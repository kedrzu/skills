// MCP tool definitions and handlers. The tool list is generated from the project's
// permissions, so the agent only sees what it may do; the dispatcher checks them again,
// because a client can still hold a list from before the config changed.

import type { drive_v3 } from "@googleapis/drive";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import { createReadStream, createWriteStream } from "fs";
import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { Readable } from "stream";
import { pipeline } from "stream/promises";
import { NotConfigured, type AccountRegistry } from "./accounts.js";
import { CONFIG_FILE, resolvePath } from "./config.js";
import { localFile, mimeTypeOf, resolveWritablePath, type FileAccess } from "./files.js";
import {
  DOCUMENT,
  downloadFormat,
  fileIdFrom,
  FOLDER,
  importTarget,
  importTargetOf,
  isNative,
  isTextMime,
  mimeTypeFrom,
  NATIVE,
  quote,
  searchQuery,
  SHORTCUT,
  SPREADSHEET,
  textExport,
} from "./formats.js";
import {
  assertAllowed,
  effectivePermissions,
  PERMISSION_DESCRIPTIONS,
  PermissionDenied,
  PERMISSIONS,
  TOOL_PERMISSION,
  type Permissions,
} from "./permissions.js";

const account = { type: "string", description: "Google account email (from list_accounts)" };
const fileId = { type: "string", description: "File id, or a drive.google.com / docs.google.com URL" };

const FILES_NOTE =
  "Local paths are absolute or relative to the project directory, and must live in the project or in a directory the project config allows " +
  "(files.roots, files.downloadsDir). .env files, OAuth client files and tokens are refused.";

// Google exports and reads are capped by Drive at about 10 MB; text past this is cut.
const DEFAULT_MAX_CHARS = 100_000;
const MAX_TEXT_BYTES = 10 * 1024 * 1024;

const FILE_FIELDS =
  "id, name, mimeType, size, modifiedTime, parents, driveId, webViewLink, trashed, starred, shortcutDetails(targetId, targetMimeType)";
const INFO_FIELDS =
  `${FILE_FIELDS}, description, createdTime, owners(displayName, emailAddress), lastModifyingUser(displayName, emailAddress), ` +
  "shared, version, capabilities(canEdit, canTrash, canDownload, canAddChildren)";

const ALL_DRIVES = { supportsAllDrives: true } as const;

