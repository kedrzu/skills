// OAuth clients (Google Cloud apps): where their id and secret come from.
//
// A client is read lazily, every time accounts are loaded, so a file decrypted after
// the server started (sops, a password manager export) is picked up without a restart.
// Nothing here ever prints a secret.

import * as fs from "fs";
import * as path from "path";
import { resolvePath, storeDir, type ClientSource } from "./config.js";

export const DEFAULT_ID_KEY = "GOOGLE_CLIENT_ID";
export const DEFAULT_SECRET_KEY = "GOOGLE_CLIENT_SECRET";

export interface ResolvedClient {
  name: string;
  clientId: string;
  clientSecret: string;
  type: "installed" | "web"; // Desktop app or Web application in the console
  redirectUris: string[];
  sourceFile: string; // never attachable to a draft
}

// KEY=value lines; `export`, quotes, blank lines and # comments are understood.
export function parseDotenv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let value = m[2];
    const quote = value[0];
    if ((quote === '"' || quote === "'") && value.lastIndexOf(quote) > 0) {
      value = value.slice(1, value.lastIndexOf(quote));
      if (quote === '"') value = value.replace(/\\n/g, "\n").replace(/\\"/g, '"');
    } else {
      value = value.replace(/\s+#.*$/, "").trim();
    }
    out[m[1]] = value;
  }
  return out;
}

// The JSON the Google Cloud console offers for download: {"installed": {...}} or {"web": {...}}.
export function parseClientJson(text: string, file: string) {
  let json: any;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(`${file} is not valid JSON - expected the OAuth client file downloaded from the Google Cloud console`);
  }
  const type = json?.installed ? "installed" : json?.web ? "web" : null;
  const body = type ? json[type] : null;
  if (!type || !body?.client_id || !body?.client_secret) {
    throw new Error(`${file} is not an OAuth client file (expected an "installed" or "web" object with client_id and client_secret)`);
  }
  return {
    type: type as "installed" | "web",
    clientId: String(body.client_id),
    clientSecret: String(body.client_secret),
    redirectUris: (body.redirect_uris ?? []).map(String) as string[],
  };
}

function readSource(file: string, what: string): string {
  try {
    return fs.readFileSync(file, "utf-8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`${what} ${file} does not exist${what === "env file" ? " - decrypt or create it first" : ""}`);
    }
    throw e;
  }
}

export function storedClientPath(name: string, env = process.env): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name)) {
    throw new Error(`Invalid client name '${name}' (letters, digits, . _ - only)`);
  }
  return path.join(storeDir(env), "clients", `${name}.json`);
}

// The file a source reads from - known without reading it, so it can be denied to drafts.
export function clientSourceFile(projectDir: string, src: ClientSource): string {
  if (src.file) return resolvePath(projectDir, src.file);
  if (src.envFile) return resolvePath(projectDir, src.envFile);
  return storedClientPath(src.store!);
}

export function resolveClient(projectDir: string, name: string, src: ClientSource): ResolvedClient {
  const sourceFile = clientSourceFile(projectDir, src);
  if (src.envFile) {
    const vars = parseDotenv(readSource(sourceFile, "env file"));
    const idKey = src.clientIdKey ?? DEFAULT_ID_KEY;
    const secretKey = src.clientSecretKey ?? DEFAULT_SECRET_KEY;
    const missing = [idKey, secretKey].filter((k) => !vars[k]);
    if (missing.length) {
      throw new Error(`env file ${sourceFile} has no ${missing.join(" / ")} (set clientIdKey/clientSecretKey if the keys are named differently)`);
    }
    return { name, clientId: vars[idKey], clientSecret: vars[secretKey], type: "installed", redirectUris: [], sourceFile };
  }
  const what = src.store ? `stored client '${src.store}' (import it with \`client import\`):` : "client file";
  const parsed = parseClientJson(readSource(sourceFile, what), sourceFile);
  return { name, ...parsed, sourceFile };
}

// Copy a downloaded client file into the store, readable only by this user.
export function importClient(name: string, from: string, env = process.env): string {
  const text = readSource(path.resolve(from), "client file");
  parseClientJson(text, from);
  const dest = storedClientPath(name, env);
  fs.mkdirSync(path.dirname(dest), { recursive: true, mode: 0o700 });
  fs.chmodSync(path.dirname(path.dirname(dest)), 0o700);
  fs.writeFileSync(dest, text, { mode: 0o600 });
  fs.chmodSync(dest, 0o600);
  return dest;
}
