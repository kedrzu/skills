// Per-project configuration: <project>/.claude/playwright.json, committed and shared by the
// team. The file and each of its fields are optional, but whatever is there must be valid:
// a typo never falls back to defaults silently.
//
// The file holds no secret. VPN credentials are named by key and read only when a region
// is requested (readCredentials), from the environment, a KEY=value file or a command's output.

import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export const CONFIG_FILE = path.join(".claude", "playwright.json");

export const PROFILE_MODES = ["persistent", "fresh"] as const;
export type ProfileMode = (typeof PROFILE_MODES)[number];

export type Env = Record<string, string | undefined>;

// Where the VPN login comes from: a KEY=value file (absolute once loaded) or a command run in
// `cwd` (the project) whose stdout holds KEY=value lines. Never both.
export type CredentialsSource = { userKey: string; passwordKey: string } & (
  | { file: string; command?: undefined; cwd?: undefined }
  | { command: string[]; cwd: string; file?: undefined }
);

// A wrapper such as a secret store's `run` may hit the network.
export const CREDENTIALS_COMMAND_TIMEOUT_MS = 60_000;

export interface GeoConfig {
  provider: string; // gluetun's VPN_SERVICE_PROVIDER
  credentials: CredentialsSource;
}

export interface ProjectConfig {
  profile: ProfileMode;
  geo?: GeoConfig;
}

export interface Credentials {
  username: string;
  password: string;
}

export class ConfigError extends Error {}

export function expandHome(p: string): string {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2));
  return p;
}

// The `secrets` plugin's shared store: ${CLAUDE_CONFIG_DIR:-~/.claude}/secrets/.env.
export function defaultCredentialsFile(env: Env = process.env): string {
  const configDir = env.CLAUDE_CONFIG_DIR?.trim() || path.join(os.homedir(), ".claude");
  return path.join(expandHome(configDir), "secrets", ".env");
}

// Missing file → defaults. Anything present but invalid → ConfigError listing every problem.
export function loadProjectConfig(projectDir: string, env: Env = process.env): ProjectConfig {
  const file = path.join(projectDir, CONFIG_FILE);
  let text: string;
  try {
    text = fs.readFileSync(file, "utf-8");
  } catch (e) {
    if (e instanceof Error && "code" in e && e.code === "ENOENT") return { profile: "persistent" };
    throw e;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    throw new ConfigError(`${file}: invalid JSON (${e instanceof Error ? e.message : String(e)})`);
  }
  const errors: string[] = [];
  const config = parseConfig(raw, projectDir, env, errors);
  if (errors.length || !config) {
    throw new ConfigError(`Invalid Playwright config in ${file}:\n- ${errors.join("\n- ")}`);
  }
  return config;
}

function parseConfig(raw: unknown, projectDir: string, env: Env, errors: string[]): ProjectConfig | undefined {
  if (!isObject(raw)) {
    errors.push("expected a JSON object");
    return undefined;
  }
  rejectUnknown(raw, ["profile", "geo"], "", errors);

  let profile: ProfileMode = "persistent";
  if (raw.profile !== undefined) {
    const value = raw.profile;
    const mode = PROFILE_MODES.find((m) => m === value);
    if (mode) profile = mode;
    else errors.push(`profile: expected one of ${PROFILE_MODES.map((m) => `"${m}"`).join(", ")}`);
  }

  if (raw.geo === undefined) return { profile };
  const geo = parseGeo(raw.geo, projectDir, env, errors);
  return geo ? { profile, geo } : undefined;
}

function parseGeo(raw: unknown, projectDir: string, env: Env, errors: string[]): GeoConfig | undefined {
  if (!isObject(raw)) {
    errors.push("geo: expected an object");
    return undefined;
  }
  rejectUnknown(raw, ["provider", "credentials"], "geo.", errors);
  const provider = requiredString(raw, "provider", "geo.", errors);

  const creds = raw.credentials;
  if (!isObject(creds)) {
    errors.push("geo.credentials: expected an object with 'userKey' and 'passwordKey'");
    return undefined;
  }
  rejectUnknown(creds, ["file", "command", "userKey", "passwordKey"], "geo.credentials.", errors);
  const userKey = requiredString(creds, "userKey", "geo.credentials.", errors);
  const passwordKey = requiredString(creds, "passwordKey", "geo.credentials.", errors);
  let file = defaultCredentialsFile(env);
  let command: string[] | undefined;
  if (creds.file !== undefined && creds.command !== undefined) {
    errors.push("geo.credentials: 'file' and 'command' are mutually exclusive, give at most one");
  } else if (creds.command !== undefined) {
    const argv = creds.command;
    if (Array.isArray(argv) && argv.length > 0 && argv.every((a) => typeof a === "string") && argv[0].trim()) command = argv;
    else errors.push("geo.credentials.command: expected a non-empty array of strings (an argv, not a shell string)");
  } else if (creds.file !== undefined) {
    if (typeof creds.file === "string" && creds.file.trim()) file = path.resolve(projectDir, expandHome(creds.file));
    else errors.push("geo.credentials.file: expected a non-empty path");
  }
  if (provider === undefined || userKey === undefined || passwordKey === undefined) return undefined;
  const where = command ? { command, cwd: projectDir } : { file };
  return { provider, credentials: { ...where, userKey, passwordKey } };
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function rejectUnknown(obj: Record<string, unknown>, known: readonly string[], prefix: string, errors: string[]) {
  for (const key of Object.keys(obj)) {
    if (!known.includes(key)) errors.push(`${prefix}${key}: unknown field`);
  }
}

function requiredString(obj: Record<string, unknown>, key: string, prefix: string, errors: string[]): string | undefined {
  const value = obj[key];
  if (typeof value === "string" && value.trim()) return value;
  errors.push(`${prefix}${key}: expected a non-empty string`);
  return undefined;
}

// Parses KEY=value lines the way the `secrets` plugin's secret.py reads them, so a value it
// stored is read back identically. Data, not shell: nothing is expanded.
export function parseEnvFile(text: string): Record<string, string> {
  const values: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim();
    if (line.startsWith("export ")) line = line.slice("export ".length).trimStart();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const eq = line.indexOf("=");
    values[line.slice(0, eq).trim()] = stripQuotes(line.slice(eq + 1).trim());
  }
  return values;
}

