import { afterAll, afterEach, beforeAll, describe, expect, it } from "bun:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import {
  CallToolResultSchema,
  ListRootsRequestSchema,
  ToolListChangedNotificationSchema,
  type CallToolResult,
  type TextContent,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { launchBrowser, loadPlaywright, profileDir, type OwnedBrowser } from "./browser.js";
import { readCredentials, type Env, type ProfileMode } from "./config.js";
import { Docker, type DockerCall, type DockerOutput } from "./docker.js";
import { BrowserSession, SESSION_TOOL } from "./session.js";
import { TunnelPool, type TunnelSource } from "./tunnels.js";

const serverDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const stockCli = path.join(serverDir, "node_modules", "@playwright", "mcp", "cli.js");

let tmp: string;
let profiles: string;
let env: Env;
const cleanups: (() => Promise<unknown>)[] = [];

beforeAll(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "playwright-session-")));
  profiles = path.join(tmp, "profiles");
  // No PLAYWRIGHT_MCP_* from the developer's shell: stock reads them, the wrapper does not.
  const inherited = Object.entries(process.env).filter(([key]) => !key.startsWith("PLAYWRIGHT_MCP_"));
  env = {
    ...Object.fromEntries(inherited),
    PWMCP_PROFILES_DIR_FOR_TEST: profiles,
    PLAYWRIGHT_MCP_HEADLESS: "1",
    TEST_VPN_USER: "vpn-user-7f3a",
    TEST_VPN_PASSWORD: "vpn-password-91c2",
  };
});

afterEach(async () => {
  for (const cleanup of cleanups.splice(0).reverse()) await cleanup();
});

afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

function project(name: string): string {
  const dir = path.join(tmp, name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function definedEnv(): Record<string, string> {
  return Object.fromEntries(Object.entries(env).filter((e): e is [string, string] => e[1] !== undefined));
}

// An MCP client that, like Claude Code, declares roots: the project is its only root.
function outerClient(root: string) {
  const client = new Client({ name: "session-test", version: "1.0.0" }, { capabilities: { roots: {} } });
  client.setRequestHandler(ListRootsRequestSchema, async () => ({ roots: [{ uri: pathToFileURL(root).href, name: "project" }] }));
  let listChanged = 0;
  const waiters: (() => void)[] = [];
  client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
    listChanged++;
    for (const resolve of waiters.splice(0)) resolve();
  });
  return {
    client,
    listChanged: () => listChanged,
    nextListChanged: () => new Promise<void>((resolve) => waiters.push(resolve)),
  };
}

async function connectWrapper(root: string, profile: ProfileMode, options: { tunnels?: TunnelSource; log?: (message: string) => void } = {}) {
  const session = new BrowserSession({ initial: { profile }, serverInfo: { name: "test", version: "0.0.0" }, env, log: () => {}, ...options });
  const outer = outerClient(root);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await session.connect(serverTransport);
  await outer.client.connect(clientTransport);
  cleanups.push(async () => {
    await outer.client.close();
    await session.close();
  });
  return { session, ...outer };
}

async function call(client: Client, name: string, args: Record<string, unknown> = {}, timeout?: number): Promise<CallToolResult> {
  return client.request({ method: "tools/call", params: { name, arguments: args } }, CallToolResultSchema, { timeout });
}

function text(result: CallToolResult): string {
  return result.content
    .filter((c): c is TextContent => c.type === "text")
    .map((c) => c.text)
    .join("\n");
}

async function ok(client: Client, name: string, args: Record<string, unknown> = {}, timeout?: number): Promise<string> {
  const result = await call(client, name, args, timeout);
  if (result.isError) throw new Error(`${name} failed: ${text(result)}`);
  return text(result);
}

async function listen(handler: http.RequestListener): Promise<string> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  cleanups.push(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("expected a TCP address");
  return `http://127.0.0.1:${address.port}/`;
}

async function siteUrl(): Promise<string> {
  return listen((_req, res) => res.end("<title>site</title>"));
}

