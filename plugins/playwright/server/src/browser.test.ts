import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ListRootsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import {
  assertMatchingPlaywright,
  defaultCacheDirectory,
  launchBrowser,
  loadPlaywright,
  profileDir,
  rootPathFromRoots,
  type OwnedBrowser,
} from "./browser.js";

const serverDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

async function listen(server: http.Server): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("expected a TCP address");
  return `http://127.0.0.1:${address.port}`;
}

describe("profile directory", () => {
  it("matches the directory stock @playwright/mcp created for a known project root", () => {
    // Observed on macOS with stock @playwright/mcp@0.0.83 for this root.
    const root = "/Users/kedrzu/.paseo/worktrees/22dk1knh/breezy-scorpion";
    expect(path.basename(profileDir(root, {}))).toBe("mcp-chrome-e76b0d0");
    expect(profileDir(root, { PWMCP_PROFILES_DIR_FOR_TEST: "/tmp/profiles" })).toBe(path.join("/tmp/profiles", "mcp-chrome-e76b0d0"));
  });

  it("uses the stock cache directory on every platform", () => {
    const home = os.homedir();
    expect(defaultCacheDirectory({}, "darwin")).toBe(path.join(home, "Library", "Caches"));
    expect(defaultCacheDirectory({}, "linux")).toBe(path.join(home, ".cache"));
    expect(defaultCacheDirectory({ XDG_CACHE_HOME: "/xdg" }, "linux")).toBe("/xdg");
    expect(defaultCacheDirectory({}, "win32")).toBe(path.join(home, "AppData", "Local"));
    expect(defaultCacheDirectory({ LOCALAPPDATA: "C:\\Local" }, "win32")).toBe("C:\\Local");
  });

  it("takes the first file root and falls back to the working directory", () => {
    const a = path.join(os.tmpdir(), "root-a");
    const b = path.join(os.tmpdir(), "root-b");
    expect(rootPathFromRoots([{ uri: "https://example.com/x" }, { uri: pathToFileURL(a).href }, { uri: pathToFileURL(b).href }])).toBe(a);
    expect(rootPathFromRoots([])).toBe(process.cwd());
  });
});

describe("playwright copy", () => {
  it("refuses a playwright-core that is not the version @playwright/mcp declares", () => {
    const mcp = { dependencies: { "playwright-core": "1.64.0-alpha-1" } };
    expect(() => assertMatchingPlaywright(mcp, { version: "1.64.0" })).toThrow(/depends on playwright-core 1.64.0-alpha-1, but 1.64.0/);
    expect(() => assertMatchingPlaywright({}, { version: "1.64.0" })).toThrow(/declares no playwright-core/);
    expect(() => assertMatchingPlaywright(mcp, { version: "1.64.0-alpha-1" })).not.toThrow();
  });

  // The layout consumers run: `bun --install=force` ignores node_modules and resolves each
  // package from bun's cache, where a playwright-core imported from this package is a different
  // copy than the one @playwright/mcp loads.
  it("is the copy @playwright/mcp itself loads when run with bun --install=force", async () => {
    const probe = [
      `import { createRequire } from "module";`,
      `import { loadPlaywright } from "./src/browser.ts";`,
      `const ours = loadPlaywright();`,
      `const mcpRequire = createRequire(import.meta.resolve("@playwright/mcp"));`,
      `console.log(JSON.stringify({ same: ours === mcpRequire("playwright-core"), core: mcpRequire.resolve("playwright-core") }));`,
    ].join("\n");
    const proc = Bun.spawn([process.execPath, "--install=force", "-e", probe], { cwd: serverDir, stdout: "pipe", stderr: "pipe" });
    const [stdout, stderr, code] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text(), proc.exited]);
    expect(stderr).toBe("");
    expect(code).toBe(0);
    expect(JSON.parse(stdout.trim().split("\n").pop() ?? "")).toMatchObject({ same: true });
  }, 60_000);
});

// Launching needs Google Chrome (the stock channel). Locally it must run; a machine without
// Chrome skips with the reason instead of failing.
const chromeMissing = await loadPlaywright()
  .chromium.launch({ channel: "chrome", headless: true })
  .then(async (browser) => {
    await browser.close();
    return undefined;
  })
  .catch((e: unknown) => (e instanceof Error ? e.message.split("\n")[0] : String(e)));
if (chromeMissing) console.warn(`Skipping browser launch tests, Chrome cannot be launched: ${chromeMissing}`);

