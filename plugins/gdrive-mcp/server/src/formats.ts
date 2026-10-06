// Google-native files (Docs, Sheets, Slides, Drawings) have no bytes of their own: they
// are exported to a regular format on the way out and converted from one on the way in.
// This module holds those mappings and the parsing of file references.

export const FOLDER = "application/vnd.google-apps.folder";
export const SHORTCUT = "application/vnd.google-apps.shortcut";
export const DOCUMENT = "application/vnd.google-apps.document";
export const SPREADSHEET = "application/vnd.google-apps.spreadsheet";
export const PRESENTATION = "application/vnd.google-apps.presentation";
export const DRAWING = "application/vnd.google-apps.drawing";
export const SCRIPT = "application/vnd.google-apps.script";

// Export formats by file extension.
export const FORMATS: Record<string, string> = {
  md: "text/markdown",
  txt: "text/plain",
  html: "text/html",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  odt: "application/vnd.oasis.opendocument.text",
  rtf: "application/rtf",
  epub: "application/epub+zip",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ods: "application/x-vnd.oasis.opendocument.spreadsheet",
  csv: "text/csv",
  tsv: "text/tab-separated-values",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  odp: "application/vnd.oasis.opendocument.presentation",
  png: "image/png",
  jpg: "image/jpeg",
  svg: "image/svg+xml",
  json: "application/vnd.google-apps.script+json",
};

interface NativeType {
  label: string;
  download: string[]; // allowed formats, the first is the default
  text?: string; // the format read_file returns
  textNote?: string;
}

export const NATIVE: Record<string, NativeType> = {
  [DOCUMENT]: { label: "Google Doc", download: ["docx", "pdf", "md", "txt", "html", "odt", "rtf", "epub"], text: "md" },
  [SPREADSHEET]: {
    label: "Google Sheet",
    download: ["xlsx", "pdf", "csv", "tsv", "ods"],
    text: "csv",
    textNote: "CSV export holds only the first sheet - download_file as xlsx for every sheet",
  },
  [PRESENTATION]: { label: "Google Slides", download: ["pptx", "pdf", "txt", "odp"], text: "txt" },
  [DRAWING]: { label: "Google Drawing", download: ["png", "pdf", "svg", "jpg"] },
  [SCRIPT]: { label: "Apps Script", download: ["json"], text: "json" },
};

export function isNative(mimeType: string | null | undefined): boolean {
  return !!mimeType && mimeType.startsWith("application/vnd.google-apps.");
}

// The export for download_file: a requested format checked against the type, or its default.
export function downloadFormat(mimeType: string, requested?: string): { ext: string; mimeType: string } {
  const native = NATIVE[mimeType];
  if (!native) throw new Error(`${mimeType} cannot be exported - only Docs, Sheets, Slides, Drawings and Apps Script can`);
  const ext = (requested ?? native.download[0]).replace(/^\./, "").toLowerCase();
  if (!native.download.includes(ext)) {
    throw new Error(`A ${native.label} exports to ${native.download.join(", ")} - not '${ext}'`);
  }
  return { ext, mimeType: FORMATS[ext] };
}

// The export for read_file, or null when the type has no text form.
export function textExport(mimeType: string): { mimeType: string; note?: string } | null {
  const native = NATIVE[mimeType];
  if (!native?.text) return null;
  return { mimeType: FORMATS[native.text], note: native.textNote };
}

// Regular files that read_file returns as text.
export function isTextMime(mimeType: string | null | undefined): boolean {
  if (!mimeType) return false;
  return (
    mimeType.startsWith("text/") ||
    /[+/](json|xml|yaml|javascript|x-sh|x-httpd-php|sql|toml)$/.test(mimeType) ||
    mimeType === "application/x-yaml"
  );
}

// Which Google type an upload becomes when converted.
const IMPORTS: Record<string, string> = {
  "text/markdown": DOCUMENT,
  "text/plain": DOCUMENT,
  "text/html": DOCUMENT,
  "application/rtf": DOCUMENT,
  "application/msword": DOCUMENT,
  [FORMATS.docx]: DOCUMENT,
  [FORMATS.odt]: DOCUMENT,
  "text/csv": SPREADSHEET,
  "text/tab-separated-values": SPREADSHEET,
  "application/vnd.ms-excel": SPREADSHEET,
  [FORMATS.xlsx]: SPREADSHEET,
  "application/vnd.oasis.opendocument.spreadsheet": SPREADSHEET,
  "application/vnd.ms-powerpoint": PRESENTATION,
  [FORMATS.pptx]: PRESENTATION,
  [FORMATS.odp]: PRESENTATION,
};

export function importTargetOf(mimeType: string): string | undefined {
  return IMPORTS[mimeType];
}

export function importTarget(mimeType: string): string {
  const target = IMPORTS[mimeType];
  if (!target) {
    throw new Error(
      `${mimeType} cannot be converted to a Google file - only text, Markdown, HTML, Word, Excel, CSV, PowerPoint and OpenDocument files can`
    );
  }
  return target;
}

// A file id, or the id inside a Drive / Docs URL.
export function fileIdFrom(input: unknown, name = "fileId"): string {
  if (typeof input !== "string" || !input.trim()) throw new Error(`'${name}' is required`);
  const s = input.trim();
  if (/^[A-Za-z0-9_-]+$/.test(s)) return s;
  let url: URL;
  try {
    url = new URL(s);
  } catch {
    throw new Error(`'${name}': '${s}' is neither a Drive file id nor a URL`);
  }
  if (!/(^|\.)google\.com$/.test(url.hostname)) throw new Error(`'${name}': ${url.hostname} is not a Google Drive URL`);
  const fromPath = url.pathname.match(/\/(?:d|folders)\/([A-Za-z0-9_-]+)/);
  const id = fromPath?.[1] ?? url.searchParams.get("id");
  if (!id) throw new Error(`'${name}': no file id in ${s}`);
  return id;
}

// A string for the Drive query language, quoted.
export function quote(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

// The 'query' of search_files: Drive query syntax passes through, anything else is a
// full-text phrase.
export function searchQuery(query: string | undefined, folderId?: string, mimeType?: string, includeTrashed = false): string {
  const parts: string[] = [];
  const q = query?.trim();
  if (q) {
    const isSyntax = /\b(contains|in parents|in owners|in writers|in readers|has \{)|[=<>]|\b(trashed|starred|sharedWithMe)\b/.test(q);
    parts.push(isSyntax ? `(${q})` : `fullText contains ${quote(q)}`);
  }
  if (folderId) parts.push(`${quote(folderId)} in parents`);
  if (mimeType) parts.push(`mimeType = ${quote(mimeType)}`);
  if (!includeTrashed && !/\btrashed\b/.test(q ?? "")) parts.push("trashed = false");
  return parts.join(" and ");
}

const ALIASES: Record<string, string> = {
  folder: FOLDER,
  doc: DOCUMENT,
  document: DOCUMENT,
  sheet: SPREADSHEET,
  spreadsheet: SPREADSHEET,
  slides: PRESENTATION,
  presentation: PRESENTATION,
  drawing: DRAWING,
  pdf: "application/pdf",
};

// A MIME type, or one of the short names above.
export function mimeTypeFrom(value: string): string {
  return ALIASES[value.trim().toLowerCase()] ?? value.trim();
}
