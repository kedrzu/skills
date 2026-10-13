import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { randomBytes } from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { Docker, processStartTime } from "./docker.js";
import { errorLine, openvpnLines, TunnelPool, type TunnelPoolOptions } from "./tunnels.js";

describe("gluetun diagnostics", () => {
  const invalid =
    "2026-10-13T10:00:00Z ERROR VPN settings: provider settings: server selection: for VPN service provider private internet access: " +
    "the region specified is not valid: value is not one of the possible choices: none of us atlantis is one of the choices available " +
    "AU Adelaide, AU Brisbane, CA Toronto, US Atlanta, US Texas, US Kansas, US West";

  it("keeps the valid region names that start like the requested one, and counts the rest", () => {
    expect(errorLine(`INFO starting\n${invalid}\nINFO shutting down`, "US Atlantis")).toBe(
      "ERROR VPN settings: provider settings: server selection: for VPN service provider private internet access: " +
        "the region specified is not valid: value is not one of the possible choices: none of us atlantis is one of the choices available: " +
        "US Atlanta, US Texas, US Kansas, US West (and 3 more)"
    );
  });

  it("lists the first valid names when none start like the requested region", () => {
    expect(errorLine(invalid, "Texas")).toEndWith("choices available: AU Adelaide, AU Brisbane, CA Toronto, US Atlanta, US Texas, US Kansas, US West");
  });

  it("selects the last OpenVPN lines and nothing else", () => {
    const logs = ["INFO [http proxy] user pw-1234", ...[1, 2, 3, 4, 5, 6].map((n) => `INFO [openvpn] attempt ${n}`), "INFO [healthcheck] unhealthy"].join("\n");
    expect(openvpnLines(logs)).toEqual([2, 3, 4, 5, 6].map((n) => `INFO [openvpn] attempt ${n}`));
  });
});

// Real Docker is required locally; a machine without it skips with the reason.
const dockerMissing = await new Docker()
  .listOwned()
  .then(() => undefined)
  .catch((e: unknown) => (e instanceof Error ? e.message : String(e)));
if (dockerMissing) console.warn(`Skipping tunnel tests on Docker: ${dockerMissing}`);

// Stands in for gluetun with the same interface and none of the VPN: the `update` command writes
// servers.json into the volume, a start needs the VPN login in /run/secrets and fails while
// /gluetun/fail-starts exists, a region starting "Bad" exits with gluetun's error, one starting
// "Stuck" never becomes healthy, and any other one serves /v1/publicip/ip on 8000: with no IP
// for 2 s after reporting healthy for "Late", never for "NoIp".
const FAKE_GLUETUN = `
if [ "$1" = update ]; then
  sleep 2
  echo "$*" >> /gluetun/updates.log
  echo '{}' > /gluetun/servers.json
  exit 0
fi
[ -f /gluetun/servers.json ] || { echo "ERROR no server list in /gluetun"; exit 1; }
[ -s /run/secrets/openvpn_user ] && [ -s /run/secrets/openvpn_password ] || { echo "ERROR VPN settings: OpenVPN user is empty"; exit 1; }
[ -f /gluetun/fail-starts ] && { echo "ERROR fake start failure"; exit 1; }
case "$SERVER_REGIONS" in
  Bad*)
    echo "2026-10-13T10:00:00Z ERROR VPN settings: the region specified is not valid: value is not one of the possible choices: none of $SERVER_REGIONS is one of the choices available Fake Alpha, Fake Beta, Other Gamma"
    exit 1 ;;
  Stuck*)
    while :; do
      echo "2026-10-13T10:00:00Z INFO [openvpn] TLS key negotiation failed to occur within 60 seconds"
      echo "2026-10-13T10:00:00Z INFO [http proxy] user $HTTPPROXY_USER"
      sleep 1
    done ;;
esac
mkdir -p /www/v1/publicip
ip() { printf '{"public_ip":"%s","region":"%s","country":"Testland","city":"Faketown"}' "$1" "$SERVER_REGIONS" > /www/ip.tmp && mv /www/ip.tmp /www/v1/publicip/ip; }
case "$SERVER_REGIONS" in
  Late*) ip ""; (sleep 2; ip 203.0.113.7) & ;;
  NoIp*) ip "" ;;
  *) ip 203.0.113.7 ;;
esac
touch /tmp/healthy
exec httpd -f -p 8000 -h /www
`;

