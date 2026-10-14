// VPN regions: a pool of gluetun containers, one per region, each exposing an authenticated HTTP
// proxy the browser goes through. Only the browser uses the VPN; the host network stays as it is.
//
// gluetun's built-in server list goes stale (dead server IPs), so before the first start the pool
// refreshes it into a volume shared by every session and mounted as /gluetun in every tunnel.
// The volume is a cache with no owner. One refresh runs at a time across sessions: the updating
// container has a fixed name, and a second `docker run --name` with it fails, so that session
// waits for the first one instead.
//
// gluetun's logs can carry the proxy username and more; an error passes on only the lines that
// explain it (the ERROR line, the last [openvpn] lines), with every secret of the start redacted.
// The VPN login reaches gluetun as its secret files (/run/secrets/<key>), never in the container's
// env, which `docker inspect` shows; the host copy is deleted once the start is over.

import { randomBytes } from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import type { ProxySettings } from "./browser.js";
import type { Credentials } from "./config.js";
import { currentOwner, Docker, DockerTimeoutError, firstLine, formatDuration, type ContainerState, type Owner } from "./docker.js";

// Pinned by the manifest-list digest: the tag alone can be pushed again.
export const GLUETUN_IMAGE = "qmcgaw/gluetun:v3.41.3@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027";

const PROXY_PORT = 8888;
const CONTROL_PORT = 8000;
const POLL_MS = 500;
const PULL_TIMEOUT_MS = 5 * 60_000;
const UPDATE_TIMEOUT_MS = 3 * 60_000;
const SERVER_LIST_MAX_AGE_MS = 24 * 60 * 60_000;

export interface TunnelInfo {
  publicIp: string;
  // ipinfo's database as gluetun sees it; may differ from the tested service's own geolocation.
  ipGeolocation: { country: string; region: string; city: string };
}

export interface Tunnel extends TunnelInfo {
  region: string;
  proxy: ProxySettings;
}

// What the browser session needs from a pool. `keep` is a region the caller still uses, never
// evicted to make room.
export interface TunnelSource {
  acquire(region: string, keep?: string | null): Promise<Tunnel>;
}

export interface TunnelPoolOptions {
  provider: string; // gluetun's VPN_SERVICE_PROVIDER
  // Read only when a container has to start, so a missing login fails just that call.
  credentials: () => Credentials;
  docker?: Docker;
  image?: string;
  // Prefix of container and volume names.
  namePrefix?: string;
  owner?: Owner;
  maxSize?: number;
  healthTimeoutMs?: number;
  log?: (message: string) => void;
}

export class TunnelError extends Error {}

interface Entry {
  region: string;
  name: string;
  proxy: ProxySettings;
  controlPort: number;
  apiKey: string;
}

export class TunnelPool implements TunnelSource {
  private readonly docker: Docker;
  private readonly provider: string;
  private readonly credentials: () => Credentials;
  private readonly image: string;
  private readonly prefix: string;
  private readonly maxSize: number;
  private readonly healthTimeoutMs: number;
  private readonly log: (message: string) => void;
  private readonly ownerOption: Owner | undefined;
  private ownerPromise: Promise<Owner> | undefined;
  // Least recently used first.
  private readonly tunnels = new Map<string, Entry>();
  private serverListCheckedAt: number | undefined;
  private queue: Promise<void> = Promise.resolve();
  private closing: Promise<void> | undefined;

  constructor(options: TunnelPoolOptions) {
    this.docker = options.docker ?? new Docker();
    this.provider = options.provider;
    this.credentials = options.credentials;
    this.image = options.image ?? GLUETUN_IMAGE;
    this.prefix = options.namePrefix ?? "playwright-mcp";
    this.ownerOption = options.owner;
    this.maxSize = options.maxSize ?? 4;
    this.healthTimeoutMs = options.healthTimeoutMs ?? 90_000;
    this.log = options.log ?? ((message) => console.error(`playwright-mcp: ${message}`));
  }

  get volume(): string {
    return `${this.prefix}-servers-${slug(this.provider)}`;
  }

