import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { AccountRegistry } from "./accounts.js";
import { importClient, parseClientJson, parseDotenv, resolveClient } from "./clients.js";
import { accountAllowed, ConfigError, loadConfig, matchesGlob, mergeConfigs, projectDirFrom, storeDir } from "./config.js";
import { TokenStore } from "./store.js";

let tmp: string;
const clientJson = (id: string, type = "installed") =>
  JSON.stringify({ [type]: { client_id: id, client_secret: `GOCSPX-${id}`, redirect_uris: ["http://localhost:4002/oauth2callback"] } });

function project(name: string, shared?: object, local?: object): string {
  const dir = path.join(tmp, name);
  fs.mkdirSync(path.join(dir, ".claude"), { recursive: true });
  if (shared) fs.writeFileSync(path.join(dir, ".claude", "gdrive-mcp.json"), JSON.stringify(shared));
  if (local) fs.writeFileSync(path.join(dir, ".claude", "gdrive-mcp.local.json"), JSON.stringify(local));
  return dir;
}

beforeAll(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gdrive-config-")));
});

afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe("dotenv and client files", () => {
  it("parses export, quotes and comments", () => {
    expect(
      parseDotenv(`# comment\nexport A=1\nB="two words" \nC='x#y'\nD=plain # trailing\n\nbad line\nE=`)
    ).toEqual({ A: "1", B: "two words", C: "x#y", D: "plain", E: "" });
  });

  it("reads installed and web client JSON and rejects anything else", () => {
    expect(parseClientJson(clientJson("a"), "f").type).toBe("installed");
    expect(parseClientJson(clientJson("b", "web"), "f")).toMatchObject({ type: "web", clientId: "b" });
    expect(() => parseClientJson("{}", "f")).toThrow(/not an OAuth client file/);
    expect(() => parseClientJson("nope", "f")).toThrow(/not valid JSON/);
  });

  it("resolves a client from an env file with default and custom keys", () => {
    const dir = project("envfile");
    fs.writeFileSync(path.join(dir, "secrets.env"), "GOOGLE_CLIENT_ID=id1\nGOOGLE_CLIENT_SECRET=s1\nMY_ID=id2\nMY_SECRET=s2\n");
    expect(resolveClient(dir, "a", { envFile: "secrets.env" })).toMatchObject({ clientId: "id1", clientSecret: "s1" });
    expect(resolveClient(dir, "b", { envFile: "secrets.env", clientIdKey: "MY_ID", clientSecretKey: "MY_SECRET" }).clientId).toBe("id2");
    expect(() => resolveClient(dir, "c", { envFile: "secrets.env", clientIdKey: "NOPE" })).toThrow(/has no NOPE/);
    expect(() => resolveClient(dir, "d", { envFile: "missing.env" })).toThrow(/decrypt or create it first/);
  });

  it("imports a client into the store with private permissions", () => {
    const env = { GDRIVE_MCP_HOME: path.join(tmp, "store-import") };
    const src = path.join(tmp, "downloaded.json");
    fs.writeFileSync(src, clientJson("imp"));
    const dest = importClient("personal", src, env);
    expect(dest).toBe(path.join(env.GDRIVE_MCP_HOME, "clients", "personal.json"));
    expect(fs.statSync(dest).mode & 0o777).toBe(0o600);
    expect(() => importClient("../evil", src, env)).toThrow(/Invalid client name/);
  });
});

describe("project config", () => {
  it("is null when the project has none", () => {
    expect(loadConfig(project("empty"))).toBeNull();
  });

  it("merges the local file over the shared one", () => {
    const merged = mergeConfigs(
      {
        clients: { a: { file: "a.json" } },
        accounts: [{ match: "*@x.com" }],
        files: { roots: ["r1"], downloadsDir: "dl" },
        permissions: { upload: true, edit: true },
      },
      { clients: { b: { store: "b" } }, accounts: [{ match: "me@y.com" }], files: { roots: ["r2"] }, permissions: { edit: false } }
    );
    expect(Object.keys(merged.clients!)).toEqual(["a", "b"]);
    expect(merged.accounts!.map((a) => a.match)).toEqual(["*@x.com", "me@y.com"]);
    expect(merged.files).toEqual({ roots: ["r1", "r2"], downloadsDir: "dl" });
    expect(merged.permissions).toEqual({ upload: true, edit: false });
    expect(mergeConfigs({ clients: {} }, {}).permissions).toBeUndefined();
  });

  it("rejects an invalid config with every problem listed", () => {
    const dir = project("invalid", { clients: { a: { file: "x", store: "y" } }, accounts: [{ match: "a@b", client: "zzz" }], permissions: { delete: "yes", purge: true } });
    try {
      loadConfig(dir);
      throw new Error("expected a ConfigError");
    } catch (e) {
      expect(e).toBeInstanceOf(ConfigError);
      expect((e as Error).message).toMatch(/exactly one of/);
      expect((e as Error).message).toMatch(/unknown client 'zzz'/);
      expect((e as Error).message).toMatch(/permissions\.delete: expected true or false/);
      expect((e as Error).message).toMatch(/permissions\.purge: unknown permission/);
    }
  });

  it("rejects a list written as a string instead of spreading it", () => {
    // Spread, "~/Notes" became ["~", "/", ...] and "/" allowed every path on disk.
    const dir = project("string-roots", { clients: { a: { file: "a.json" } }, accounts: { match: "*@x.com" } }, { files: { roots: "~/Notes" } });
    try {
      loadConfig(dir);
      throw new Error("expected a ConfigError");
    } catch (e) {
      expect(e).toBeInstanceOf(ConfigError);
      expect((e as Error).message).toMatch(/files\.roots: expected an array of paths/);
      expect((e as Error).message).toMatch(/accounts: expected an array of rules/);
    }
  });

  it("matches account globs", () => {
    expect(matchesGlob("Ann@Sigma.Clinic", "*@sigma.clinic")).toBe(true);
    expect(matchesGlob("ann@sigma.clinic.evil.com", "*@sigma.clinic")).toBe(false);
    expect(matchesGlob("a+b@x.com", "a+b@x.com")).toBe(true);
    const config = { clients: { work: { file: "w" }, home: { file: "h" } }, accounts: [{ match: "*@work.com", client: "work" }] };
    expect(accountAllowed(config, "me@work.com", "work")).toBe(true);
    expect(accountAllowed(config, "me@work.com", "home")).toBe(false);
    expect(accountAllowed({ clients: {} }, "anyone@x.com", "home")).toBe(true);
  });

  it("falls back to the working directory for an unexpanded project path", () => {
    expect(projectDirFrom("${CLAUDE_PROJECT_DIR}")).toBe(process.cwd());
    expect(projectDirFrom(undefined)).toBe(process.cwd());
    expect(projectDirFrom("/tmp/x")).toBe("/tmp/x");
  });

  it("puts the store under the Claude config dir unless overridden", () => {
    expect(storeDir({ CLAUDE_CONFIG_DIR: "/c" })).toBe("/c/gdrive-mcp");
    expect(storeDir({ GDRIVE_MCP_HOME: "/g", CLAUDE_CONFIG_DIR: "/c" })).toBe("/g");
  });
});