describe.skipIf(chromeMissing !== undefined)("launching", () => {
  let tmp: string;
  let profiles: string;
  let env: Record<string, string | undefined>;
  let site: http.Server;
  let siteUrl: string;
  const open: OwnedBrowser[] = [];

  async function launch(...args: Parameters<typeof launchBrowser>): Promise<OwnedBrowser> {
    const owned = await launchBrowser(...args);
    open.push(owned);
    return owned;
  }

  function project(name: string): string {
    const dir = path.join(tmp, name);
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  async function storedValue(owned: OwnedBrowser): Promise<string | null> {
    const page = await owned.context.newPage();
    await page.goto(siteUrl);
    return page.evaluate(() => localStorage.getItem("marker"));
  }

  beforeAll(async () => {
    tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "playwright-browser-")));
    profiles = path.join(tmp, "profiles");
    env = { ...process.env, PWMCP_PROFILES_DIR_FOR_TEST: profiles, PLAYWRIGHT_MCP_HEADLESS: "1" };
    site = http.createServer((_req, res) => res.end("<title>site</title>"));
    siteUrl = `${await listen(site)}/`;
  });

  afterAll(async () => {
    await Promise.all(open.map((owned) => owned.close()));
    await new Promise((resolve) => site.close(resolve));
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("opens the profile the stock server created for the same root, with its data", async () => {
    const root = project("stock");
    // Stock asks the client for its roots; a cwd elsewhere proves the root is what counts.
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [path.join(serverDir, "node_modules", "@playwright", "mcp", "cli.js")],
      env: Object.fromEntries(Object.entries(env).filter((e): e is [string, string] => e[1] !== undefined)),
      cwd: tmp,
      stderr: "pipe",
    });
    const client = new Client({ name: "contract-test", version: "1.0.0" }, { capabilities: { roots: {} } });
    client.setRequestHandler(ListRootsRequestSchema, async () => ({ roots: [{ uri: pathToFileURL(root).href, name: "project" }] }));
    try {
      await client.connect(transport);
      const navigated = await client.callTool({ name: "browser_navigate", arguments: { url: siteUrl } });
      expect(navigated.isError).toBeFalsy();
      const stored = await client.callTool({
        name: "browser_evaluate",
        arguments: { function: "() => localStorage.setItem('marker', 'from-stock')" },
      });
      expect(stored.isError).toBeFalsy();
      await client.callTool({ name: "browser_close", arguments: {} });
    } finally {
      await client.close();
    }

    expect(fs.readdirSync(profiles)).toEqual([path.basename(profileDir(root, env))]);
    const persistent = await launch({ profile: "persistent" }, { rootPath: root, env });
    expect(persistent.profileDir).toBe(path.join(profiles, fs.readdirSync(profiles)[0]));
    expect(await storedValue(persistent)).toBe("from-stock");

    // Fresh runs beside the persistent profile and sees none of its data.
    const fresh = await launch({ profile: "fresh" }, { rootPath: root, env });
    expect(fresh.profileDir).toBeUndefined();
    expect(await storedValue(fresh)).toBeNull();
    await Promise.all([persistent.close(), fresh.close()]);
  }, 90_000);

  it("refuses a persistent profile in use and releases it on close", async () => {
    const root = project("lock");
    const first = await launch({ profile: "persistent" }, { rootPath: root, env });
    // Stock waits up to five seconds for the lock to clear before giving up.
    await expect(launchBrowser({ profile: "persistent" }, { rootPath: root, env })).rejects.toThrow(/Browser is already in use for/);
    await first.close();
    await first.closed;
    const second = await launch({ profile: "persistent" }, { rootPath: root, env });
    await second.close();
  }, 30_000);

  it("settles `closed` and shuts a fresh browser down when the context is closed from outside", async () => {
    const fresh = await launch({ profile: "fresh" }, { rootPath: project("outside"), env });
    const browser = fresh.context.browser();
    await fresh.context.close();
    await fresh.closed;
    expect(browser?.isConnected()).toBe(false);
  }, 30_000);

  it("routes through an authenticating proxy in both profiles", async () => {
    const seen: string[] = [];
    const proxy = http.createServer((req, res) => {
      const auth = req.headers["proxy-authorization"];
      if (auth !== `Basic ${Buffer.from("user:pass").toString("base64")}`) {
        res.writeHead(407, { "Proxy-Authenticate": 'Basic realm="test"' }).end();
        return;
      }
      seen.push(req.url ?? "");
      res.end("<title>via-proxy</title>");
    });
    const server = await listen(proxy);
    try {
      for (const profile of ["fresh", "persistent"] as const) {
        const owned = await launch({ profile, proxy: { server, username: "user", password: "pass" } }, { rootPath: project(`proxy-${profile}`), env });
        const page = await owned.context.newPage();
        await page.goto("http://proxied.test/");
        expect(await page.title()).toBe("via-proxy");
        await owned.close();
      }
      expect(seen.filter((url) => url === "http://proxied.test/")).toHaveLength(2);
    } finally {
      await new Promise((resolve) => proxy.close(resolve));
    }
  }, 60_000);
});