  // A healthy tunnel for `region`: the pooled one if it still is, else a new container.
  acquire(region: string, keep?: string | null): Promise<Tunnel> {
    return this.exclusive(async () => {
      this.assertOpen();
      const key = slug(region);
      if (!key) throw new TunnelError(`"${region}" is not a region name`);
      const pooled = this.tunnels.get(key);
      if (pooled) {
        const info = await this.check(pooled);
        if (info) {
          this.tunnels.delete(key);
          this.tunnels.set(key, pooled);
          return { region: pooled.region, proxy: pooled.proxy, ...info };
        }
        this.log(`the VPN container for ${pooled.region} is not healthy any more; starting another`);
      }
      // The browser may still go through the old container: it stays until its replacement is up.
      const { entry, info } = await this.start(region.trim(), key);
      if (pooled) await this.docker.remove([pooled.name]).catch((e: unknown) => this.log(`removing ${pooled.name} failed: ${message(e)}`));
      this.tunnels.delete(key);
      this.tunnels.set(key, entry);
      await this.evict(key, keep);
      return { region: entry.region, proxy: entry.proxy, ...info };
    });
  }

  // Removes every container of this owner, including ones still starting. Safe to call twice.
  close(): Promise<void> {
    this.closing ??= (async () => {
      const removed = await this.docker.removeOwnedBy(await this.owner());
      this.tunnels.clear();
      if (removed.length) this.log(`removed VPN containers: ${removed.join(", ")}`);
    })();
    return this.closing;
  }

  // Containers left behind by servers that are gone.
  async pruneOrphans(): Promise<string[]> {
    return this.docker.pruneDeadOwners();
  }

  private async start(region: string, key: string): Promise<{ entry: Entry; info: TunnelInfo }> {
    const credentials = this.credentials();
    const owner = await this.owner();
    await this.ensureImage();
    await this.ensureServerList(owner);

    // Unique, so a replacement can start beside the container it replaces.
    const name = `${this.prefix}-${owner.pid}-${key}-${randomHex(3)}`;
    const proxy = { username: `pw-${randomHex(6)}`, password: randomHex(24) };
    const apiKey = randomHex(24);
    const secrets = [credentials.username, credentials.password, proxy.password, apiKey];
    // A directory only this user can read, holding one file per secret; mounted as /run/secrets.
    const secretFiles = fs.mkdtempSync(path.join(os.tmpdir(), "playwright-mcp-secrets-"));
    fs.writeFileSync(path.join(secretFiles, "openvpn_user"), credentials.username, { mode: 0o600 });
    fs.writeFileSync(path.join(secretFiles, "openvpn_password"), credentials.password, { mode: 0o600 });
    this.log(`starting the VPN container for ${region}`);
    try {
      await this.docker.start({
        name,
        image: this.image,
        owner,
        capAdd: ["NET_ADMIN"],
        devices: ["/dev/net/tun"],
        publish: [PROXY_PORT, CONTROL_PORT],
        volumes: { [this.volume]: "/gluetun" },
        binds: { [secretFiles]: "/run/secrets" },
        env: {
          VPN_SERVICE_PROVIDER: this.provider,
          SERVER_REGIONS: region,
          HTTPPROXY: "on",
          HTTPPROXY_USER: proxy.username,
          HTTPPROXY_PASSWORD: proxy.password,
          HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE: JSON.stringify({ auth: "apikey", apikey: apiKey }),
        },
      });
      this.assertOpen();
      const deadline = Date.now() + this.healthTimeoutMs;
      const state = await this.waitHealthy(name, region, secrets, deadline);
      const proxyPort = hostPort(state, PROXY_PORT);
      const entry: Entry = {
        region,
        name,
        proxy: { server: `http://127.0.0.1:${proxyPort}`, ...proxy },
        controlPort: hostPort(state, CONTROL_PORT),
        apiKey,
      };
      return { entry, info: await this.waitPublicIp(entry, deadline) };
    } catch (e) {
      await this.docker.remove([name]).catch((removeError: unknown) => this.log(`removing ${name} failed: ${message(removeError)}`));
      throw e;
    } finally {
      // gluetun reads its settings once, at startup.
      fs.rmSync(secretFiles, { recursive: true, force: true });
    }
  }

