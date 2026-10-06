import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { localFile, mimeTypeOf, resolveLocalFile, resolveWritablePath, safeFileName, type FileAccess } from "./files.js";

let tmp: string;
let repo: string;
let vault: string;
let access: FileAccess;

beforeAll(async () => {
  tmp = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "gdrive-files-")));
  repo = path.join(tmp, "repo");
  vault = path.join(tmp, "Mobile Documents", "vault");
  await fs.mkdir(path.join(repo, ".context", "outbox"), { recursive: true });
  await fs.mkdir(path.join(vault, "Projekty"), { recursive: true });
  await fs.writeFile(path.join(repo, ".context", "outbox", "raport.pdf"), "pdf");
  await fs.writeFile(path.join(repo, ".env"), "SECRET=1");
  await fs.writeFile(path.join(vault, "Projekty", "szafa 1.png"), "png");
  await fs.writeFile(path.join(tmp, "outside.txt"), "nope");
  await fs.symlink(vault, path.join(repo, "obsidian"));
  await fs.symlink(path.join(tmp, "outside.txt"), path.join(repo, "leak.txt"));
  await fs.symlink(tmp, path.join(repo, "escape"));
  access = { baseDir: repo, roots: [repo, vault] };
});

afterAll(async () => {
  await fs.rm(tmp, { recursive: true, force: true });
});

describe("resolveLocalFile", () => {
  it("accepts repo-relative, absolute and vault-via-symlink paths", async () => {
    const pdf = path.join(repo, ".context", "outbox", "raport.pdf");
    expect(await resolveLocalFile(".context/outbox/raport.pdf", access)).toBe(pdf);
    expect(await resolveLocalFile(pdf, access)).toBe(pdf);
    expect(await resolveLocalFile("obsidian/Projekty/szafa 1.png", access)).toBe(path.join(vault, "Projekty", "szafa 1.png"));
  });

  it("refuses anything outside the roots", async () => {
    await expect(resolveLocalFile("../outside.txt", access)).rejects.toThrow(/outside/);
    await expect(resolveLocalFile("leak.txt", access)).rejects.toThrow(/outside/);
    await expect(resolveLocalFile("/etc/hosts", access)).rejects.toThrow(/outside/);
  });

  it("refuses secrets, directories, missing files and ~", async () => {
    await expect(resolveLocalFile(".env", access)).rejects.toThrow(/secrets/);
    await expect(resolveLocalFile("obsidian/Projekty", access)).rejects.toThrow(/regular file/);
    await expect(resolveLocalFile("nope.png", access)).rejects.toThrow(/not found/);
    await expect(resolveLocalFile("~/a.png", access)).rejects.toThrow(/absolute/);
  });

  it("refuses denied files and everything under a denied directory", async () => {
    const guarded = { ...access, denied: [path.join(vault, "Projekty")] };
    await expect(resolveLocalFile("obsidian/Projekty/szafa 1.png", guarded)).rejects.toThrow(/secrets/);
    await expect(resolveLocalFile(".context/outbox/raport.pdf", guarded)).resolves.toBeTruthy();
  });
});

describe("localFile", () => {
  it("describes the file with a type from its extension", async () => {
    const f = await localFile("obsidian/Projekty/szafa 1.png", access);
    expect(f).toMatchObject({ filename: "szafa 1.png", mimeType: "image/png", size: 3 });
  });

  it("knows Markdown and falls back to octet-stream", () => {
    expect(mimeTypeOf("notes.md")).toBe("text/markdown");
    expect(mimeTypeOf("a.csv")).toBe("text/csv");
    expect(mimeTypeOf("blob")).toBe("application/octet-stream");
  });
});

describe("resolveWritablePath", () => {
  it("writes into a directory under the Drive name, creating missing ones", async () => {
    expect(await resolveWritablePath("downloads/2026/", "Umowa.pdf", access)).toBe(path.join(repo, "downloads", "2026", "Umowa.pdf"));
    expect(await resolveWritablePath("obsidian/Projekty", "a/b.docx", access)).toBe(path.join(vault, "Projekty", "a_b.docx"));
    expect(await resolveWritablePath("out/x.txt", "ignored", access)).toBe(path.join(repo, "out", "x.txt"));
  });

  it("does not replace a file unless asked", async () => {
    await expect(resolveWritablePath(".context/outbox/raport.pdf", "x", access)).rejects.toThrow(/already exists/);
    expect(await resolveWritablePath(".context/outbox/raport.pdf", "x", access, true)).toBe(path.join(repo, ".context", "outbox", "raport.pdf"));
  });

  it("refuses targets outside the roots, through symlinks, and secrets", async () => {
    await expect(resolveWritablePath("../x.txt", "x", access)).rejects.toThrow(/outside/);
    await expect(resolveWritablePath("escape/new/x.txt", "x", access)).rejects.toThrow(/outside/);
    await expect(fs.stat(path.join(tmp, "new"))).rejects.toThrow();
    await expect(resolveWritablePath("leak.txt", "x", access, true)).rejects.toThrow(/not a regular file/);
    await expect(resolveWritablePath(".env.local", "x", access)).rejects.toThrow(/secrets/);
  });
});

describe("safeFileName", () => {
  it("strips separators, control characters and leading dots", () => {
    expect(safeFileName("Q1/Q2: plan?.xlsx")).toBe("Q1_Q2_ plan_.xlsx");
    expect(safeFileName("..env")).toBe("_env");
    expect(safeFileName("  ")).toBe("download");
  });
});
