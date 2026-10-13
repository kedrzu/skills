import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { ConfigError, loadProjectConfig, parseEnvFile, readCredentials, type CredentialsSource } from "./config.js";

let tmp: string;

function project(name: string, config?: unknown): string {
  const dir = path.join(tmp, name);
  fs.mkdirSync(path.join(dir, ".claude"), { recursive: true });
  if (config !== undefined) {
    const text = typeof config === "string" ? config : JSON.stringify(config);
    fs.writeFileSync(path.join(dir, ".claude", "playwright.json"), text);
  }
  return dir;
}

function loadError(dir: string): string {
  try {
    loadProjectConfig(dir, {});
  } catch (e) {
    expect(e).toBeInstanceOf(ConfigError);
    return e instanceof Error ? e.message : String(e);
  }
  throw new Error("expected loadProjectConfig to throw");
}

beforeAll(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "playwright-config-")));
});

afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe("project config", () => {
  it("defaults to the persistent profile without geo when the project has no file", () => {
    expect(loadProjectConfig(project("none"), {})).toEqual({ profile: "persistent" });
  });

  it("reads the profile and resolves the credentials file against the project, home or the secrets store", () => {
    const geo = (file?: string) => ({ provider: "private internet access", credentials: { file, userKey: "PIA_USER", passwordKey: "PIA_PASS" } });
    const relative = project("relative", { profile: "fresh", geo: geo("secrets/vpn.env") });
    expect(loadProjectConfig(relative, {})).toEqual({
      profile: "fresh",
      geo: { provider: "private internet access", credentials: { file: path.join(relative, "secrets", "vpn.env"), userKey: "PIA_USER", passwordKey: "PIA_PASS" } },
    });
    expect(loadProjectConfig(project("home", { geo: geo("~/vpn.env") }), {}).geo?.credentials.file).toBe(path.join(os.homedir(), "vpn.env"));
    const store = project("store", { geo: geo() });
    expect(loadProjectConfig(store, {}).geo?.credentials.file).toBe(path.join(os.homedir(), ".claude", "secrets", ".env"));
    expect(loadProjectConfig(store, { CLAUDE_CONFIG_DIR: "~/alt-claude" }).geo?.credentials.file).toBe(
      path.join(os.homedir(), "alt-claude", "secrets", ".env")
    );
  });

  it("rejects invalid JSON and a non-object", () => {
    expect(loadError(project("broken", "{ profile: fresh"))).toMatch(/invalid JSON/);
    expect(loadError(project("array", []))).toMatch(/expected a JSON object/);
  });

  it("rejects unknown fields and wrong types with every problem listed instead of falling back to defaults", () => {
    const message = loadError(
      project("invalid", {
        profile: "isolated",
        browser: "firefox",
        geo: { provider: 42, region: "US", credentials: { file: "", userKey: "U", passwordKey: ["P"], extra: true } },
      })
    );
    for (const problem of [
      "profile: expected one of",
      "browser: unknown field",
      "geo.provider: expected a non-empty string",
      "geo.region: unknown field",
      "geo.credentials.extra: unknown field",
      "geo.credentials.passwordKey: expected a non-empty string",
      "geo.credentials.file: expected a non-empty path",
    ]) {
      expect(message).toContain(problem);
    }
  });

  it("requires credentials keys when geo is configured", () => {
    expect(loadError(project("no-credentials", { geo: { provider: "pia" } }))).toContain("geo.credentials: expected an object");
  });
});

describe("credentials", () => {
  const USER = "p1234567";
  const PASSWORD = "s3cr3t-Value#with'quotes";

  function source(file: string): CredentialsSource {
    return { file, userKey: "PIA_USER", passwordKey: "PIA_PASS" };
  }

  it("reads KEY=value lines the way the secrets plugin stores them", () => {
    expect(parseEnvFile(`# comment\nexport A=1\nB="two words"\nC='x'\nD=a=b\nnot a line\n`)).toEqual({ A: "1", B: "two words", C: "x", D: "a=b" });
  });

  it("takes each key from the environment first and from the file otherwise", () => {
    const file = path.join(tmp, "creds.env");
    fs.writeFileSync(file, `PIA_USER=file-user\nPIA_PASS=${PASSWORD}\n`);
    expect(readCredentials(source(file), {})).toEqual({ username: "file-user", password: PASSWORD });
    expect(readCredentials(source(file), { PIA_USER: USER, PIA_PASS: "" })).toEqual({ username: USER, password: PASSWORD });
    // Both keys in the environment: the file is not needed at all.
    expect(readCredentials(source(path.join(tmp, "absent.env")), { PIA_USER: USER, PIA_PASS: PASSWORD })).toEqual({
      username: USER,
      password: PASSWORD,
    });
  });

  it("names the missing key and file without revealing a value it did find", () => {
    const file = path.join(tmp, "partial.env");
    fs.writeFileSync(file, `PIA_PASS=${PASSWORD}\n`);
    const errors = [
      () => readCredentials(source(file), {}),
      () => readCredentials(source(path.join(tmp, "missing.env")), { PIA_PASS: PASSWORD }),
    ].map((read) => {
      try {
        read();
      } catch (e) {
        expect(e).toBeInstanceOf(ConfigError);
        return e instanceof Error ? e.message : String(e);
      }
      throw new Error("expected readCredentials to throw");
    });
    expect(errors[0]).toContain("PIA_USER");
    expect(errors[0]).toContain(file);
    expect(errors[1]).toContain("does not exist");
    for (const message of errors) {
      expect(message).not.toContain(PASSWORD);
      expect(message).not.toContain("PIA_PASS");
    }
  });
});