describe("account registry", () => {
  it("shows only accounts of configured clients that match the rules", () => {
    const store = new TokenStore(path.join(tmp, "store-registry"));
    const token = (email: string, clientId: string) => ({
      email,
      clientId,
      scopes: [],
      token: { refresh_token: `r-${email}` },
      createdAt: "2026-01-01",
    });
    store.write(token("me@gmail.com", "personal-id"));
    store.write(token("me@work.com", "work-id"));
    store.write(token("boss@work.com", "work-id"));
    store.write(token("me@work.com", "other-id"));

    const work = project("work", {
      clients: { work: { file: "client.json" } },
      accounts: [{ match: "me@work.com" }],
    });
    fs.writeFileSync(path.join(work, "client.json"), clientJson("work-id"));
    const registry = new AccountRegistry(work, store);
    registry.reload();
    expect([...registry.accounts.keys()]).toEqual(["me@work.com"]);
    expect(registry.hidden).toEqual([{ email: "boss@work.com", client: "work" }]);
    expect(() => registry.get("me@gmail.com")).toThrow(/Account not found/);
    expect(() => registry.get("boss@work.com")).toThrow(/not allowed in this project/);
    expect(registry.deniedFiles()).toContain(path.join(work, "client.json"));

    // A personal project with its own client sees neither work account.
    const home = project("home", { clients: { personal: { file: "c.json" } } });
    fs.writeFileSync(path.join(home, "c.json"), clientJson("personal-id"));
    const homeRegistry = new AccountRegistry(home, store);
    homeRegistry.reload();
    expect([...homeRegistry.accounts.keys()]).toEqual(["me@gmail.com"]);
  });

  it("reports an unreadable client without failing the others", () => {
    const dir = project("broken", { clients: { gone: { envFile: "nope.env" }, ok: { file: "c.json" } } });
    fs.writeFileSync(path.join(dir, "c.json"), clientJson("ok-id"));
    const registry = new AccountRegistry(dir, new TokenStore(path.join(tmp, "store-broken")));
    registry.reload();
    expect(registry.clients.has("ok")).toBe(true);
    expect(registry.problems).toEqual([{ client: "gone", message: expect.stringMatching(/decrypt or create it first/) }]);
  });

  it("explains a missing config instead of throwing on load", () => {
    const registry = new AccountRegistry(project("unconfigured"));
    registry.reload();
    expect(registry.loaded).toBeNull();
    expect(() => registry.get("x@y.com")).toThrow(/gdrive-mcp:setup/);
  });
});

describe("token store", () => {
  it("writes privately and keeps the refresh token on update", () => {
    const store = new TokenStore(path.join(tmp, "store-tokens"));
    store.write({ email: "A@x.com", clientId: "cid", scopes: [], token: { refresh_token: "r1", access_token: "a1" }, createdAt: "t" });
    store.update("cid", "a@x.com", { access_token: "a2", expiry_date: 5 });
    const t = store.read("cid", "a@x.com")!;
    expect(t.token).toEqual({ refresh_token: "r1", access_token: "a2", expiry_date: 5 });
    expect(fs.statSync(store.file("cid", "a@x.com")).mode & 0o777).toBe(0o600);
    expect(fs.statSync(path.dirname(store.file("cid", "a@x.com"))).mode & 0o777).toBe(0o700);
    expect(() => store.file("../x", "a@x.com")).toThrow(/Unsafe/);
    expect(store.remove("cid", "a@x.com")).toBe(true);
    expect(store.list("cid")).toEqual([]);
  });
});