export function toolDefinitions(permissions: Permissions): Tool[] {
  const tools: Tool[] = [
    {
      name: "list_accounts",
      description:
        "List the Google accounts this project may use, what the project allows in Drive (permissions), and any setup problem " +
        "(missing config, undecryptable client file, revoked token). Every other tool takes one of these as 'account'.",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "search_files",
      description:
        "Search Drive (My Drive, shared with me, shared drives). 'query' is either plain words (full-text search of names and contents) " +
        "or Drive query syntax, e.g. \"name contains 'invoice' and modifiedTime > '2026-01-01'\". Trashed files are left out.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          query: { type: "string", description: "Words to find, or a Drive query ('q' syntax)" },
          folderId: { type: "string", description: "Only direct children of this folder (id or URL)" },
          mimeType: {
            type: "string",
            description: "Only this type: a MIME type or folder, document, spreadsheet, presentation, drawing, pdf",
          },
          maxResults: { type: "number", description: "Maximum number of files (default 20, at most 100)" },
          pageToken: { type: "string", description: "nextPageToken from a previous call" },
        },
        required: ["account"],
      },
    },
    {
      name: "list_folder",
      description: "List a folder's direct children, folders first. Without 'folderId' lists the root of My Drive; a shared drive id lists that drive's root.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          folderId: { type: "string", description: "Folder or shared drive id, or a URL (default: My Drive root)" },
          maxResults: { type: "number", description: "Maximum number of entries (default 100, at most 1000)" },
          pageToken: { type: "string", description: "nextPageToken from a previous call" },
        },
        required: ["account"],
      },
    },
    {
      name: "get_file_info",
      description: "Metadata of a file or folder: type, size, path, owners, dates, link, description, whether it is trashed and what the account may do with it.",
      inputSchema: { type: "object", properties: { account, fileId }, required: ["account", "fileId"] },
    },
    {
      name: "list_shared_drives",
      description: "List the shared drives the account belongs to. Their ids work as 'folderId' in list_folder and search_files.",
      inputSchema: { type: "object", properties: { account }, required: ["account"] },
    },
    {
      name: "read_file",
      description:
        "Read a file's contents as text: a Google Doc as Markdown, a Sheet as CSV (first sheet only), Slides as plain text, " +
        "and text-like files (txt, md, csv, json, xml, code) as they are. Binary files (PDF, images, Office) are refused - use download_file.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          fileId,
          maxChars: { type: "number", description: `Cut the text after this many characters (default ${DEFAULT_MAX_CHARS})` },
        },
        required: ["account", "fileId"],
      },
    },
    {
      name: "download_file",
      description:
        "Save a file to the local disk. Google files are exported: Docs to docx (or pdf, md, txt, html, odt, rtf, epub), " +
        "Sheets to xlsx (or pdf, csv, tsv, ods), Slides to pptx (or pdf, txt, odp), Drawings to png (or pdf, svg, jpg). " +
        FILES_NOTE,
      inputSchema: {
        type: "object",
        properties: {
          account,
          fileId,
          path: {
            type: "string",
            description: "Target file, or a directory (existing, or ending in /) to save under the Drive name. Default: the downloads directory.",
          },
          format: { type: "string", description: "Export format for Google files, as an extension (e.g. 'pdf')" },
          overwrite: { type: "boolean", description: "Replace an existing local file (default false)" },
        },
        required: ["account", "fileId"],
      },
    },
    {
      name: "upload_file",
      description:
        "Create a new file in Drive from a local file ('path') or from text ('content' with 'name'). With convert: true it becomes a " +
        "Google file: .md/.txt/.html/.docx -> Doc, .csv/.xlsx -> Sheet, .pptx -> Slides. Drive allows duplicate names; to change an " +
        "existing file use update_file. " +
        FILES_NOTE,
      inputSchema: {
        type: "object",
        properties: {
          account,
          path: { type: "string", description: "Local file to upload" },
          content: { type: "string", description: "Text to upload instead of a local file (needs 'name')" },
          name: { type: "string", description: "Name in Drive (default: the local file name; the extension is dropped on convert)" },
          folderId: { type: "string", description: "Parent folder or shared drive id, or a URL (default: My Drive root)" },
          convert: { type: "boolean", description: "Convert to a Google Doc / Sheet / Slides (default false)" },
          description: { type: "string", description: "File description" },
        },
        required: ["account"],
      },
    },
    {
      name: "create_folder",
      description: "Create a folder in Drive.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          name: { type: "string", description: "Folder name" },
          parentId: { type: "string", description: "Parent folder or shared drive id, or a URL (default: My Drive root)" },
        },
        required: ["account", "name"],
      },
    },
    {
      name: "update_file",
      description:
        "Replace a file's contents with a local file ('path') or text ('content'), keeping its id, link, sharing and history. " +
        "A Google Doc takes Markdown, text, HTML or docx; a Sheet takes CSV or xlsx; Slides take pptx. " +
        FILES_NOTE,
      inputSchema: {
        type: "object",
        properties: {
          account,
          fileId,
          path: { type: "string", description: "Local file with the new contents" },
          content: { type: "string", description: "New contents as text, instead of a local file" },
          contentType: {
            type: "string",
            description: "MIME type of 'content' (default: text/markdown for a Google Doc, else the file's own type)",
          },
        },
        required: ["account", "fileId"],
      },
    },
    {
      name: "update_file_metadata",
      description: "Rename, move, describe or star a file or folder. Pass only what changes.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          fileId,
          name: { type: "string", description: "New name" },
          description: { type: "string", description: "New description ('' clears it)" },
          starred: { type: "boolean", description: "Star or unstar" },
          moveTo: { type: "string", description: "Folder or shared drive id (or URL) to move the file into, out of all its current folders" },
        },
        required: ["account", "fileId"],
      },
    },
    {
      name: "trash_file",
      description:
        "Move a file or folder (with everything in it) to the Drive trash. It can be restored with restore_file for 30 days; " +
        "nothing is ever deleted permanently.",
      inputSchema: { type: "object", properties: { account, fileId }, required: ["account", "fileId"] },
    },
    {
      name: "restore_file",
      description: "Take a file or folder out of the trash.",
      inputSchema: { type: "object", properties: { account, fileId }, required: ["account", "fileId"] },
    },
  ];
  return tools.filter((t) => {
    const needed = TOOL_PERMISSION[t.name];
    return !needed || permissions[needed];
  });
}