  private async waitHealthy(name: string, region: string, secrets: string[], deadline: number): Promise<ContainerState> {
    for (;;) {
      const state = await this.docker.inspect(name);
      if (!state) throw new TunnelError(`The VPN container for "${region}" disappeared while starting.`);
      if (state.running && state.health === "healthy") return state;
      if (!state.running) {
        const error = errorLine(await this.docker.logs(name), region);
        throw new TunnelError(
          `The VPN tunnel for "${region}" stopped while starting` + (error ? `: ${redact(error, secrets)}` : ` (exit code ${state.exitCode}).`)
        );
      }
      if (Date.now() >= deadline) {
        const lines = openvpnLines(await this.docker.logs(name)).map((line) => redact(line, secrets));
        throw new TunnelError(
          `The VPN tunnel for "${region}" did not become healthy within ${formatDuration(this.healthTimeoutMs)}.` +
            (lines.length ? ` Last OpenVPN messages:\n${lines.join("\n")}` : "")
        );
      }
      await sleep(POLL_MS);
    }
  }

  // The tunnel's public IP and gluetun's geolocation of it, or undefined if it is not healthy.
  private async check(entry: Entry): Promise<TunnelInfo | undefined> {
    try {
      const state = await this.docker.inspect(entry.name);
      if (!state?.running || state.health !== "healthy") return undefined;
      return await this.readPublicIp(entry);
    } catch (e) {
      this.log(`checking the VPN container for ${entry.region} failed: ${message(e)}`);
      return undefined;
    }
  }

  // gluetun reports healthy before it has fetched the public IP, so a new tunnel waits for it.
  private async waitPublicIp(entry: Entry, deadline: number): Promise<TunnelInfo> {
    for (;;) {
      const info = await this.readPublicIp(entry);
      if (info) return info;
      if (Date.now() >= deadline) {
        throw new TunnelError(
          `The VPN tunnel for "${entry.region}" is up, but gluetun did not report its public IP within ${formatDuration(this.healthTimeoutMs)}.`
        );
      }
      await sleep(POLL_MS);
    }
  }

  // Undefined while gluetun has no public IP: before its first fetch, during a restart of the
  // tunnel, or after the fetch failed.
  private async readPublicIp(entry: Entry): Promise<TunnelInfo | undefined> {
    const response = await fetch(`http://127.0.0.1:${entry.controlPort}/v1/publicip/ip`, {
      headers: { "X-API-Key": entry.apiKey },
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) throw new TunnelError(`gluetun's control server answered ${response.status} for the public IP of "${entry.region}".`);
    const body: unknown = await response.json();
    return parsePublicIp(body);
  }

  private async ensureImage(): Promise<void> {
    if (await this.docker.hasImage(this.image)) return;
    this.log(`pulling ${this.image}`);
    try {
      await this.docker.pull(this.image, PULL_TIMEOUT_MS);
    } catch (e) {
      throw new TunnelError(`Pulling ${this.image} failed: ${message(e)}`, { cause: e });
    }
  }

  private async ensureServerList(owner: Owner): Promise<void> {
    if (this.serverListCheckedAt !== undefined && Date.now() - this.serverListCheckedAt < SERVER_LIST_MAX_AGE_MS) return;
    const updater = `${this.prefix}-servers-update-${slug(this.provider)}`;
    for (let attempt = 0; !(await this.serverListFresh(owner)); attempt++) {
      if (attempt === 3) throw new TunnelError(`The ${this.provider} server list in volume ${this.volume} could not be refreshed.`);
      this.log(`refreshing the ${this.provider} server list`);
      let output;
      try {
        output = await this.docker.runToCompletion(
          { name: updater, image: this.image, owner, volumes: { [this.volume]: "/gluetun" }, command: ["update", "-enduser", "-providers", this.provider] },
          UPDATE_TIMEOUT_MS
        );
      } catch (e) {
        if (!(e instanceof DockerTimeoutError)) throw e;
        await this.docker.remove([updater]);
        throw new TunnelError(`Refreshing the ${this.provider} server list did not finish within ${formatDuration(UPDATE_TIMEOUT_MS)}.`, { cause: e });
      }
      if (output.exitCode === 0) break;
      if (/already in use|Conflict/i.test(output.stderr)) {
        // Another session is refreshing it; its result is ours too.
        this.log(`waiting for another session refreshing the ${this.provider} server list`);
        if (!(await this.docker.wait(updater, UPDATE_TIMEOUT_MS))) {
          throw new TunnelError(`Another session's refresh of the ${this.provider} server list did not finish within ${formatDuration(UPDATE_TIMEOUT_MS)}.`);
        }
        continue;
      }
      const error = errorLine(`${output.stdout}\n${output.stderr}`) ?? firstLine(output.stderr);
      throw new TunnelError(`Refreshing the ${this.provider} server list failed: ${error || `exit code ${output.exitCode}`}`);
    }
    this.serverListCheckedAt = Date.now();
  }

  // servers.json exists in the volume and is younger than the maximum age, by the container's clock.
  private async serverListFresh(owner: Owner): Promise<boolean> {
    const minutes = Math.max(1, Math.floor(SERVER_LIST_MAX_AGE_MS / 60_000));
    const output = await this.docker.runToCompletion(
      {
        image: this.image,
        owner,
        volumes: { [this.volume]: "/gluetun" },
        entrypoint: "sh",
        command: ["-c", `test -n "$(find /gluetun/servers.json -mmin -${minutes} 2>/dev/null)"`],
      },
      60_000
    );
    if (output.exitCode === 0) return true;
    if (output.exitCode === 1) return false;
    throw new TunnelError(`Checking the server list in volume ${this.volume} failed: ${firstLine(output.stderr) || `exit code ${output.exitCode}`}`);
  }

  private async evict(added: string, keep: string | null | undefined): Promise<void> {
    const kept = keep ? slug(keep) : undefined;
    for (const [key, entry] of this.tunnels) {
      if (this.tunnels.size <= this.maxSize) return;
      if (key === added || key === kept) continue;
      this.tunnels.delete(key);
      this.log(`stopping the least recently used VPN container (${entry.region})`);
      await this.docker.remove([entry.name]).catch((e: unknown) => this.log(`removing ${entry.name} failed: ${message(e)}`));
    }
  }

  private owner(): Promise<Owner> {
    this.ownerPromise ??= this.ownerOption ? Promise.resolve(this.ownerOption) : currentOwner();
    return this.ownerPromise;
  }

  private assertOpen(): void {
    if (this.closing) throw new TunnelError("The VPN tunnels are shutting down");
  }

  private exclusive<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.queue.then(fn);
    this.queue = run.then(
      () => undefined,
      () => undefined
    );
    return run;
  }
}

