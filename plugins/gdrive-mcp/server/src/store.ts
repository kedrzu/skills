// Refresh tokens, one file per (OAuth client, Google account), outside every repository.
//
//   <store>/tokens/<client_id>/<email>.json   mode 0600, directories 0700
//
// Keyed by client_id rather than by the project's name for the client: the same account
// can be authorised in two Google Cloud apps independently, client names in different
// projects never collide, and projects sharing a client share its tokens. Several server
// processes (one per Claude session) write here, so every write is atomic.

import * as fs from "fs";
import * as path from "path";
import { storeDir } from "./config.js";

export interface StoredToken {
  email: string;
  clientId: string;
  scopes: string[];
  token: {
    refresh_token?: string | null;
    access_token?: string | null;
    expiry_date?: number | null;
    token_type?: string | null;
    scope?: string;
    id_token?: string | null;
  };
  createdAt: string;
}

function safeSegment(s: string): string {
  if (!s || s === "." || s === ".." || /[\/\\\0]/.test(s)) throw new Error(`Unsafe store path segment: ${s}`);
  return s;
}

export class TokenStore {
  constructor(readonly root = storeDir()) {}

  private dir(clientId: string): string {
    return path.join(this.root, "tokens", safeSegment(clientId));
  }

  file(clientId: string, email: string): string {
    return path.join(this.dir(clientId), `${safeSegment(email.toLowerCase())}.json`);
  }

  list(clientId: string): StoredToken[] {
    let names: string[];
    try {
      names = fs.readdirSync(this.dir(clientId));
    } catch {
      return [];
    }
    const out: StoredToken[] = [];
    for (const name of names) {
      if (!name.endsWith(".json")) continue;
      try {
        const t = JSON.parse(fs.readFileSync(path.join(this.dir(clientId), name), "utf-8")) as StoredToken;
        if (t.email && t.token) out.push(t);
      } catch {
        // half-written or foreign file: skip it, a later scan picks it up
      }
    }
    return out.sort((a, b) => a.email.localeCompare(b.email));
  }

  read(clientId: string, email: string): StoredToken | null {
    try {
      return JSON.parse(fs.readFileSync(this.file(clientId, email), "utf-8"));
    } catch {
      return null;
    }
  }

  write(t: StoredToken): void {
    const file = this.file(t.clientId, t.email);
    for (const d of [this.root, path.join(this.root, "tokens"), path.dirname(file)]) {
      fs.mkdirSync(d, { recursive: true, mode: 0o700 });
    }
    const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(t, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, file);
  }

  // Merge refreshed credentials into the stored token. Google sends a new refresh token
  // only now and then, so an update without one keeps the old.
  update(clientId: string, email: string, fresh: StoredToken["token"]): void {
    const current = this.read(clientId, email);
    if (!current) return;
    const token = { ...current.token, ...fresh };
    if (!fresh.refresh_token) token.refresh_token = current.token.refresh_token;
    this.write({ ...current, token });
  }

  remove(clientId: string, email: string): boolean {
    try {
      fs.unlinkSync(this.file(clientId, email));
      return true;
    } catch {
      return false;
    }
  }
}
