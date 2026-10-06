import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { AccountRegistry } from "./accounts.js";
import { CONFIG_FILE } from "./config.js";
import { TokenStore } from "./store.js";

let tmp: string;

beforeAll(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gmail-accounts-")));
});

afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

function registry(name: string): { registry: AccountRegistry; store: TokenStore } {
  const dir = path.join(tmp, name);
  fs.mkdirSync(path.join(dir, ".claude"), { recursive: true });
  fs.writeFileSync(path.join(dir, CONFIG_FILE), JSON.stringify({ clients: { c: { file: "client.json" } } }));
  fs.writeFileSync(path.join(dir, "client.json"), JSON.stringify({ installed: { client_id: "cid", client_secret: "GOCSPX-cid" } }));
  const store = new TokenStore(path.join(tmp, `store-${name}`));
  store.write({ email: "me@x.com", clientId: "cid", scopes: [], token: { refresh_token: "r1" }, createdAt: "t" });
  const r = new AccountRegistry(dir, store);
  r.reload();
  return { registry: r, store };
}

describe("signing an account in again", () => {
  it("takes effect in a running server without a restart", () => {
    const { registry: r } = registry("reauth");
    const live = r.get("me@x.com");
    expect(live.auth.credentials.refresh_token).toBe("r1");

    // `auth` in another process rewrites the token file.
    const other = new TokenStore(r.store.root);
    other.write({ email: "me@x.com", clientId: "cid", scopes: [], token: { refresh_token: "r2", access_token: "a2" }, createdAt: "t2" });

    const again = r.get("me@x.com");
    expect(again).toBe(live); // same live client, new credentials
    expect(again.auth.credentials).toMatchObject({ refresh_token: "r2", access_token: "a2" });
  });

  it("keeps the live credentials when the token was only refreshed", () => {
    const { registry: r, store } = registry("refresh");
    const live = r.get("me@x.com");
    live.auth.setCredentials({ refresh_token: "r1", access_token: "live", expiry_date: 9 });
    // A refresh: the client's listener merges the new access token into the store.
    live.auth.emit("tokens", { access_token: "refreshed", expiry_date: 10 });
    expect(store.read("cid", "me@x.com")!.token).toEqual({ refresh_token: "r1", access_token: "refreshed", expiry_date: 10 });

    expect(r.get("me@x.com").auth.credentials).toEqual({ refresh_token: "r1", access_token: "live", expiry_date: 9 });
  });
});