// Region names as container-name-safe keys; gluetun compares region names case-insensitively.
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// The last ERROR line of a gluetun log, from "ERROR" on. When it lists the valid region names,
// it keeps those that start like the requested region (e.g. every "US …" for "US Atlantis"), or
// the first few, and says how many it left out.
export function errorLine(logs: string, region?: string): string | undefined {
  const line = logs
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => /\bERROR\b/.test(l))
    .at(-1);
  if (!line) return undefined;
  const error = line.slice(line.search(/\bERROR\b/));
  const marker = "choices available ";
  const at = error.indexOf(marker);
  if (at < 0) return clip(error, 1000);
  const choices = error
    .slice(at + marker.length)
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  const head = error.slice(0, at + marker.length - 1);
  const word = region?.trim().split(/\s+/)[0]?.toLowerCase();
  const alike = word ? choices.filter((c) => c.toLowerCase() === word || c.toLowerCase().startsWith(`${word} `)) : [];
  const shown = alike.length ? alike : choices.slice(0, 30);
  const omitted = choices.length - shown.length;
  return `${clip(head, 500)}: ${shown.join(", ")}` + (omitted ? ` (and ${omitted} more)` : "");
}

// The last OpenVPN messages of a gluetun log: why a tunnel does not come up.
export function openvpnLines(logs: string, count = 5): string[] {
  return logs
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.includes("[openvpn]"))
    .slice(-count)
    .map((l) => clip(l, 300));
}

export function redact(text: string, secrets: string[]): string {
  return secrets.filter(Boolean).reduce((out, secret) => out.split(secret).join("[redacted]"), text);
}

// gluetun's /v1/publicip/ip: { public_ip, country, region, city, … }.
function parsePublicIp(body: unknown): TunnelInfo | undefined {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return undefined;
  const fields: Record<string, unknown> = { ...body };
  const text = (key: string) => (typeof fields[key] === "string" ? String(fields[key]) : "");
  const publicIp = text("public_ip");
  if (!publicIp) return undefined;
  return { publicIp, ipGeolocation: { country: text("country"), region: text("region"), city: text("city") } };
}

function hostPort(state: ContainerState, containerPort: number): number {
  const port = state.ports.find((p) => p.containerPort === containerPort);
  if (!port) throw new TunnelError(`The VPN container publishes no port for ${containerPort}`);
  return port.hostPort;
}

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