function jsonResult(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

function bool(value: unknown): boolean {
  return value === true || value === "true";
}

function count(value: unknown, fallback: number, max: number): number {
  const n = Math.floor(Number(value));
  return Number.isFinite(n) && n > 0 ? Math.min(n, max) : fallback;
}

function optionalString(value: unknown, name: string): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string") throw new Error(`'${name}' must be a string`);
  return value;
}

function typeLabel(mimeType: string | null | undefined): string {
  if (!mimeType) return "unknown";
  if (mimeType === FOLDER) return "folder";
  if (mimeType === SHORTCUT) return "shortcut";
  return NATIVE[mimeType]?.label ?? mimeType;
}

function summary(f: drive_v3.Schema$File) {
  return {
    id: f.id,
    name: f.name,
    type: typeLabel(f.mimeType),
    mimeType: f.mimeType,
    size: f.size ? Number(f.size) : undefined,
    modifiedTime: f.modifiedTime,
    webViewLink: f.webViewLink,
    starred: f.starred || undefined,
    trashed: f.trashed || undefined,
    shortcutTo: f.shortcutDetails?.targetId ? { id: f.shortcutDetails.targetId, mimeType: f.shortcutDetails.targetMimeType } : undefined,
  };
}

// The bytes of an API response, whatever shape the client returned them in.
function bytes(data: unknown): Buffer {
  if (Buffer.isBuffer(data)) return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data);
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  if (typeof data === "string") return Buffer.from(data);
  throw new Error("Unexpected response body from Drive");
}

interface Upload {
  mimeType: string;
  body: () => Readable;
  name?: string; // the local file name, for upload_file
}

export class DriveTools {
  constructor(readonly registry: AccountRegistry) {}

  get permissions(): Permissions {
    return effectivePermissions(this.registry.loaded?.config.permissions);
  }

  downloadsDir(): string {
    const configured = this.registry.loaded?.config.files?.downloadsDir;
    return configured ? resolvePath(this.registry.projectDir, configured) : path.join(os.tmpdir(), "gdrive-mcp", "downloads");
  }

  fileAccess(): FileAccess {
    const projectDir = this.registry.projectDir;
    const roots = (this.registry.loaded?.config.files?.roots ?? []).map((r) => resolvePath(projectDir, r));
    return { baseDir: projectDir, roots: [projectDir, ...roots, this.downloadsDir()], denied: this.registry.deniedFiles() };
  }

  async call(name: string, args: Record<string, any> = {}) {
    try {
      this.registry.refreshIfChanged();
      assertAllowed(name, this.permissions, CONFIG_FILE);
      return await this.dispatch(name, args);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const hint = error instanceof NotConfigured || error instanceof PermissionDenied ? "" : this.authHint(message);
      return { content: [{ type: "text" as const, text: `Error: ${message}${hint}` }], isError: true };
    }
  }

