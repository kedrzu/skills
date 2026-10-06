// The accounts a project may use: tokens in the store whose client is configured in the
// project, narrowed by the project's account rules. Re-read on demand, so an account
// authorised with `auth` while a session runs is usable without a restart.

import { drive as driveApi, type drive_v3 } from "@googleapis/drive";
import * as fs from "fs";
import * as path from "path";
import { OAuth2Client } from "google-auth-library";
import { clientSourceFile, resolveClient, type ResolvedClient } from "./clients.js";
import { accountAllowed, ConfigError, CONFIG_FILE, loadConfig, LOCAL_CONFIG_FILE, type LoadedConfig } from "./config.js";
import { TokenStore, type StoredToken } from "./store.js";

// The full Drive scope: one token serves every project using the account, and projects
// differ in what they allow. What a project may do is enforced by its permissions, not by
// the scope (see permissions.ts).
export const SCOPES = ["https://www.googleapis.com/auth/drive"];

export interface Account {
  email: string;
  client: ResolvedClient;
  auth: OAuth2Client;
  drive: drive_v3.Drive;
}

export interface Problem {
  client?: string;
  email?: string;
  message: string;
}

export class NotConfigured extends Error {}

export function oauthClient(client: ResolvedClient, redirectUri?: string): OAuth2Client {
  return new OAuth2Client({ clientId: client.clientId, clientSecret: client.clientSecret, redirectUri });
}

export class AccountRegistry {
  loaded: LoadedConfig | null = null;
  configError: string | null = null;
  clients = new Map<string, ResolvedClient>();
  accounts = new Map<string, Account>();
  hidden: { email: string; client: string }[] = []; // authorised, but outside the account rules
  problems: Problem[] = [];
  private cache = new Map<string, Account>(); // clientId|email -> live OAuth client
  private configStamp = "";

  constructor(readonly projectDir: string, readonly store = new TokenStore()) {}

  private stamp(): string {
    return [CONFIG_FILE, LOCAL_CONFIG_FILE]
      .map((f) => {
        try {
          return String(fs.statSync(path.join(this.projectDir, f)).mtimeMs);
        } catch {
          return "-";
        }
      })
      .join("|");
  }

  // Cheap check before every tool call: an edited config takes effect without a restart.
  refreshIfChanged(): void {
    if (this.stamp() !== this.configStamp) this.reload();
  }

  reload(): void {
    this.configStamp = this.stamp();
    this.clients.clear();
    this.accounts.clear();
    this.hidden = [];
    this.problems = [];
    try {
      this.loaded = loadConfig(this.projectDir);
      this.configError = null;
    } catch (e) {
      this.loaded = null;
      this.configError = e instanceof ConfigError ? e.message : `Cannot read config: ${(e as Error).message}`;
      return;
    }
    if (!this.loaded) return;

    for (const [name, src] of Object.entries(this.loaded.config.clients)) {
      let client: ResolvedClient;
      try {
        client = resolveClient(this.projectDir, name, src);
      } catch (e) {
        this.problems.push({ client: name, message: (e as Error).message });
        continue;
      }
      this.clients.set(name, client);
      for (const t of this.store.list(client.clientId)) {
        if (!accountAllowed(this.loaded.config, t.email, name)) {
          this.hidden.push({ email: t.email, client: name });
          continue;
        }
        const key = t.email.toLowerCase();
        const existing = this.accounts.get(key);
        if (existing) {
          this.problems.push({
            email: t.email,
            message: `authorised under both '${existing.client.name}' and '${name}' - using '${existing.client.name}'; narrow 'accounts' with a 'client' to choose`,
          });
          continue;
        }
        this.accounts.set(key, this.account(client, t.email, t.token));
      }
    }
  }

  private account(client: ResolvedClient, email: string, token: StoredToken["token"]): Account {
    const key = `${client.clientId}|${email.toLowerCase()}`;
    const cached = this.cache.get(key);
    // Same client and secret: keep the live client, it holds a fresh access token.
    if (cached && cached.client.clientSecret === client.clientSecret) {
      cached.client = client;
      // A refresh token other than the live one means the account was signed in again
      // (`auth`, possibly in another process) and the live one is likely revoked: switch.
      // Refreshes never trigger this - they keep the refresh token, or store the new one.
      if (token.refresh_token && token.refresh_token !== cached.auth.credentials.refresh_token) {
        cached.auth.setCredentials(token);
      }
      return cached;
    }
    const auth = oauthClient(client);
    auth.setCredentials(token);
    auth.on("tokens", (fresh) => this.store.update(client.clientId, email, fresh));
    const account: Account = { email, client, auth, drive: driveApi({ version: "v3", auth }) };
    this.cache.set(key, account);
    return account;
  }

  notConfiguredMessage(): string {
    if (this.configError) return this.configError;
    return (
      `Google Drive MCP is not configured for this project: ${this.projectDir}/${CONFIG_FILE} does not exist. ` +
      "Ask the user to run /gdrive-mcp:setup to choose an OAuth client and sign in."
    );
  }

  // The account to act on; rescans once when it is unknown (it may have just been added).
  get(email: string): Account {
    if (!this.loaded) {
      this.reload();
      if (!this.loaded) throw new NotConfigured(this.notConfiguredMessage());
    }
    if (!email) throw new Error("'account' is required - call list_accounts to see the available ones");
    let account = this.accounts.get(email.toLowerCase());
    if (!account) {
      this.reload();
      account = this.accounts.get(email.toLowerCase());
    }
    if (!account) {
      const hidden = this.hidden.find((h) => h.email.toLowerCase() === email.toLowerCase());
      const available = [...this.accounts.values()].map((a) => a.email);
      throw new Error(
        hidden
          ? `${email} is authorised (client '${hidden.client}') but not allowed in this project - add it to 'accounts' in ${CONFIG_FILE}`
          : `Account not found: ${email}. Available: ${available.join(", ") || "none - ask the user to run /gdrive-mcp:setup to sign in"}`
      );
    }
    // Re-read its token on every use, so signing the account in again takes effect at once.
    const stored = this.store.read(account.client.clientId, account.email);
    return stored?.token ? this.account(account.client, account.email, stored.token) : account;
  }

  // Files never to upload: the token store and every client source.
  deniedFiles(): string[] {
    const files = [this.store.root];
    for (const src of Object.values(this.loaded?.config.clients ?? {})) {
      try {
        files.push(clientSourceFile(this.projectDir, src));
      } catch {
        // an invalid store name is reported by reload()
      }
    }
    return files;
  }
}
