// Local files for uploads and downloads.
//
// Every path is checked against an explicit allowlist after resolving symlinks, so an
// upload can never carry a file from outside the project directory and the extra roots
// named in the project config, and a download can never land outside them. Secrets inside
// those roots are refused on top of that.

import * as fs from "fs/promises";
import * as path from "path";

export interface FileAccess {
  baseDir: string; // relative paths resolve here (the project directory)
  roots: string[]; // files must live under one of these
  denied?: string[]; // files or directories never to upload or overwrite (OAuth clients, token store)
}

export interface LocalFile {
  path: string;
  filename: string;
  mimeType: string;
  size: number;
}

// Secrets living next to the allowed files: .env files, OAuth credentials/tokens.
function isSecretFile(filePath: string): boolean {
  const name = path.basename(filePath).toLowerCase();
  return name.startsWith(".env") || /-(credentials|tokens)\.json$/.test(name);
}

function isInside(filePath: string, root: string): boolean {
  const rel = path.relative(root, filePath);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

async function realRoots(roots: string[]): Promise<string[]> {
  const resolved = await Promise.all(roots.map((r) => fs.realpath(r).catch(() => null)));
  return resolved.filter((r): r is string => r !== null);
}

function checkInput(input: string): string {
  const p = input.trim();
  if (!p) throw new Error("Empty file path");
  if (p.startsWith("~")) throw new Error(`'${p}': use an absolute path instead of ~`);
  return p;
}

async function assertAllowed(real: string, shown: string, access: FileAccess, verb: string): Promise<void> {
  const roots = await realRoots(access.roots);
  if (!roots.some((root) => isInside(real, root))) {
    throw new Error(
      `'${shown}' is outside the directories the Google Drive server may ${verb} ` +
        `(${access.roots.join(", ")}). Use a path inside the project directory.`
    );
  }
  const denied = await realRoots(access.denied ?? []);
  if (isSecretFile(real) || denied.some((d) => isInside(real, d))) {
    throw new Error(`'${shown}' looks like a secrets file - refusing to ${verb} it`);
  }
}

// Absolute path of a readable regular file inside the allowed roots, or an error.
export async function resolveLocalFile(input: string, access: FileAccess): Promise<string> {
  const p = checkInput(input);
  let real: string;
  try {
    real = await fs.realpath(path.resolve(access.baseDir, p));
  } catch {
    throw new Error(`File not found: ${p}`);
  }
  await assertAllowed(real, p, access, "read");
  const stat = await fs.stat(real);
  if (!stat.isFile()) throw new Error(`'${p}' is not a regular file`);
  return real;
}

export async function localFile(input: string, access: FileAccess): Promise<LocalFile> {
  const real = await resolveLocalFile(input, access);
  const filename = path.basename(real);
  const stat = await fs.stat(real);
  return { path: real, filename, mimeType: mimeTypeOf(filename), size: stat.size };
}

export function mimeTypeOf(filename: string): string {
  const type = Bun.file(filename).type.split(";")[0];
  // Bun has no entry for Markdown; Drive needs it to convert .md into a Google Doc.
  if (/\.(md|markdown)$/i.test(filename)) return "text/markdown";
  return type || "application/octet-stream";
}

// Where a download may be written. `input` is a file path, or a directory (an existing
// one, or a path ending in /) to put `defaultName` in. Missing parent directories are
// created; an existing file is only replaced with `overwrite`.
export async function resolveWritablePath(
  input: string,
  defaultName: string,
  access: FileAccess,
  overwrite = false
): Promise<string> {
  const p = checkInput(input);
  let target = path.resolve(access.baseDir, p);
  const isDir = /[\\/]$/.test(p) || (await fs.stat(target).then((s) => s.isDirectory()).catch(() => false));
  if (isDir) target = path.join(target, safeFileName(defaultName));

  // The nearest existing ancestor decides where the new directories would end up.
  let existing = path.dirname(target);
  while (!(await fs.stat(existing).then(() => true).catch(() => false))) existing = path.dirname(existing);
  const rest = path.relative(existing, path.dirname(target));
  await assertAllowed(path.join(await fs.realpath(existing), rest, path.basename(target)), p, access, "write");

  await fs.mkdir(path.dirname(target), { recursive: true });
  const real = path.join(await fs.realpath(path.dirname(target)), path.basename(target));
  await assertAllowed(real, p, access, "write");

  const stat = await fs.lstat(real).catch(() => null);
  if (stat) {
    if (!stat.isFile()) throw new Error(`'${p}' exists and is not a regular file`);
    if (!overwrite) throw new Error(`'${p}' already exists - pass overwrite: true to replace it, or choose another path`);
  }
  return real;
}

// A Drive name made safe for the local filesystem: no separators, no control characters.
export function safeFileName(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/^\.+/, "_").trim();
  return cleaned || "download";
}