  private authHint(message: string): string {
    return /invalid_grant|invalid_client|unauthorized_client/i.test(message)
      ? " - the sign-in for this account is no longer valid (revoked, password changed, or an External app in Testing mode, whose tokens expire after 7 days). " +
          "Ask the user to run /gdrive-mcp:setup to sign in again."
      : "";
  }

  private drive(email: string): drive_v3.Drive {
    return this.registry.get(email).drive;
  }

  // A file's metadata, following a shortcut to its target when asked to.
  private async file(drive: drive_v3.Drive, id: string, fields = FILE_FIELDS, follow = false): Promise<drive_v3.Schema$File> {
    const res = await drive.files.get({ fileId: id, fields, ...ALL_DRIVES });
    if (follow && res.data.mimeType === SHORTCUT && res.data.shortcutDetails?.targetId) {
      return this.file(drive, res.data.shortcutDetails.targetId, fields, false);
    }
    return res.data;
  }

  // "My Drive/Projects/2026" style path of a file's first parent chain.
  private async pathOf(drive: drive_v3.Drive, f: drive_v3.Schema$File): Promise<string | undefined> {
    const names: string[] = [];
    let parent = f.parents?.[0];
    for (let hop = 0; parent && hop < 25; hop++) {
      if (f.driveId && parent === f.driveId) {
        const d = await drive.drives.get({ driveId: parent, fields: "name" }).catch(() => null);
        names.unshift(d?.data.name ?? "Shared drive");
        return names.join("/");
      }
      const p = await drive.files.get({ fileId: parent, fields: "name, parents", ...ALL_DRIVES }).catch(() => null);
      if (!p) {
        names.unshift("…");
        return names.join("/");
      }
      names.unshift(p.data.parents?.length ? (p.data.name ?? "?") : "My Drive");
      parent = p.data.parents?.[0];
    }
    return names.length ? names.join("/") : undefined;
  }

  private async list(drive: drive_v3.Drive, q: string, max: number, pageToken?: string, orderBy?: string) {
    const res = await drive.files.list({
      q,
      pageSize: max,
      pageToken,
      orderBy,
      fields: `nextPageToken, incompleteSearch, files(${FILE_FIELDS})`,
      corpora: "allDrives",
      includeItemsFromAllDrives: true,
      ...ALL_DRIVES,
    });
    const files = (res.data.files ?? []).map(summary);
    return {
      count: files.length,
      files,
      nextPageToken: res.data.nextPageToken ?? undefined,
      incompleteSearch: res.data.incompleteSearch || undefined,
    };
  }

  // New contents from either a local file or text - exactly one of them.
  private async source(args: Record<string, any>, contentType?: string): Promise<Upload> {
    const p = optionalString(args.path, "path");
    const content = args.content;
    if ((p === undefined) === (content === undefined || content === null)) {
      throw new Error("Pass either 'path' (a local file) or 'content' (text), not both");
    }
    if (p !== undefined) {
      const local = await localFile(p, this.fileAccess());
      return { mimeType: local.mimeType, body: () => createReadStream(local.path), name: local.filename };
    }
    const text = typeof content === "string" ? content : JSON.stringify(content);
    return { mimeType: contentType ?? "text/plain", body: () => Readable.from([Buffer.from(text, "utf-8")]) };
  }

