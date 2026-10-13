// Per-project configuration: <project>/.claude/playwright.json, committed and shared by the
// team. The file and each of its fields are optional, but whatever is there must be valid:
// a typo never falls back to defaults silently.
//
// The file holds no secret. VPN credentials are named by key and read only when a region
// is requested (readCredentials), from the environment or a KEY=value file.

import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export const CONFIG_FILE = path.join(".claude", "playwright.json");

export const PROFILE_MODES = ["persistent", "fresh"] as const;
export type ProfileMode = (typeof PROFILE_MODES)[number];

export type Env = Record<string, string | undefined>;

// Where the VPN login comes from. `file` is absolute once loaded.
export interface CredentialsSource {
  file: string;
  userKey: string;
  passwordKey: string;
}

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
  rejectUnknown(creds, ["file", "userKey", "passwordKey"], "geo.credentials.", errors);
  const userKey = requiredString(creds, "userKey", "geo.credentials.", errors);
  const passwordKey = requiredString(creds, "passwordKey", "geo.credentials.", errors);
  let file = defaultCredentialsFile(env);
  if (creds.file !== undefined) {
    if (typeof creds.file === "string" && creds.file.trim()) file = path.resolve(projectDir, expandHome(creds.file));
    else errors.push("geo.credentials.file: expected a non-empty path");
  }
  if (provider === undefined || userKey === undefined || passwordKey === undefined) return undefined;
  return { provider, credentials: { file, userKey, passwordKey } };
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

// The VPN login. A non-empty environment variable named like the key wins over the file;
// the file is read only when a key is missing from the environment. Errors name keys and
// the file, never a value.
export function readCredentials(source: CredentialsSource, env: Env = process.env): Credentials {
  const keys = [source.userKey, source.passwordKey];
  const notInEnv = keys.filter((k) => !env[k]);
  const fromFile = notInEnv.length ? readCredentialsFile(source.file, notInEnv) : {};
  const username = env[source.userKey] || fromFile[source.userKey];
  const password = env[source.passwordKey] || fromFile[source.passwordKey];
  if (!username || !password) {
    const missing = keys.filter((k) => !env[k] && !fromFile[k]);
    throw new ConfigError(
      `VPN credentials ${missing.join(" / ")} are set neither in the environment nor in ${source.file}. ` +
        "Store them with the secrets plugin (secret.py set)."
    );
  }
  return { username, password };
}

function readCredentialsFile(file: string, missing: string[]): Record<string, string> {
  try {
    return parseEnvFile(fs.readFileSync(file, "utf-8"));
  } catch (e) {
    const reason = e instanceof Error && "code" in e && e.code === "ENOENT" ? "does not exist" : "cannot be read";
    throw new ConfigError(
      `VPN credentials ${missing.join(" / ")} are not in the environment and ${file} ${reason}. ` +
        "Store them with the secrets plugin (secret.py set) or point geo.credentials.file at the right file."
    );
  }
}
