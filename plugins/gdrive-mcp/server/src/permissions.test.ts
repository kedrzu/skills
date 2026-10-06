import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { AccountRegistry } from "./accounts.js";
import {
  assertAllowed,
  DEFAULT_PERMISSIONS,
  effectivePermissions,
  PermissionDenied,
  PERMISSIONS,
  TOOL_PERMISSION,
  validatePermissions,
} from "./permissions.js";
import { TokenStore } from "./store.js";
import { DriveTools, toolDefinitions } from "./tools.js";

let tmp: string;

beforeAll(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gdrive-permissions-")));
});

afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

function project(name: string, permissions?: object): string {
  const dir = path.join(tmp, name);
  fs.mkdirSync(path.join(dir, ".claude"), { recursive: true });
  fs.writeFileSync(path.join(dir, "client.json"), JSON.stringify({ installed: { client_id: "cid", client_secret: "s" } }));
  fs.writeFileSync(path.join(dir, ".claude", "gdrive-mcp.json"), JSON.stringify({ clients: { main: { file: "client.json" } }, permissions }));
  return dir;
}

const names = (perms: Parameters<typeof toolDefinitions>[0]) => toolDefinitions(perms).map((t) => t.name);

describe("permissions", () => {
  it("reads by default and writes only when switched on", () => {
    expect(effectivePermissions()).toEqual(DEFAULT_PERMISSIONS);
    expect(effectivePermissions({ upload: true, browse: false })).toEqual({
      browse: false,
      download: true,
      upload: true,
      edit: false,
      delete: false,
    });
  });

  it("rejects unknown keys and non-boolean values", () => {
    expect(validatePermissions({ upload: true })).toEqual([]);
    expect(validatePermissions({ upload: "yes", purge: true })).toEqual([
      "upload: expected true or false",
      expect.stringMatching(/^purge: unknown permission/),
    ]);
    expect(validatePermissions([])).toHaveLength(1);
  });

  it("maps every defined tool to a permission", () => {
    const all = Object.fromEntries(PERMISSIONS.map((p) => [p, true])) as Record<(typeof PERMISSIONS)[number], boolean>;
    expect(names(all).sort()).toEqual(Object.keys(TOOL_PERMISSION).sort());
  });

  it("lists only the tools the project allows", () => {
    expect(names(DEFAULT_PERMISSIONS)).toEqual([
      "list_accounts",
      "search_files",
      "list_folder",
      "get_file_info",
      "list_shared_drives",
      "read_file",
      "download_file",
    ]);
    const writeOnly = { browse: false, download: false, upload: true, edit: false, delete: true };
    expect(names(writeOnly)).toEqual(["list_accounts", "upload_file", "create_folder", "trash_file", "restore_file"]);
  });

  it("names the switch and the config file when a tool is refused", () => {
    expect(() => assertAllowed("list_accounts", { ...DEFAULT_PERMISSIONS, browse: false }, "cfg")).not.toThrow();
    expect(() => assertAllowed("no_such_tool", DEFAULT_PERMISSIONS, "cfg")).not.toThrow();
    try {
      assertAllowed("trash_file", DEFAULT_PERMISSIONS, ".claude/gdrive-mcp.json");
      throw new Error("expected PermissionDenied");
    } catch (e) {
      expect(e).toBeInstanceOf(PermissionDenied);
      expect((e as Error).message).toMatch(/'delete' permission/);
      expect((e as Error).message).toMatch(/"delete": true \} in \.claude\/gdrive-mcp\.json/);
    }
  });
});

describe("DriveTools gate", () => {
  const store = () => new TokenStore(path.join(tmp, "store"));

  it("refuses a disabled tool before touching any account", async () => {
    const registry = new AccountRegistry(project("readonly"), store());
    registry.reload();
    const result = await new DriveTools(registry).call("upload_file", { account: "me@x.com", content: "x", name: "a.txt" });
    expect("isError" in result && result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/needs the 'upload' permission/);
    expect(result.content[0].text).not.toMatch(/sign in again/);
  });

  it("lets an enabled tool through to the account lookup", async () => {
    const registry = new AccountRegistry(project("writable", { upload: true }), store());
    registry.reload();
    const result = await new DriveTools(registry).call("upload_file", { account: "me@x.com", content: "x", name: "a.txt" });
    expect(result.content[0].text).toMatch(/Account not found: me@x.com/);
  });

  it("picks up a permission change without a restart", async () => {
    const dir = project("live");
    const registry = new AccountRegistry(dir, store());
    registry.reload();
    const tools = new DriveTools(registry);
    expect(tools.permissions.delete).toBe(false);
    const file = path.join(dir, ".claude", "gdrive-mcp.local.json");
    fs.writeFileSync(file, JSON.stringify({ permissions: { delete: true } }));
    const result = await tools.call("trash_file", { account: "me@x.com", fileId: "abc" });
    expect(result.content[0].text).toMatch(/Account not found/);
    expect(tools.permissions.delete).toBe(true);
  });
});