  private async dispatch(name: string, args: Record<string, any>) {
    switch (name) {
      case "list_accounts": {
        this.registry.reload();
        const permissions = this.permissions;
        const allowed = PERMISSIONS.filter((p) => permissions[p]);
        const notAllowed = PERMISSIONS.filter((p) => !permissions[p]);
        const permissionReport = {
          allowed: Object.fromEntries(allowed.map((p) => [p, PERMISSION_DESCRIPTIONS[p]])),
          notAllowed: notAllowed.length ? notAllowed : undefined,
          note: notAllowed.length ? `Only the user can change these, in 'permissions' in ${CONFIG_FILE}` : undefined,
        };
        if (!this.registry.loaded) return jsonResult({ accounts: [], setup: this.registry.notConfiguredMessage() });
        const accounts = [...this.registry.accounts.values()].map((a) => ({ email: a.email, client: a.client.name }));
        return jsonResult({
          accounts,
          permissions: permissionReport,
          notAllowedHere: this.registry.hidden.length ? this.registry.hidden : undefined,
          problems: this.registry.problems.length ? this.registry.problems : undefined,
          setup: accounts.length ? undefined : "No account is signed in for this project - ask the user to run /gdrive-mcp:setup",
        });
      }

      case "search_files": {
        const drive = this.drive(args.account);
        const folder = optionalString(args.folderId, "folderId");
        const type = optionalString(args.mimeType, "mimeType");
        const query = optionalString(args.query, "query");
        if (!query && !folder && !type) throw new Error("Pass a 'query', a 'folderId' or a 'mimeType'");
        const q = searchQuery(query, folder && fileIdFrom(folder, "folderId"), type && mimeTypeFrom(type));
        // Drive refuses orderBy together with a full-text search.
        const orderBy = /fullText contains/.test(q) ? undefined : "modifiedTime desc";
        return jsonResult(await this.list(drive, q, count(args.maxResults, 20, 100), optionalString(args.pageToken, "pageToken"), orderBy));
      }

      case "list_folder": {
        const drive = this.drive(args.account);
        const folder = args.folderId ? fileIdFrom(args.folderId, "folderId") : "root";
        const q = `${quote(folder)} in parents and trashed = false`;
        return jsonResult({
          folderId: folder,
          ...(await this.list(drive, q, count(args.maxResults, 100, 1000), optionalString(args.pageToken, "pageToken"), "folder, name")),
        });
      }

      case "get_file_info": {
        const drive = this.drive(args.account);
        const f = await this.file(drive, fileIdFrom(args.fileId), INFO_FIELDS);
        return jsonResult({
          ...summary(f),
          path: await this.pathOf(drive, f),
          description: f.description || undefined,
          createdTime: f.createdTime,
          owners: f.owners?.map((o) => o.emailAddress ?? o.displayName),
          lastModifiedBy: f.lastModifyingUser?.emailAddress ?? f.lastModifyingUser?.displayName,
          sharedDriveId: f.driveId || undefined,
          shared: f.shared,
          version: f.version,
          capabilities: f.capabilities,
          exportFormats: f.mimeType && NATIVE[f.mimeType] ? NATIVE[f.mimeType].download : undefined,
        });
      }

      case "list_shared_drives": {
        const drive = this.drive(args.account);
        const drives: { id?: string | null; name?: string | null }[] = [];
        let pageToken: string | undefined;
        do {
          const res = await drive.drives.list({ pageSize: 100, pageToken, fields: "nextPageToken, drives(id, name)" });
          drives.push(...(res.data.drives ?? []).map((d) => ({ id: d.id, name: d.name })));
          pageToken = res.data.nextPageToken ?? undefined;
        } while (pageToken && drives.length < 1000);
        return jsonResult({ count: drives.length, drives });
      }

      case "read_file": {
        const drive = this.drive(args.account);
        const f = await this.file(drive, fileIdFrom(args.fileId), FILE_FIELDS, true);
        const mime = f.mimeType ?? "";
        let data: Buffer;
        let note: string | undefined;
        if (mime === FOLDER) throw new Error(`'${f.name}' is a folder - use list_folder`);
        if (isNative(mime)) {
          const exp = textExport(mime);
          if (!exp) throw new Error(`A ${typeLabel(mime)} has no text form - use download_file`);
          const res = await drive.files.export({ fileId: f.id!, mimeType: exp.mimeType }, { responseType: "arraybuffer" });
          data = bytes(res.data);
          note = exp.note;
        } else {
          if (!isTextMime(mime)) throw new Error(`'${f.name}' is ${mime}, not text - use download_file to save it locally`);
          if (Number(f.size ?? 0) > MAX_TEXT_BYTES) throw new Error(`'${f.name}' is over 10 MB - use download_file`);
          const res = await drive.files.get({ fileId: f.id!, alt: "media", ...ALL_DRIVES }, { responseType: "arraybuffer" });
          data = bytes(res.data);
        }
        const text = data.toString("utf-8");
        const max = count(args.maxChars, DEFAULT_MAX_CHARS, Number.MAX_SAFE_INTEGER);
        const truncated = text.length > max;
        const header = { id: f.id, name: f.name, type: typeLabel(mime), modifiedTime: f.modifiedTime, chars: text.length, truncated: truncated || undefined, note };
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(header, null, 2) },
            { type: "text" as const, text: truncated ? text.slice(0, max) : text },
          ],
        };
      }

      case "download_file": {
        const drive = this.drive(args.account);
        const f = await this.file(drive, fileIdFrom(args.fileId), FILE_FIELDS, true);
        const mime = f.mimeType ?? "";
        if (mime === FOLDER) throw new Error(`'${f.name}' is a folder - download its files one by one`);
        const requested = optionalString(args.format, "format");
        let filename = f.name ?? f.id!;
        let exportMime: string | undefined;
        if (isNative(mime)) {
          const fmt = downloadFormat(mime, requested);
          exportMime = fmt.mimeType;
          filename = `${filename}.${fmt.ext}`;
        } else if (requested) {
          throw new Error(`'format' only applies to Google files; '${f.name}' is ${mime} and is saved as it is`);
        }
        // An allowed root only counts once it exists.
        await fs.mkdir(this.downloadsDir(), { recursive: true });
        const access = this.fileAccess();
        const target = await resolveWritablePath(
          optionalString(args.path, "path") ?? this.downloadsDir() + path.sep,
          filename,
          access,
          bool(args.overwrite)
        );
        const res = exportMime
          ? await drive.files.export({ fileId: f.id!, mimeType: exportMime }, { responseType: "stream" })
          : await drive.files.get({ fileId: f.id!, alt: "media", ...ALL_DRIVES }, { responseType: "stream" });
        const partial = `${target}.part-${process.pid}`;
        try {
          await pipeline(res.data as unknown as Readable, createWriteStream(partial, { mode: 0o644 }));
          await fs.rename(partial, target);
        } catch (e) {
          await fs.rm(partial, { force: true });
          throw e;
        }
        const stat = await fs.stat(target);
        return jsonResult({ status: "Downloaded", path: target, size: stat.size, mimeType: exportMime ?? mime, from: summary(f) });
      }

      case "upload_file": {
        const drive = this.drive(args.account);
        const src = await this.source(args, args.content !== undefined ? mimeTypeOf(String(args.name ?? "")) : undefined);
        const convert = bool(args.convert);
        let name = optionalString(args.name, "name") ?? src.name;
        if (!name) throw new Error("'name' is required with 'content'");
        if (src.name === undefined && !/\.[A-Za-z0-9]+$/.test(name)) {
          // Text without an extension is uploaded as plain text.
          src.mimeType = "text/plain";
        }
        const target = convert ? importTarget(src.mimeType) : undefined;
        if (convert) name = name.replace(/\.[A-Za-z0-9]+$/, "") || name;
        const folder = args.folderId ? fileIdFrom(args.folderId, "folderId") : undefined;
        const created = await drive.files.create({
          requestBody: {
            name,
            parents: folder ? [folder] : undefined,
            mimeType: target,
            description: optionalString(args.description, "description"),
          },
          media: { mimeType: src.mimeType, body: src.body() },
          fields: FILE_FIELDS,
          ...ALL_DRIVES,
        });
        const duplicates = await drive.files
          .list({
            q: `name = ${quote(name)} and ${quote(folder ?? "root")} in parents and trashed = false`,
            fields: "files(id)",
            corpora: "allDrives",
            includeItemsFromAllDrives: true,
            ...ALL_DRIVES,
          })
          .then((r) => (r.data.files ?? []).filter((x) => x.id !== created.data.id).length)
          .catch(() => 0);
        return jsonResult({
          status: "Uploaded",
          file: summary(created.data),
          note: duplicates ? `The folder now holds ${duplicates + 1} files named '${name}' - update_file replaces contents instead of adding a copy` : undefined,
        });
      }

      case "create_folder": {
        const drive = this.drive(args.account);
        const name = optionalString(args.name, "name");
        if (!name) throw new Error("'name' is required");
        const parent = args.parentId ? fileIdFrom(args.parentId, "parentId") : undefined;
        const created = await drive.files.create({
          requestBody: { name, mimeType: FOLDER, parents: parent ? [parent] : undefined },
          fields: FILE_FIELDS,
          ...ALL_DRIVES,
        });
        return jsonResult({ status: "Folder created", folder: summary(created.data) });
      }

      case "update_file": {
        const drive = this.drive(args.account);
        const f = await this.file(drive, fileIdFrom(args.fileId), FILE_FIELDS, true);
        const mime = f.mimeType ?? "";
        if (mime === FOLDER) throw new Error(`'${f.name}' is a folder - it has no contents to replace`);
        const native = isNative(mime);
        const defaultType = mime === DOCUMENT ? "text/markdown" : mime === SPREADSHEET ? "text/csv" : native ? undefined : mime || "text/plain";
        const contentType = optionalString(args.contentType, "contentType") ?? defaultType;
        const src = await this.source(args, contentType);
        if (native && importTargetOf(src.mimeType) !== mime) {
          throw new Error(`A ${typeLabel(mime)} cannot take ${src.mimeType} contents`);
        }
        const updated = await drive.files.update({
          fileId: f.id!,
          media: { mimeType: src.mimeType, body: src.body() },
          fields: `${FILE_FIELDS}, version`,
          ...ALL_DRIVES,
        });
        return jsonResult({ status: "Contents replaced", file: summary(updated.data), version: updated.data.version });
      }

      case "update_file_metadata": {
        const drive = this.drive(args.account);
        const id = fileIdFrom(args.fileId);
        const requestBody: drive_v3.Schema$File = {};
        const newName = optionalString(args.name, "name");
        if (newName) requestBody.name = newName;
        if (typeof args.description === "string") requestBody.description = args.description;
        if (args.starred !== undefined) requestBody.starred = bool(args.starred);
        let addParents: string | undefined;
        let removeParents: string | undefined;
        if (args.moveTo) {
          addParents = fileIdFrom(args.moveTo, "moveTo");
          const current = await this.file(drive, id, "parents");
          removeParents = (current.parents ?? []).filter((p) => p !== addParents).join(",") || undefined;
        }
        if (!Object.keys(requestBody).length && !addParents) {
          throw new Error("Nothing to change - pass name, description, starred or moveTo");
        }
        const updated = await drive.files.update({ fileId: id, requestBody, addParents, removeParents, fields: FILE_FIELDS, ...ALL_DRIVES });
        return jsonResult({ status: "Updated", file: summary(updated.data) });
      }

      case "trash_file":
      case "restore_file": {
        const drive = this.drive(args.account);
        const trashed = name === "trash_file";
        const updated = await drive.files.update({
          fileId: fileIdFrom(args.fileId),
          requestBody: { trashed },
          fields: FILE_FIELDS,
          ...ALL_DRIVES,
        });
        return jsonResult({
          status: trashed ? "Moved to trash (restorable for 30 days with restore_file)" : "Restored from trash",
          file: summary(updated.data),
        });
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  }
}