// gluetun behind a substituted `docker`: every call is recorded, a started "container" is a
// local authenticating proxy and control server that accept exactly the credentials docker
// received in its environment. The VPN login is read from the secret files mounted at
// /run/secrets, as gluetun reads it at startup. A region starting "Bad" exits with gluetun's
// error, which here also carries the VPN login, to prove it is redacted.
function fakeGluetun() {
  const calls: DockerCall[] = [];
  const mounts: { source: string; login: Record<string, string> }[] = [];
  const containers = new Map<string, Record<string, string>>();
  const proxied: string[] = [];
  let proxyPort = 0;
  let controlPort = 0;
  const ready = (async () => {
    proxyPort = Number(new URL(await listen((req, res) => {
      const env = [...containers.values()].find((e) => req.headers["proxy-authorization"] === `Basic ${Buffer.from(`${e.HTTPPROXY_USER}:${e.HTTPPROXY_PASSWORD}`).toString("base64")}`);
      if (!env) return void res.writeHead(407, { "Proxy-Authenticate": 'Basic realm="gluetun"' }).end();
      proxied.push(req.url ?? "");
      res.end(`<title>via ${env.SERVER_REGIONS}</title>`);
    })).port);
    controlPort = Number(new URL(await listen((req, res) => {
      const env = [...containers.values()].find((e) => req.headers["x-api-key"] === JSON.parse(e.HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE).apikey);
      if (!env) return void res.writeHead(401).end();
      res.end(JSON.stringify({ public_ip: "203.0.113.7", region: `${env.SERVER_REGIONS} (ipinfo)`, country: "United States", city: "Dallas", organization: "Test" }));
    })).port);
  })();
  const out = (stdout = "", exitCode = 0, stderr = ""): DockerOutput => ({ exitCode, stdout, stderr });
  const runner = async (c: DockerCall): Promise<DockerOutput> => {
    await ready;
    calls.push(c);
    const [command, ...args] = c.args;
    const name = args.at(-1) ?? "";
    if (command === "run" && args[0] === "-d") {
      const source = args[args.indexOf("--mount") + 1]?.match(/^type=bind,source=(.+),target=\/run\/secrets,readonly$/)?.[1];
      const login: Record<string, string> = source
        ? { OPENVPN_USER: fs.readFileSync(path.join(source, "openvpn_user"), "utf8"), OPENVPN_PASSWORD: fs.readFileSync(path.join(source, "openvpn_password"), "utf8") }
        : {};
      if (source) mounts.push({ source, login });
      containers.set(args[args.indexOf("--name") + 1], { ...c.env, ...login });
      return out("0123456789ab\n");
    }
    if (command === "inspect") {
      const env = containers.get(name);
      if (!env) return out("", 1, `Error: No such container: ${name}`);
      const bad = env.SERVER_REGIONS.startsWith("Bad");
      const state = { Running: !bad, ExitCode: bad ? 1 : 0, Health: { Status: bad ? "unhealthy" : "healthy" } };
      const ports = bad ? {} : { "8888/tcp": [{ HostIp: "127.0.0.1", HostPort: String(proxyPort) }], "8000/tcp": [{ HostIp: "127.0.0.1", HostPort: String(controlPort) }] };
      return out(`${JSON.stringify(state)}\t${JSON.stringify(ports)}\n`);
    }
    if (command === "logs") {
      const env = containers.get(name) ?? {};
      return out(
        `INFO [http proxy] user ${env.HTTPPROXY_USER}\n` +
          `ERROR VPN settings: login ${env.OPENVPN_USER}:${env.OPENVPN_PASSWORD}: the region specified is not valid: none of ${env.SERVER_REGIONS} is one of the choices available US Texas, US Kansas\n`
      );
    }
    if (command === "rm") for (const n of args.slice(1)) containers.delete(n);
    // image inspect, the server-list check (fresh), ps, rm: success with nothing to say.
    return out();
  };
  return {
    calls,
    mounts,
    proxied,
    // Every value a start handed to docker that must stay secret.
    secrets: () =>
      [...mounts.flatMap((m) => Object.values(m.login)), ...calls.flatMap((c) => [c.env.HTTPPROXY_PASSWORD, c.env.HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE])].filter(
        (v): v is string => !!v
      ),
    pool: (log: (message: string) => void = () => {}) =>
      new TunnelPool({
        provider: "private internet access",
        credentials: () => readCredentials({ file: path.join(tmp, "no-credentials.env"), userKey: "TEST_VPN_USER", passwordKey: "TEST_VPN_PASSWORD" }, env),
        docker: new Docker({ runner }),
        owner: { pid: process.pid, startTime: "Tue Oct 13 10:00:00 2026" },
        log,
      }),
  };
}

