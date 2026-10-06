// Per-project configuration and the machine-wide store location.
//
// A project opts in with .claude/gmail-mcp.json (committed, shared by the team) and may
// add .claude/gmail-mcp.local.json (personal, gitignored) on top. Neither file holds a
// secret: OAuth clients are referenced by path, and refresh tokens live in the store.

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { validateLabelRules, type LabelRulesConfig } from "./label-rules.js";

export const CONFIG_FILE = path.join(".claude", "gmail-mcp.json");
export const LOCAL_CONFIG_FILE = path.join(".claude", "gmail-mcp.local.json");

// Where an OAuth client's id and secret come from. Exactly one of the three.
export interface ClientSource {
  file?: string; // client JSON downloaded from the Google Cloud console
  envFile?: string; // any KEY=value file, e.g. one decrypted by sops
  clientIdKey?: string; // key names inside envFile
  clientSecretKey?: string;
  store?: string; // name of a client imported into the store with `client import`
}

export interface AccountRule {
  match: string; // email, or a glob with * ("*@example.com")
  client?: string; // limit the rule to one configured client
}

export interface FilesConfig {
  roots?: string[]; // extra directories drafts may attach files from
  attachmentsDir?: string; // where save_attachment writes
}

export interface ProjectConfig {
  clients: Record<string, ClientSource>;
  accounts?: AccountRule[];
  files?: FilesConfig;
  labels?: LabelRulesConfig;
}

export interface LoadedConfig {
  projectDir: string;
  config: ProjectConfig;
  files: string[]; // config files that were read
}

export class ConfigError extends Error {}

export function storeDir(env = process.env): string {
  if (env.GMAIL_MCP_HOME) return expandHome(env.GMAIL_MCP_HOME);
  const claude = env.CLAUDE_CONFIG_DIR ? expandHome(env.CLAUDE_CONFIG_DIR) : path.join(os.homedir(), ".claude");
  return path.join(claude, "gmail-mcp");
}

export function expandHome(p: string): string {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2));
  return p;
}

// Paths in the config are relative to the project directory; ~ means the home directory.
export function resolvePath(projectDir: string, p: string): string {
  return path.resolve(projectDir, expandHome(p));
}

// The project directory as passed by Claude Code. An unexpanded ${CLAUDE_PROJECT_DIR}
// (an older Claude Code, or a manual run) falls back to the working directory.
export function projectDirFrom(arg: string | undefined): string {
  if (!arg || arg.includes("${")) return process.cwd();
  return path.resolve(expandHome(arg));
}

function readJson(file: string): unknown {
  let text: string;
  try {
    text = fs.readFileSync(file, "utf-8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw e;
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new ConfigError(`${file}: invalid JSON (${(e as Error).message})`);
  }
}

// Appends one layer's list to the other's. A layer whose value is not an array (a JSON
// string, say) is passed through untouched so validateConfig reports it: spreading
// "~/Notes" would turn it into ["~", "/", ...], and "/" would allow every path on disk.
function appendLayers<T>(base: T[] | undefined, local: T[] | undefined): T[] | undefined {
  if (base !== undefined && !Array.isArray(base)) return base;
  if (local !== undefined && !Array.isArray(local)) return local;
  return base || local ? [...(base ?? []), ...(local ?? [])] : undefined;
}

// The local file layers over the shared one: clients are merged by name, accounts and
// file roots are appended, attachmentsDir and labels replace.
export function mergeConfigs(base: Partial<ProjectConfig>, local: Partial<ProjectConfig>): Partial<ProjectConfig> {
  return {
    clients: { ...base.clients, ...local.clients },
    accounts: appendLayers(base.accounts, local.accounts),
    files: {
      roots: appendLayers(base.files?.roots, local.files?.roots) ?? [],
      attachmentsDir: local.files?.attachmentsDir ?? base.files?.attachmentsDir,
    },
    labels: local.labels ?? base.labels,
  };
}

// Null when the project has no config at all (the plugin is installed but not set up).
export function loadConfig(projectDir: string): LoadedConfig | null {
  const sharedPath = path.join(projectDir, CONFIG_FILE);
  const localPath = path.join(projectDir, LOCAL_CONFIG_FILE);
  const shared = readJson(sharedPath);
  const local = readJson(localPath);
  if (shared === undefined && local === undefined) return null;

  for (const [file, value] of [[sharedPath, shared], [localPath, local]] as const) {
    if (value !== undefined && (typeof value !== "object" || value === null || Array.isArray(value))) {
      throw new ConfigError(`${file}: expected a JSON object`);
    }
  }
  const merged = mergeConfigs(
    (shared ?? {}) as Partial<ProjectConfig>,
    (local ?? {}) as Partial<ProjectConfig>
  );
  const errors = validateConfig(merged);
  if (errors.length) {
    throw new ConfigError(`Invalid Gmail MCP config in ${projectDir}:\n- ${errors.join("\n- ")}`);
  }
  return {
    projectDir,
    config: merged as ProjectConfig,
    files: [sharedPath, localPath].filter((f) => fs.existsSync(f)),
  };
}

export function validateConfig(c: Partial<ProjectConfig>): string[] {
  const errors: string[] = [];
  const clients = c.clients ?? {};
  if (Object.keys(clients).length === 0) {
    errors.push("'clients' must name at least one OAuth client");
  }
  for (const [name, src] of Object.entries(clients)) {
    if (!src || typeof src !== "object") {
      errors.push(`clients.${name}: expected an object`);
      continue;
    }
    const kinds = (["file", "envFile", "store"] as const).filter((k) => typeof src[k] === "string" && src[k]);
    if (kinds.length !== 1) {
      errors.push(`clients.${name}: set exactly one of 'file', 'envFile' or 'store'`);
    }
    if ((src.clientIdKey || src.clientSecretKey) && !src.envFile) {
      errors.push(`clients.${name}: 'clientIdKey'/'clientSecretKey' only apply to 'envFile'`);
    }
  }
  const accounts = c.accounts ?? [];
  if (!Array.isArray(accounts)) {
    errors.push("accounts: expected an array of rules");
  }
  for (const [i, rule] of (Array.isArray(accounts) ? accounts : []).entries()) {
    if (!rule || typeof rule.match !== "string" || !rule.match) {
      errors.push(`accounts[${i}]: 'match' (email or glob) is required`);
    } else if (rule.client !== undefined && !(rule.client in clients)) {
      errors.push(`accounts[${i}]: unknown client '${rule.client}'`);
    }
  }
  const roots = c.files?.roots ?? [];
  if (!Array.isArray(roots) || roots.some((r) => typeof r !== "string")) {
    errors.push("files.roots: expected an array of paths");
  }
  if (c.labels !== undefined) {
    errors.push(...validateLabelRules(c.labels).map((e) => `labels.${e}`));
  }
  return errors;
}

// "*@example.com" style match, case-insensitive. * is the only wildcard.
export function matchesGlob(email: string, pattern: string): boolean {
  const re = new RegExp(
    "^" + pattern.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$",
    "i"
  );
  return re.test(email);
}

// Whether an account authorised under `clientName` may be used in this project.
// No rules at all means every account of every configured client.
export function accountAllowed(config: ProjectConfig, email: string, clientName: string): boolean {
  const rules = config.accounts;
  if (!rules || rules.length === 0) return true;
  return rules.some((r) => (!r.client || r.client === clientName) && matchesGlob(email, r.match));
}
