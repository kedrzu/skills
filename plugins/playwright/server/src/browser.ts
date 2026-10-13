// The browser this server owns. It is launched here, not by @playwright/mcp, so a session can
// switch between a persistent and a fresh profile and route through a proxy; the resulting
// BrowserContext is what @playwright/mcp drives.
//
// Everything that decides where the persistent profile lives and how the browser starts mirrors
// stock @playwright/mcp (playwright-core/lib/coreBundle.js: createUserDataDir,
// createPersistentBrowser, createIsolatedBrowser, validateBrowserConfig, resolveCLIConfigForMCP),
// so a user keeps the logins the stock server stored for the same project. The pinned
// @playwright/mcp version and the contract test in browser.test.ts guard that.

import { createHash } from "crypto";
import * as fs from "fs";
import { createRequire } from "module";
import * as os from "os";
import * as path from "path";
import { fileURLToPath } from "url";
import type { BrowserContext, LaunchOptions } from "playwright-core";
import type { Env, ProfileMode } from "./config.js";

type Playwright = typeof import("playwright-core");

export interface ProxySettings {
  server: string; // e.g. http://127.0.0.1:41234
  username?: string;
  password?: string;
}

export interface BrowserState {
  profile: ProfileMode;
  proxy?: ProxySettings;
}

export interface LaunchContext {
  // The project root the stock server would see: the first MCP client root, else the cwd.
  rootPath: string;
  env?: Env;
}

export interface OwnedBrowser {
  readonly state: BrowserState;
  readonly context: BrowserContext;
  // The profile directory of a persistent browser; undefined for a fresh one.
  readonly profileDir: string | undefined;
  // Settles once the context is gone, whether close() ended it or it ended on its own (the
  // user quit the browser, a crash). Rejects only if shutting the browser down failed.
  readonly closed: Promise<void>;
  // Closes the browser and, for a persistent profile, releases its lock. Safe to call twice.
  close(): Promise<void>;
}

// Stock defaults when no --browser is given: chromium on the installed Chrome.
const CHANNEL = "chrome";

let playwright: Playwright | undefined;

// playwright-core exactly as @playwright/mcp resolves it. A context from any other copy (a
// direct `import "playwright"` resolves a different version under `bun --install=force`)
// would be handed to createConnection and break in subtle ways.
export function loadPlaywright(): Playwright {
  if (playwright) return playwright;
  const mcpRequire = createRequire(import.meta.resolve("@playwright/mcp"));
  assertMatchingPlaywright(mcpRequire("./package.json"), mcpRequire("playwright-core/package.json"));
  const mod: unknown = mcpRequire("playwright-core");
  if (!isPlaywright(mod)) throw new Error("playwright-core resolved next to @playwright/mcp has no chromium launcher");
  playwright = mod;
  return mod;
}

