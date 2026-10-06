// Signing a mailbox in: the installed-app OAuth flow on a loopback port, with PKCE.
//
// A Desktop-app client accepts any http://127.0.0.1:<port> redirect, so the port is
// random and nothing has to stay running. A Web-application client only accepts the
// redirect URIs registered for it, so its first loopback URI is used as is.

import { gmail as gmailApi } from "@googleapis/gmail";
import { spawn } from "child_process";
import { randomBytes } from "crypto";
import * as http from "http";
import type { AddressInfo } from "net";
import { oauthClient, SCOPES } from "./accounts.js";
import type { ResolvedClient } from "./clients.js";
import type { StoredToken } from "./store.js";

const TIMEOUT_MS = 5 * 60 * 1000;

export interface AuthOptions {
  loginHint?: string;
  port?: number;
  openBrowser?: boolean;
  log?: (line: string) => void;
}

function loopbackRedirect(client: ResolvedClient, port?: number): { host: string; port: number; path: string } {
  if (client.type === "web") {
    const registered = client.redirectUris
      .map((u) => new URL(u))
      .find((u) => u.protocol === "http:" && ["localhost", "127.0.0.1"].includes(u.hostname) && u.port);
    if (!registered) {
      throw new Error(
        `Client '${client.name}' is a Web application without a loopback redirect URI. ` +
          "Create a 'Desktop app' OAuth client instead (it needs no redirect URI), or register http://127.0.0.1:<port>/ on this one."
      );
    }
    return { host: registered.hostname, port: Number(registered.port), path: registered.pathname };
  }
  return { host: "127.0.0.1", port: port ?? 0, path: "/" };
}

export function openInBrowser(url: string): void {
  const [cmd, args] =
    process.platform === "darwin"
      ? ["open", [url]]
      : process.platform === "win32"
        ? ["cmd", ["/c", "start", '""', url]]
        : ["xdg-open", [url]];
  try {
    spawn(cmd, args, { stdio: "ignore", detached: true }).on("error", () => {}).unref();
  } catch {
    // no browser here - the URL is printed anyway
  }
}

const page = (title: string, body: string) =>
  `<!doctype html><meta charset="utf-8"><title>${title}</title>` +
  `<body style="font-family:system-ui;max-width:32rem;margin:4rem auto"><h1>${title}</h1><p>${body}</p></body>`;

export async function signIn(client: ResolvedClient, opts: AuthOptions = {}): Promise<StoredToken> {
  const log = opts.log ?? ((l: string) => console.error(l));
  const target = loopbackRedirect(client, opts.port);
  const state = randomBytes(16).toString("hex");

  const server = http.createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(target.port, target.host === "localhost" ? "127.0.0.1" : target.host, () => resolve());
  });
  const port = (server.address() as AddressInfo).port;
  const redirectUri = `http://${target.host}:${port}${target.path}`;
  const auth = oauthClient(client, redirectUri);
  const { codeVerifier, codeChallenge } = await auth.generateCodeVerifierAsync();
  const url = auth.generateAuthUrl({
    access_type: "offline",
    prompt: "consent", // always returns a refresh token, also on a repeated sign-in
    scope: SCOPES,
    state,
    login_hint: opts.loginHint,
    code_challenge: codeChallenge,
    code_challenge_method: "S256" as any,
  });

  log(`Sign in with Google in the browser. If it did not open, visit:\n${url}`);
  if (opts.openBrowser !== false) openInBrowser(url);

  try {
    const code = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Timed out after 5 minutes waiting for the Google sign-in")), TIMEOUT_MS);
      server.on("request", (req, res) => {
        const u = new URL(req.url || "/", redirectUri);
        if (u.pathname !== target.path) {
          res.writeHead(404).end();
          return;
        }
        const error = u.searchParams.get("error");
        const got = u.searchParams.get("code");
        if (u.searchParams.get("state") !== state || (!got && !error)) {
          res.writeHead(400, { "content-type": "text/html" }).end(page("Unexpected request", "This is not the sign-in that is waiting."));
          return;
        }
        clearTimeout(timer);
        if (error) {
          res.writeHead(200, { "content-type": "text/html" }).end(page("Sign-in cancelled", `Google answered: ${error}. You can close this tab.`));
          reject(new Error(`Google sign-in failed: ${error}`));
          return;
        }
        res.writeHead(200, { "content-type": "text/html" }).end(page("Signed in", "Gmail access is granted. You can close this tab and go back to Claude."));
        resolve(got!);
      });
    });

    const { tokens } = await auth.getToken({ code, codeVerifier, redirect_uri: redirectUri });
    if (!tokens.refresh_token) {
      throw new Error("Google returned no refresh token - remove the app's access at myaccount.google.com/permissions and sign in again");
    }
    auth.setCredentials(tokens);
    const granted = (tokens.scope ?? "").split(" ");
    const missing = SCOPES.filter((s) => !granted.includes(s));
    if (missing.length) {
      throw new Error(`Not all permissions were granted (missing: ${missing.join(", ")}). Sign in again and tick every checkbox on the consent screen.`);
    }
    const profile = await gmailApi({ version: "v1", auth }).users.getProfile({ userId: "me" });
    const email = profile.data.emailAddress;
    if (!email) throw new Error("Signed in, but Gmail returned no address for the account");
    return { email, clientId: client.clientId, scopes: granted, token: tokens, createdAt: new Date().toISOString() };
  } finally {
    server.close();
  }
}