// Python's str.strip('"').strip("'"): every leading/trailing " then every leading/trailing '.
function stripQuotes(value: string): string {
  return value.replace(/^"+|"+$/g, "").replace(/^'+|'+$/g, "");
}

// The VPN login. A non-empty environment variable named like the key wins over the file or
// command; that is run or read only when a key is missing from the environment. Errors name
// keys and the file or command, never a value.
export function readCredentials(source: CredentialsSource, env: Env = process.env): Credentials {
  const keys = [source.userKey, source.passwordKey];
  const notInEnv = keys.filter((k) => !env[k]);
  const fromFile = notInEnv.length ? readStored(source, notInEnv, env) : {};
  const username = env[source.userKey] || fromFile[source.userKey];
  const password = env[source.passwordKey] || fromFile[source.passwordKey];
  if (!username || !password) {
    const missing = keys.filter((k) => !env[k] && !fromFile[k]);
    throw new ConfigError(
      `VPN credentials ${missing.join(" / ")} are set neither in the environment nor in ${describeSource(source)}. ` +
        storeHint(source, missing, env)
    );
  }
  return { username, password };
}

// How to supply missing keys. `secret.py set` is named only for the secrets plugin's own store;
// a project that points `credentials.file` elsewhere may not have that plugin enabled at all.
function storeHint(source: CredentialsSource, missing: string[], env: Env): string {
  if (source.command) return `Make the command print ${missing.map((k) => `${k}=…`).join(" and ")}.`;
  if (source.file === defaultCredentialsFile(env)) return "Store them with the secrets plugin (secret.py set).";
  return `Add ${missing.map((k) => `${k}=…`).join(" and ")} to ${source.file}.`;
}

function describeSource(source: CredentialsSource): string {
  return source.command ? `the output of geo.credentials.command (${source.command[0]})` : source.file;
}

function readStored(source: CredentialsSource, missing: string[], env: Env): Record<string, string> {
  return source.command ? readCredentialsCommand(source, source.command, source.cwd, env) : readCredentialsFile(source.file, source, missing, env);
}

// Runs the command and keeps only the two credential keys from its stdout: a wrapper may print
// log lines first. The message carries the exit code and argv[0], never stdout (it holds the
// values) nor stderr (a wrapper may echo what it read).
function readCredentialsCommand(source: CredentialsSource, argv: string[], cwd: string, env: Env): Record<string, string> {
  const name = argv[0];
  const fail = (reason: string): never => {
    throw new ConfigError(`geo.credentials.command (${name}) ${reason}. Run it by hand in ${cwd} to see why.`);
  };
  let result: Bun.SyncSubprocess<"pipe", "ignore">;
  try {
    result = Bun.spawnSync(argv, {
      cwd,
      env: Object.fromEntries(Object.entries(env).filter((e): e is [string, string] => e[1] !== undefined)),
      stdin: "ignore",
      stdout: "pipe",
      stderr: "ignore",
      timeout: CREDENTIALS_COMMAND_TIMEOUT_MS,
    });
  } catch {
    return fail("could not be started");
  }
  if (result.exitedDueToTimeout) return fail(`did not finish within ${CREDENTIALS_COMMAND_TIMEOUT_MS / 1000}s`);
  if (result.exitCode !== 0) return fail(`failed with exit code ${result.exitCode ?? `signal ${result.signalCode}`}`);
  const all = parseEnvFile(result.stdout.toString());
  const wanted: Record<string, string> = {};
  for (const key of [source.userKey, source.passwordKey]) if (all[key]) wanted[key] = all[key];
  return wanted;
}

function readCredentialsFile(file: string, source: CredentialsSource, missing: string[], env: Env): Record<string, string> {
  try {
    return parseEnvFile(fs.readFileSync(file, "utf-8"));
  } catch (e) {
    const reason = e instanceof Error && "code" in e && e.code === "ENOENT" ? "does not exist" : "cannot be read";
    throw new ConfigError(
      `VPN credentials ${missing.join(" / ")} are not in the environment and ${file} ${reason}. ` +
        `${storeHint(source, missing, env)} Or point geo.credentials.file at the right file.`
    );
  }
}