async function readMarker(client: Client): Promise<string> {
  return ok(client, "browser_evaluate", { function: "() => localStorage.getItem('marker')" });
}

describe("tool list", () => {
  it("is the stock CLI's list, unchanged, plus browser_session with only `profile`", async () => {
    const root = project("tools");
    const stock = outerClient(root).client;
    await stock.connect(new StdioClientTransport({ command: process.execPath, args: [stockCli], env: definedEnv(), cwd: tmp, stderr: "pipe" }));
    cleanups.push(() => stock.close());
    const { client } = await connectWrapper(root, "persistent");

    const stockTools = (await stock.listTools()).tools;
    const tools = (await client.listTools()).tools;
    expect(stockTools.length).toBeGreaterThan(10);
    expect(tools.slice(0, -1)).toEqual(stockTools);
    const sessionTool: Tool | undefined = tools.at(-1);
    expect(sessionTool?.name).toBe(SESSION_TOOL);
    expect(Object.keys(sessionTool?.inputSchema.properties ?? {})).toEqual(["profile"]);
    expect(stock.getServerCapabilities()?.tools?.listChanged).toBe(true);
    expect(client.getServerCapabilities()?.tools?.listChanged).toBe(true);
  }, 30_000);

  it("offers `region` only when the project configures VPN regions", async () => {
    const { client } = await connectWrapper(project("tools-geo"), "fresh", { tunnels: fakeGluetun().pool() });
    const sessionTool = (await client.listTools()).tools.at(-1);
    expect(Object.keys(sessionTool?.inputSchema.properties ?? {})).toEqual(["profile", "region"]);

    const { client: plain } = await connectWrapper(project("tools-plain"), "fresh");
    const result = await call(plain, SESSION_TOOL, { region: "US Texas" });
    expect(result.isError).toBe(true);
    expect(text(result)).toContain("region: VPN regions are not configured for this project");
  });

  it("rejects an unknown profile without touching the session", async () => {
    const { client, session } = await connectWrapper(project("invalid"), "fresh");
    const result = await call(client, SESSION_TOOL, { profile: "incognito" });
    expect(result.isError).toBe(true);
    expect(text(result)).toContain('profile: expected one of "persistent", "fresh"');
    expect(session.state.profile).toBe("fresh");
    expect(session.browser).toBeUndefined();
  });
});

// Driving the browser needs Google Chrome (the stock channel). Locally it must run; a machine
// without Chrome skips with the reason instead of failing.
const chromeMissing = await loadPlaywright()
  .chromium.launch({ channel: "chrome", headless: true })
  .then(async (browser) => {
    await browser.close();
    return undefined;
  })
  .catch((e: unknown) => (e instanceof Error ? e.message.split("\n")[0] : String(e)));
if (chromeMissing) console.warn(`Skipping browser session tests, Chrome cannot be launched: ${chromeMissing}`);