describe.skipIf(dockerMissing !== undefined)("tunnel pool on Docker", () => {
  const run = randomBytes(4).toString("hex");
  // Names and labels of their own, so nothing here can touch a real server's containers or volumes.
  const labelPrefix = `kedrzu.playwright-mcp-test-${run}`;
  const image = `playwright-mcp-test-gluetun:${run}`;
  const docker = new Docker({ labelPrefix });
  let tmp: string;
  let pools = 0;

  beforeAll(async () => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "playwright-tunnels-"));
    fs.writeFileSync(path.join(tmp, "fake-gluetun.sh"), FAKE_GLUETUN);
    fs.writeFileSync(
      path.join(tmp, "Dockerfile"),
      [
        "FROM busybox:1.37.0",
        "COPY fake-gluetun.sh /fake-gluetun.sh",
        "HEALTHCHECK --interval=1s --timeout=1s --retries=1 CMD test -f /tmp/healthy",
        'ENTRYPOINT ["sh", "/fake-gluetun.sh"]',
      ].join("\n")
    );
    const build = Bun.spawnSync(["docker", "build", "--quiet", "--tag", image, tmp], { stderr: "pipe" });
    if (build.exitCode !== 0) throw new Error(`building the fake gluetun image failed: ${build.stderr.toString()}`);
  }, 180_000);

  afterAll(async () => {
    await docker.remove((await docker.listOwned()).map((c) => c.name));
    const volumes = dockerOut(["volume", "ls", "--quiet", "--filter", `name=pwmcp-test-${run}`]).split("\n").filter(Boolean);
    if (volumes.length) dockerOut(["volume", "rm", ...volumes]);
    dockerOut(["image", "rm", image]);
    fs.rmSync(tmp, { recursive: true, force: true });
  }, 60_000);

  function dockerOut(args: string[]): string {
    return Bun.spawnSync(["docker", ...args], { stderr: "pipe" }).stdout.toString().trim();
  }

  // A pool with a server-list volume of its own unless `prefix` shares one.
  function pool(options: Partial<TunnelPoolOptions> = {}): TunnelPool {
    return new TunnelPool({
      provider: "test provider",
      credentials: () => ({ username: "vpn-user-5e1d", password: "vpn-password-c08b" }),
      docker,
      image,
      namePrefix: `pwmcp-test-${run}-${++pools}`,
      log: () => {},
      ...options,
    });
  }

  function updates(volume: string): string[] {
    return dockerOut(["run", "--rm", "-v", `${volume}:/gluetun`, "busybox:1.37.0", "cat", "/gluetun/updates.log"]).split("\n").filter(Boolean);
  }

  function exists(name: string): boolean {
    return Bun.spawnSync(["docker", "inspect", "--type", "container", name], { stdout: "ignore", stderr: "ignore" }).exitCode === 0;
  }

  function names(): Promise<string[]> {
    return docker.listOwned().then((containers) => containers.map((c) => c.name));
  }

  it("starts a tunnel on loopback ports with its owner's labels and the VPN login out of its config, reuses it while healthy, replaces it when gone and removes it on close", async () => {
    const tunnels = pool();
    const tunnel = await tunnels.acquire("Fake Alpha");
    expect(tunnel).toMatchObject({
      region: "Fake Alpha",
      publicIp: "203.0.113.7",
      ipGeolocation: { country: "Testland", region: "Fake Alpha", city: "Faketown" },
    });
    expect(tunnel.proxy.server).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);

    const [name] = await names();
    expect(name).toMatch(new RegExp(`^pwmcp-test-${run}-${pools}-${process.pid}-fake-alpha-[0-9a-f]{6}$`));
    const [ports, labels, mounts] = dockerOut(["inspect", "--format", "{{json .NetworkSettings.Ports}}\t{{json .Config.Labels}}\t{{json .Mounts}}", name]).split("\t");
    const bindings = Object.values(JSON.parse(ports)).flat();
    expect(bindings).toHaveLength(2);
    expect(bindings.every((b) => typeof b === "object" && b !== null && "HostIp" in b && b.HostIp === "127.0.0.1")).toBe(true);
    expect(JSON.parse(labels)).toMatchObject({
      [`${labelPrefix}.owner`]: String(process.pid),
      [`${labelPrefix}.owner-start`]: await processStartTime(process.pid),
    });
    // gluetun read the login from /run/secrets; docker keeps no copy, and the host's is gone.
    const inspected = dockerOut(["inspect", name]);
    expect(inspected).not.toContain("vpn-user-5e1d");
    expect(inspected).not.toContain("vpn-password-c08b");
    const secrets = JSON.parse(mounts).find((m: { Destination?: string }) => m.Destination === "/run/secrets");
    expect(secrets).toMatchObject({ Type: "bind", RW: false });
    expect(fs.existsSync(secrets.Source)).toBe(false);

    // Region names match case-insensitively, like gluetun's.
    expect((await tunnels.acquire("fake alpha")).proxy).toEqual(tunnel.proxy);
    dockerOut(["rm", "-f", name]);
    const restarted = await tunnels.acquire("Fake Alpha");
    expect(restarted.proxy.password).not.toBe(tunnel.proxy.password);
    // The server list was refreshed for the first start only.
    expect(updates(tunnels.volume)).toEqual(["update -enduser -providers test provider"]);

    await tunnels.close();
    expect(exists(name)).toBe(false);
    expect(await docker.listOwned()).toEqual([]);
  }, 90_000);

  it("refreshes a shared server list once when two sessions start at the same time", async () => {
    const namePrefix = `pwmcp-test-${run}-shared`;
    const [a, b] = [pool({ namePrefix }), pool({ namePrefix })];
    await Promise.all([a.acquire("Fake Alpha"), b.acquire("Fake Beta")]);
    expect(updates(a.volume)).toHaveLength(1);
    await Promise.all([a.close(), b.close()]);
  }, 90_000);

  it("stops the least recently used tunnel beyond the limit, but never the one in use", async () => {
    const namePrefix = `pwmcp-test-${run}-lru`;
    const tunnels = pool({ maxSize: 1, namePrefix });
    const running = async () => (await names()).map((name) => name.slice(`${namePrefix}-${process.pid}-`.length).replace(/-[0-9a-f]{6}$/, "")).sort();
    await tunnels.acquire("Fake Alpha");
    await tunnels.acquire("Fake Beta", "Fake Alpha");
    expect(await running()).toEqual(["fake-alpha", "fake-beta"]);
    await tunnels.acquire("Other Gamma", "Fake Beta");
    expect(await running()).toEqual(["fake-beta", "other-gamma"]);
    await tunnels.close();
  }, 90_000);

  it("keeps a tunnel that fails its check until a replacement is up, as the browser may still use it", async () => {
    const tunnels = pool();
    const first = await tunnels.acquire("Fake Alpha");
    const [old] = await names();
    dockerOut(["exec", old, "rm", "/tmp/healthy"]);
    while (dockerOut(["inspect", "--format", "{{.State.Health.Status}}", old]) !== "unhealthy") await Bun.sleep(200);

    dockerOut(["exec", old, "touch", "/gluetun/fail-starts"]);
    expect(String(await tunnels.acquire("Fake Alpha").catch((e: unknown) => e))).toContain("ERROR fake start failure");
    expect(await names()).toEqual([old]);

    dockerOut(["exec", old, "rm", "/gluetun/fail-starts"]);
    const second = await tunnels.acquire("Fake Alpha");
    expect(second.proxy.password).not.toBe(first.proxy.password);
    const after = await names();
    expect(after).toHaveLength(1);
    expect(after[0]).not.toBe(old);
    await tunnels.close();
  }, 90_000);

  it("waits for the public IP gluetun fetches only after reporting healthy, and fails a tunnel that never gets one", async () => {
    const tunnels = pool({ healthTimeoutMs: 5_000 });
    expect((await tunnels.acquire("Late Delta")).publicIp).toBe("203.0.113.7");
    const error = String(await tunnels.acquire("NoIp Epsilon").catch((e: unknown) => e));
    expect(error).toContain('The VPN tunnel for "NoIp Epsilon" is up, but gluetun did not report its public IP within 5 s.');
    expect((await names()).filter((name) => name.includes("noip"))).toEqual([]);
    await tunnels.close();
  }, 60_000);

  it("fails a bad region with gluetun's error and the valid names, and removes its container", async () => {
    const tunnels = pool();
    const error = await tunnels.acquire("Bad Region").catch((e: unknown) => e);
    expect(String(error)).toContain(
      'The VPN tunnel for "Bad Region" stopped while starting: ERROR VPN settings: the region specified is not valid: value is not one of the possible choices: none of Bad Region is one of the choices available: Fake Alpha, Fake Beta, Other Gamma'
    );
    expect(await docker.listOwned()).toEqual([]);
    await tunnels.close();
  }, 60_000);

  it("fails a tunnel that never becomes healthy with the last OpenVPN lines only, and removes its container", async () => {
    const tunnels = pool({ healthTimeoutMs: 3_000 });
    const error = String(await tunnels.acquire("Stuck Region").catch((e: unknown) => e));
    expect(error).toContain('The VPN tunnel for "Stuck Region" did not become healthy within 3 s. Last OpenVPN messages:\n');
    expect(error).toContain("INFO [openvpn] TLS key negotiation failed to occur within 60 seconds");
    expect(error).not.toContain("[http proxy]");
    expect(await docker.listOwned()).toEqual([]);
    await tunnels.close();
  }, 60_000);
});