// The playwright-core found next to @playwright/mcp must be the exact version it declares;
// anything else means the install is not the one bun.lock pins.
export function assertMatchingPlaywright(mcpPackage: unknown, corePackage: unknown): void {
  const expected = isRecord(mcpPackage) && isRecord(mcpPackage.dependencies) ? mcpPackage.dependencies["playwright-core"] : undefined;
  const actual = isRecord(corePackage) ? corePackage.version : undefined;
  if (typeof expected !== "string") throw new Error("@playwright/mcp's package.json declares no playwright-core dependency");
  if (expected !== actual) {
    throw new Error(`@playwright/mcp depends on playwright-core ${expected}, but ${String(actual)} was resolved next to it`);
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function isPlaywright(mod: unknown): mod is Playwright {
  return (
    isRecord(mod) &&
    isRecord(mod.chromium) &&
    typeof mod.chromium.launch === "function" &&
    typeof mod.chromium.launchPersistentContext === "function"
  );
}

// Stock defaultCacheDirectory() (playwright-core registry).
export function defaultCacheDirectory(env: Env = process.env, platform: NodeJS.Platform = process.platform): string {
  if (platform === "linux") return env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  if (platform === "darwin") return path.join(os.homedir(), "Library", "Caches");
  if (platform === "win32") return env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  throw new Error("Unsupported platform: " + platform);
}

// Stock createUserDataDir(): one profile per browser channel and project root.
export function profileDir(rootPath: string, env: Env = process.env): string {
  const base = env.PWMCP_PROFILES_DIR_FOR_TEST ?? path.join(defaultCacheDirectory(env), "ms-playwright-mcp");
  const rootToken = createHash("sha256").update(rootPath).digest("hex").slice(0, 7);
  return path.join(base, `mcp-${CHANNEL}-${rootToken}`);
}

// Stock firstRootPath(): the first root that is a file URL, else the working directory.
export function rootPathFromRoots(roots: readonly { uri: string }[]): string {
  for (const root of roots) {
    const url = new URL(root.uri);
    if (url.protocol !== "file:") continue;
    try {
      return fileURLToPath(url);
    } catch (e) {
      // Stock reads a Windows file URL without a drive letter from its pathname.
      if (process.platform === "win32" && e instanceof Error && "code" in e && e.code === "ERR_INVALID_FILE_URL_PATH") {
        return decodeURIComponent(url.pathname);
      }
      if (e instanceof TypeError) continue;
      throw e;
    }
  }
  return process.cwd();
}

// Stock envToBoolean().
function envToBoolean(value: string | undefined): boolean | undefined {
  if (value === "true" || value === "1") return true;
  if (value === "false" || value === "0") return false;
  return undefined;
}

export async function launchBrowser(state: BrowserState, { rootPath, env = process.env }: LaunchContext): Promise<OwnedBrowser> {
  const { chromium } = loadPlaywright();
  // The launch options stock passes for the default chromium/chrome config.
  const options: LaunchOptions = {
    channel: CHANNEL,
    // A display-less Linux box cannot show a window; PLAYWRIGHT_MCP_HEADLESS overrides.
    headless: envToBoolean(env.PLAYWRIGHT_MCP_HEADLESS) ?? (os.platform() === "linux" && !env.DISPLAY),
    // validateBrowserConfig: true everywhere for the chrome channel.
    chromiumSandbox: true,
    // The MCP server decides when the browser dies, not a signal sent to the process group.
    handleSIGINT: false,
    handleSIGTERM: false,
    proxy: state.proxy,
  };

  if (state.profile === "fresh") {
    // No user data dir at all: nothing from the persistent profile, nothing left behind.
    const browser = await chromium.launch(options).catch((e: unknown) => {
      throw launchError(e);
    });
    const context = await browser.newContext().catch(async (e: unknown) => {
      await browser.close();
      throw e;
    });
    // The context can also be closed from outside (by @playwright/mcp); the browser goes with it.
    const closed = contextClosed(context).then(() => browser.close());
    return {
      state,
      context,
      profileDir: undefined,
      closed,
      close: async () => {
        await context.close();
        await closed;
      },
    };
  }

  const dir = profileDir(rootPath, env);
  await fs.promises.mkdir(dir, { recursive: true });
  if (await isProfileLocked5Times(dir)) throw profileInUse(dir);
  const context = await chromium
    .launchPersistentContext(dir, {
      ...options,
      // Stock keeps extensions enabled in the persistent profile.
      ignoreDefaultArgs: ["--disable-extensions"],
    })
    .catch((e: unknown) => {
      throw launchError(e, dir);
    });
  const closed = contextClosed(context);
  return {
    state,
    context,
    profileDir: dir,
    closed,
    // Closing a persistent context ends the browser process, which releases the profile lock.
    close: async () => {
      await context.close();
      await closed;
    },
  };
}

function contextClosed(context: BrowserContext): Promise<void> {
  return new Promise((resolve) => context.once("close", () => resolve()));
}

function profileInUse(dir: string): Error {
  return new Error(`Browser is already in use for ${dir}; another session holds this persistent profile. Use the fresh profile to run beside it.`);
}

// Stock maps these launch failures to actionable messages.
function launchError(e: unknown, dir?: string): unknown {
  if (!(e instanceof Error)) return e;
  if (e.message.includes("Executable doesn't exist")) {
    const match = e.message.match(/Executable doesn't exist at ([^\r\n]+)/);
    const location = match ? `; expected executable at ${match[1].trim()}` : "";
    return new Error(`Browser "${CHANNEL}" is not installed${location}. Run \`npx @playwright/mcp install-browser ${CHANNEL}\` to install`, { cause: e });
  }
  if (e.message.includes("cannot open shared object file: No such file or directory")) {
    return new Error(`Missing system dependencies required to run browser ${CHANNEL}. Install them with: sudo npx playwright install-deps ${CHANNEL}`, { cause: e });
  }
  if (dir && (e.message.includes("ProcessSingleton") || e.message.includes("exitCode=21"))) {
    return profileInUse(dir);
  }
  return e;
}

// Stock isProfileLocked5Times(): a profile just released by another process may still show
// its lock for a moment, so look again for up to five seconds.
async function isProfileLocked5Times(dir: string): Promise<boolean> {
  for (let i = 0; i < 5; i++) {
    if (!isProfileLocked(dir)) return false;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return true;
}

function isProfileLocked(dir: string): boolean {
  if (process.platform === "win32") {
    try {
      fs.closeSync(fs.openSync(path.join(dir, "lockfile"), "r+"));
      return false;
    } catch (e) {
      return !(e instanceof Error && "code" in e && e.code === "ENOENT");
    }
  }
  // Chrome's SingletonLock is a symlink to "<host>-<pid>"; the lock is live while that pid is.
  let target: string;
  try {
    target = fs.readlinkSync(path.join(dir, "SingletonLock"));
  } catch {
    return false; // no lock, or not a symlink Chrome would have written
  }
  const pid = parseInt(target.split("-").pop() || "", 10);
  if (isNaN(pid)) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false; // the owner is gone; Chrome takes over a stale lock
  }
}