describe.skipIf(chromeMissing !== undefined)("browser session", () => {
  it("starts persistent on the stock profile and switches fresh <-> persistent", async () => {
    const root = project("switch");
    const site = await siteUrl();
    const { client, session, listChanged } = await connectWrapper(root, "persistent");
    expect(session.browser).toBeUndefined(); // launched on demand, like stock

    await ok(client, "browser_navigate", { url: site });
    expect(session.browser?.profileDir).toBe(profileDir(root, env));
    await ok(client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'kept')" });

    // Stock announces its page tools after a navigation too; the swap adds exactly one.
    const beforeSwitch = listChanged();
    expect(JSON.parse(await ok(client, SESSION_TOOL, { profile: "fresh" }))).toEqual({ profile: "fresh", region: null });
    expect(listChanged()).toBe(beforeSwitch + 1);
    expect(session.browser?.profileDir).toBeUndefined();
    await ok(client, "browser_navigate", { url: site });
    expect(await readMarker(client)).toContain("null");

    // An omitted profile keeps the current one; calling fresh again starts clean.
    await ok(client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'fresh-only')" });
    expect(JSON.parse(await ok(client, SESSION_TOOL))).toEqual({ profile: "fresh", region: null });
    await ok(client, "browser_navigate", { url: site });
    expect(await readMarker(client)).toContain("null");

    const beforeReturn = listChanged();
    await ok(client, SESSION_TOOL, { profile: "persistent" });
    expect(listChanged()).toBe(beforeReturn + 1);
    await ok(client, "browser_navigate", { url: site });
    expect(await readMarker(client)).toContain('"kept"');
  }, 60_000);

  it("runs two fresh sessions of one project side by side without sharing data", async () => {
    const root = project("parallel");
    const site = await siteUrl();
    const a = await connectWrapper(root, "fresh");
    const b = await connectWrapper(root, "fresh");
    await Promise.all([ok(a.client, "browser_navigate", { url: site }), ok(b.client, "browser_navigate", { url: site })]);
    await ok(a.client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'a')" });
    expect(await readMarker(b.client)).toContain("null");
    expect(await readMarker(a.client)).toContain('"a"');
    expect(fs.existsSync(profileDir(root, env))).toBe(false);
  }, 60_000);

  it("keeps the previous state when the persistent profile is held by someone else", async () => {
    const root = project("atomic");
    const site = await siteUrl();
    const { client, session, listChanged } = await connectWrapper(root, "fresh");
    await ok(client, "browser_navigate", { url: site });
    await ok(client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'still-here')" });
    const before = session.browser;
    const announced = listChanged();

    const holder = await launchBrowser({ profile: "persistent" }, { rootPath: root, env });
    cleanups.push(() => holder.close());
    const result = await call(client, SESSION_TOOL, { profile: "persistent" });
    expect(result.isError).toBe(true);
    expect(text(result)).toContain("The browser stays in the fresh profile. Browser is already in use for");

    // Same state, same browser, same tab: nothing was swapped.
    expect(session.state.profile).toBe("fresh");
    expect(session.browser).toBe(before);
    expect(listChanged()).toBe(announced);
    expect(await readMarker(client)).toContain('"still-here"');
  }, 60_000);

  it("keeps the persistent state when relaunching it fails, and reopens it once the profile is free", async () => {
    const root = project("relaunch");
    const site = await siteUrl();
    const { client, session } = await connectWrapper(root, "persistent");
    await ok(client, "browser_navigate", { url: site });
    await ok(client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'profile-data')" });
    const dir = profileDir(root, env);
    const lock = path.join(dir, "SingletonLock");
    // The moment the session's own browser lets go of the profile, a live process claims it,
    // the way another Chrome would. The session cannot get its profile back while it is held.
    const owner = Bun.spawn(["sleep", "60"]);
    cleanups.push(async () => owner.kill());
    session.browser?.closed.then(() => {
      fs.rmSync(lock, { force: true });
      fs.symlinkSync(`${os.hostname()}-${owner.pid}`, lock);
    });

    const result = await call(client, SESSION_TOOL, { profile: "persistent" });
    expect(result.isError).toBe(true);
    expect(text(result)).toContain("The browser stays in the persistent profile. Browser is already in use for");
    expect(text(result)).toContain("Reopening the persistent profile failed as well");
    expect(session.state.profile).toBe("persistent");

    owner.kill();
    await owner.exited;
    fs.rmSync(lock, { force: true });
    await ok(client, "browser_navigate", { url: site });
    expect(await readMarker(client)).toContain('"profile-data"');
  }, 60_000);

  it("routes through the region's proxy, back directly with null, and keeps the previous state when a region fails", async () => {
    const root = project("region");
    const site = await siteUrl();
    const gluetun = fakeGluetun();
    // Persistent: switching closes the browser before relaunching it, so a failed region must fail before that.
    const { client, session, listChanged } = await connectWrapper(root, "persistent", { tunnels: gluetun.pool() });
    await ok(client, "browser_navigate", { url: site });

    const tunnel = { publicIp: "203.0.113.7", ipGeolocation: { country: "United States", region: "US Texas (ipinfo)", city: "Dallas" } };
    expect(JSON.parse(await ok(client, SESSION_TOOL, { region: "US Texas" }))).toEqual({ profile: "persistent", region: "US Texas", tunnel });
    expect(await ok(client, "browser_navigate", { url: "http://proxied.test/" })).toContain("Page Title: via US Texas");
    await ok(client, "browser_evaluate", { function: "() => localStorage.setItem('marker', 'texas')" });
    const before = session.browser;
    const announced = listChanged();

    const failed = await call(client, SESSION_TOOL, { region: "Bad Place", profile: "fresh" });
    expect(failed.isError).toBe(true);
    expect(text(failed)).toContain("The browser stays in the persistent profile via US Texas. The VPN tunnel for \"Bad Place\" stopped while starting: ERROR VPN settings");
    expect(text(failed)).toContain("choices available: US Texas, US Kansas");
    expect(session.status).toEqual({ profile: "persistent", region: "US Texas", tunnel });
    expect(session.browser).toBe(before);
    expect(listChanged()).toBe(announced);
    expect(await readMarker(client)).toContain('"texas"');
    const pageLoads = () => gluetun.proxied.filter((url) => url === "http://proxied.test/").length;
    expect(pageLoads()).toBe(1);

    expect(JSON.parse(await ok(client, SESSION_TOOL, { region: null }))).toEqual({ profile: "persistent", region: null });
    expect(await ok(client, "browser_navigate", { url: site })).toContain("Page Title: site");
    await call(client, "browser_navigate", { url: "http://proxied.test/" });
    expect(pageLoads()).toBe(1);
  }, 60_000);

  it("never lets VPN credentials, the proxy password or the API key reach docker's arguments, tool results or logs, nor the VPN login a container's env", async () => {
    const gluetun = fakeGluetun();
    const logs: string[] = [];
    const log = (message: string) => void logs.push(message);
    const { client } = await connectWrapper(project("leak"), "fresh", { tunnels: gluetun.pool(log), log });
    const results = [
      await call(client, SESSION_TOOL, { region: "US Texas" }),
      await call(client, "browser_navigate", { url: "http://proxied.test/" }),
      await call(client, SESSION_TOOL, { region: "Bad Place" }),
      await call(client, SESSION_TOOL, {}),
    ];
    expect(results.map((r) => !!r.isError)).toEqual([false, false, true, false]);
    expect(text(results[1])).toContain("Page Title: via US Texas");

    // The login reached gluetun as its secret files only, deleted once each start was over. The
    // container env, which `docker inspect` shows, never had it.
    const login = { OPENVPN_USER: "vpn-user-7f3a", OPENVPN_PASSWORD: "vpn-password-91c2" };
    expect(gluetun.calls.filter((c) => c.args[0] === "run" && c.args[1] === "-d")).toHaveLength(2);
    expect(gluetun.mounts.map((m) => m.login)).toEqual([login, login]);
    for (const { source } of gluetun.mounts) expect(fs.existsSync(source)).toBe(false);
    const containerEnv = gluetun.calls.flatMap((c) => Object.values(c.env));
    for (const secret of Object.values(login)) expect(containerEnv.filter((value) => value.includes(secret))).toEqual([]);
    const secrets = [...new Set([...gluetun.secrets(), ...gluetun.secrets().map((role) => role.match(/"apikey":"(\w+)"/)?.[1] ?? role)])];
    // The login, then per start the proxy password, the control role and its API key.
    expect(secrets).toHaveLength(2 + 2 * 3);
    const exposed = [...gluetun.calls.flatMap((c) => c.args), ...results.map(text), ...logs];
    for (const secret of secrets) expect(exposed.filter((line) => line.includes(secret))).toEqual([]);
    expect(text(results[2])).toContain("ERROR VPN settings: login [redacted]:[redacted]");
  }, 60_000);

  it("starts over after browser_close, in the current profile", async () => {
    const site = await siteUrl();
    const { client, session } = await connectWrapper(project("close"), "fresh");
    await ok(client, "browser_navigate", { url: site });
    const first = session.browser;
    if (!first) throw new Error("expected a running browser");

    await ok(client, "browser_close");
    await first.closed;
    expect(session.browser).toBeUndefined();
    await ok(client, "browser_navigate", { url: site });
    expect(session.browser).not.toBe(first);
    expect(session.browser?.state.profile).toBe("fresh");
  }, 60_000);

  const endings: [string, (owned: OwnedBrowser) => Promise<unknown>][] = [
    ["the user closes the window", async (owned) => Promise.all(owned.context.pages().map((page) => page.close()))],
    ["the user quits the browser", async (owned) => owned.context.close()],
    [
      "the browser crashes",
      async (owned) => {
        const cdp = await owned.context.browser()?.newBrowserCDPSession();
        // A crashed browser never answers, so the call is not awaited.
        void cdp?.send("Browser.crash").catch(() => {});
        await owned.closed;
      },
    ],
  ];
  for (const [what, end] of endings) {
    for (const profile of ["persistent", "fresh"] as const) {
      it(`works again after ${what} (${profile})`, async () => {
        const site = await siteUrl();
        const { client, session } = await connectWrapper(project(`ending-${profile}-${what.replace(/\W+/g, "-")}`), profile);
        await ok(client, "browser_navigate", { url: site });
        const owned = session.browser;
        if (!owned) throw new Error("expected a running browser");
        await end(owned);
        expect(await ok(client, "browser_navigate", { url: site })).toContain("Page Title: site");
        expect(session.state.profile).toBe(profile);
      }, 60_000);
    }
  }

  it("relays the tools a page registers at runtime and forwards calls to them", async () => {
    const page = await listen((_req, res) =>
      res.end(`<title>webmcp</title><script>
        document.modelContext = {
          getTools: () => [{ name: "add", description: "Adds two numbers", inputSchema: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } } } }],
          executeTool: (tool, args) => String(args.a + args.b),
        };
      </script>`)
    );
    const { client, nextListChanged } = await connectWrapper(project("webmcp"), "fresh");
    const changed = nextListChanged();
    await ok(client, "browser_navigate", { url: page });
    await changed;

    const tools = (await client.listTools()).tools.map((t) => t.name);
    expect(tools).toContain("webmcp_add");
    expect(tools.at(-1)).toBe(SESSION_TOOL);
    expect(await ok(client, "webmcp_add", { a: 2, b: 3 })).toContain("5");
  }, 60_000);

  // A real call past the MCP SDK's 60 s default request timeout, which would cut it otherwise.
  it("does not cut a forwarded call that runs longer than 60 s", async () => {
    const site = await siteUrl();
    const { client } = await connectWrapper(project("long"), "fresh");
    await ok(client, "browser_navigate", { url: site });
    const started = Date.now();
    const result = await ok(client, "browser_evaluate", { function: "() => new Promise((r) => setTimeout(() => r('finished'), 61000))" }, 120_000);
    expect(Date.now() - started).toBeGreaterThan(60_000);
    expect(result).toContain('"finished"');
  }, 120_000);
});

// Process ids of the Chrome browsers a process started.
function chromeChildren(pid: number): number[] {
  const out = Bun.spawnSync(["ps", "-A", "-o", "pid=,ppid=,command="]).stdout.toString();
  return out
    .split("\n")
    .map((line) => line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/))
    .filter((m): m is RegExpMatchArray => m !== null && Number(m[2]) === pid && /chrome/i.test(m[3]))
    .map((m) => Number(m[1]));
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitFor(condition: () => boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (condition()) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return condition();
}

describe.skipIf(chromeMissing !== undefined)("main over stdio", () => {
  // VPN regions of a provider, with the login in TEST_VPN_USER / TEST_VPN_PASSWORD.
  const geo = { provider: "private internet access", credentials: { file: "no-credentials.env", userKey: "TEST_VPN_USER", passwordKey: "TEST_VPN_PASSWORD" } };
  // PATH without any docker on it.
  const pathWithoutDocker = (process.env.PATH ?? "")
    .split(path.delimiter)
    .filter((dir) => dir && !fs.existsSync(path.join(dir, "docker")))
    .join(path.delimiter);

  // The command .mcp.json runs, with a project whose config starts sessions fresh.
  async function start(name: string, options: { geo?: typeof geo; env?: Record<string, string> } = {}) {
    const root = project(name);
    fs.mkdirSync(path.join(root, ".claude"));
    fs.writeFileSync(path.join(root, ".claude", "playwright.json"), JSON.stringify({ profile: "fresh", geo: options.geo }));
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: ["--install=force", path.join(serverDir, "src", "main.ts"), "--project", root],
      env: { ...definedEnv(), ...options.env },
      cwd: root,
      stderr: "pipe",
    });
    let stderr = "";
    transport.stderr?.on("data", (chunk: Buffer) => (stderr += chunk.toString()));
    const { client } = outerClient(root);
    await client.connect(transport);
    const pid = transport.pid;
    if (pid === null) throw new Error("expected a server process");
    const exited = new Promise<void>((resolve) => {
      const check = setInterval(() => {
        if (!alive(pid)) {
          clearInterval(check);
          resolve();
        }
      }, 100);
    });
    cleanups.push(async () => {
      if (alive(pid)) process.kill(pid, "SIGKILL");
      await client.close();
    });
    const site = await siteUrl();
    expect(await ok(client, "browser_navigate", { url: site })).toContain("Page Title: site");
    const chrome = chromeChildren(pid);
    expect(chrome.length).toBeGreaterThan(0);
    // The project's config made it fresh: nothing was written to a persistent profile.
    expect(fs.existsSync(profileDir(root, env))).toBe(false);
    return { client, transport, pid, chrome, exited, stderr: () => stderr };
  }

  it("closes Chrome and exits on SIGTERM", async () => {
    const server = await start("main-sigterm");
    process.kill(server.pid, "SIGTERM");
    await server.exited;
    expect(server.stderr()).toContain("shutting down (SIGTERM)");
    expect(await waitFor(() => server.chrome.every((pid) => !alive(pid)), 5_000)).toBe(true);
  }, 90_000);

  it("closes Chrome and exits when the client closes stdin", async () => {
    const server = await start("main-stdin");
    await server.transport.close();
    await server.exited;
    expect(server.stderr()).toContain("shutting down (stdin closed)");
    expect(await waitFor(() => server.chrome.every((pid) => !alive(pid)), 5_000)).toBe(true);
  }, 90_000);

  it("starts and serves without Docker; only a VPN region fails, saying why", async () => {
    const server = await start("main-no-docker", { geo, env: { PATH: pathWithoutDocker } });
    expect((await server.client.listTools()).tools.at(-1)?.inputSchema.properties).toHaveProperty("region");
    const result = await call(server.client, SESSION_TOOL, { region: "US Texas" });
    expect(result.isError).toBe(true);
    expect(text(result)).toContain("The browser stays in the fresh profile, connected directly. Docker is not installed");
    expect(await ok(server.client, "browser_navigate", { url: await siteUrl() })).toContain("Page Title: site");
    expect(server.stderr()).toContain("looking for orphaned VPN containers failed: Docker is not installed");
  }, 90_000);

  // A recording docker stands in: the startup sweep's `ps` takes a while, and `ps` for this
  // server's own containers names one.
  it("sweeps orphans in the background at startup and removes its own containers on shutdown", async () => {
    const bin = project("fake-docker-bin");
    const calls = path.join(bin, "calls.log");
    fs.writeFileSync(
      path.join(bin, "docker"),
      `#!/bin/sh
echo "$*" >> "${calls}"
[ "$1" = ps ] || exit 0
case "$*" in
  *"owner=$PPID "*)
    start=$(TZ=UTC LC_ALL=C ps -o lstart= -p "$PPID")
    printf 'playwright-mcp-%s-us-texas\t%s\t%s\n' "$PPID" "$PPID" "$(echo $start)" ;;
  *) sleep 5; echo "sweep finished" >> "${calls}" ;;
esac
`,
      { mode: 0o755 }
    );
    const server = await start("main-fake-docker", { geo, env: { PATH: `${bin}${path.delimiter}${pathWithoutDocker}` } });
    const log = () => fs.readFileSync(calls, "utf-8");
    // start() navigated already: the sweep was not in the way.
    expect(log()).toContain("ps -a --filter label=kedrzu.playwright-mcp.owner --format");
    expect(log()).not.toContain("sweep finished");

    process.kill(server.pid, "SIGTERM");
    await server.exited;
    expect(log()).toContain(`ps -a --filter label=kedrzu.playwright-mcp.owner=${server.pid} --format`);
    expect(log()).toContain(`rm -f playwright-mcp-${server.pid}-us-texas`);
    // The sweep's docker outlives the server; let it end.
    expect(await waitFor(() => log().includes("sweep finished"), 10_000)).toBe(true);
  }, 90_000);
});
