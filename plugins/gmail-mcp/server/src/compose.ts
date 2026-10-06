// Draft composition: Markdown -> Gmail-looking HTML, signature, reply quote, MIME.
//
// Pure functions only (no Gmail API calls), so the whole draft shape is unit-testable.

import { createHash } from "crypto";
import * as path from "path";
import { fileURLToPath } from "url";
import { Marked } from "marked";
import MimeNode from "nodemailer/lib/mime-node";
import { detectMimeType } from "nodemailer/lib/mime-funcs/mime-types";
import TurndownService from "turndown";

export type BodyFormat = "markdown" | "html";

// Inline styles only where Gmail's defaults look broken; no font-family, so the
// draft keeps the account's default compose font and reads like a hand-written mail.
const TAG_STYLES: Record<string, string> = {
  p: "margin:0 0 1em 0",
  table: "border-collapse:collapse;margin:0 0 1em 0",
  th: "border:1px solid #ccc;padding:4px 8px",
  td: "border:1px solid #ccc;padding:4px 8px",
  blockquote: "margin:0 0 1em 0.8ex;border-left:1px solid #ccc;padding-left:1ex",
  pre: "font-family:monospace;white-space:pre-wrap;margin:0 0 1em 0",
  code: "font-family:monospace",
  ul: "margin:0 0 1em 0",
  ol: "margin:0 0 1em 0",
  hr: "border:none;border-top:1px solid #ccc",
  img: "max-width:100%",
};

const marked = new Marked({ gfm: true, breaks: true });

// Adds a style attribute to known tags that don't already carry one.
function addInlineStyles(html: string): string {
  return html.replace(
    /<(p|table|th|td|blockquote|pre|code|ul|ol|hr|img)(\s[^>]*)?>/g,
    (tag, name: string, attrs: string | undefined) => {
      if (attrs && /\sstyle=/i.test(attrs)) return tag;
      let style = TAG_STYLES[name];
      // Table cells: GFM column alignment as CSS (Gmail ignores align=), headers left by default.
      if (name === "th" || name === "td") {
        const align = attrs?.match(/\salign="(left|center|right)"/)?.[1];
        if (align || name === "th") style += `;text-align:${align ?? "left"}`;
      }
      return `<${name}${attrs ?? ""} style="${style}">`;
    }
  );
}

export function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false }) as string;
  return addInlineStyles(html.trim());
}

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Plain-text rendering of HTML for the text/plain alternative.
const plainTurndown = new TurndownService({
  headingStyle: "atx",
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  linkStyle: "inlined",
});
plainTurndown.remove(["style", "script", "head"]);
// A local image path means nothing to the recipient (and leaks the Mac's layout).
plainTurndown.addRule("local-image", {
  filter: (node) =>
    node.nodeName === "IMG" &&
    localImagePath((node as Element).getAttribute("src") || "") !== null,
  replacement: (_content, node) => {
    const el = node as Element;
    return imagePlaceholder(el.getAttribute("alt") || "", el.getAttribute("src") || "");
  },
});

export function htmlToPlain(html: string): string {
  return plainTurndown.turndown(html).replace(/\n{3,}/g, "\n\n").trim();
}

// Inner part of <body>, so a full HTML document can be embedded in a quote.
export function extractBodyInner(html: string): string {
  const body = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  const inner = body ? body[1] : html;
  return inner
    .replace(/<head[\s\S]*?<\/head>/gi, "")
    .replace(/<\/?html[^>]*>/gi, "")
    .replace(/<!DOCTYPE[^>]*>/gi, "")
    .trim();
}

// ----------------------------------------------------------------------------
// Local images -> inline (cid) parts
// ----------------------------------------------------------------------------

function decodeEntities(text: string): string {
  return text
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

// Image src pointing at a file on disk (absolute, relative or file://), decoded;
// null for anything the mail client fetches itself (http:, data:, cid:, //host).
export function localImagePath(src: string): string | null {
  const s = decodeEntities(src.trim());
  if (!s) return null;
  if (/^file:/i.test(s)) {
    try {
      return fileURLToPath(s);
    } catch {
      return null;
    }
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(s) || s.startsWith("//")) return null;
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function imagePlaceholder(alt: string, src: string): string {
  const name = path.basename(localImagePath(src) ?? src);
  return `[image: ${alt.trim() || name}]`;
}

export interface InlineImageRef {
  path: string; // as written in the body (resolved against the file roots later)
  cid: string;
}

// Gmail's own inline-image id ("ii_" + hex). The web composer only re-embeds
// images whose Content-ID/X-Attachment-Id look like this when the draft is sent;
// any other cid ends up as a dead mail.google.com link in the sent mail.
// Same path -> same id, so an image used twice is attached once.
export function imageCid(filePath: string): string {
  return `ii_${createHash("sha1").update(filePath).digest("hex").slice(0, 20)}`;
}

// Rewrites <img src="local path"> to cid: references and lists the files to attach.
export function collectLocalImages(html: string): {
  html: string;
  images: InlineImageRef[];
} {
  const images: InlineImageRef[] = [];
  const out = html.replace(/<img\b[^>]*>/gi, (tag) => {
    const src = tag.match(/\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)')/i);
    if (!src) return tag;
    const filePath = localImagePath(src[1] ?? src[2]);
    if (filePath === null) return tag;
    const cid = imageCid(filePath);
    if (!images.some((i) => i.cid === cid)) images.push({ path: filePath, cid });
    let result = tag.replace(src[0], ` src="cid:${cid}"`);
    if (!/\sstyle\s*=/i.test(result)) {
      result = result.replace(/^<img\b/i, '<img style="max-width:100%"');
    }
    return result;
  });
  return { html: out, images };
}

// ![alt](local path) -> [image: alt] in the plain-text part; remote images stay.
function markdownImagesToPlain(md: string): string {
  return md.replace(
    /!\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/g,
    (whole, alt: string, target: string) => {
      const src = target.replace(/^<|>$/g, "");
      return localImagePath(src) === null ? whole : imagePlaceholder(alt, src);
    }
  );
}

// ----------------------------------------------------------------------------
// Reply helpers
// ----------------------------------------------------------------------------

export function replySubject(subject: string): string {
  const s = subject.trim();
  return /^(re|odp|aw|sv)\s*:/i.test(s) ? s : `Re: ${s}`;
}

export function buildReferences(
  references: string,
  messageId: string
): string {
  const ids = references.split(/\s+/).filter(Boolean);
  if (messageId && !ids.includes(messageId)) ids.push(messageId);
  return ids.join(" ");
}

export interface QuotedMessage {
  from: string; // raw From header, e.g. "Jan Kowalski <jan@x.pl>"
  date: string; // raw Date header
  html: string | null;
  text: string | null;
}

// "W dniu pon., 28 wrz 2026 o 10:15 Jan Kowalski <jan@x.pl> napisał(a):" — Gmail's Polish attribution.
export function quoteAttribution(rawFrom: string, date: string): string {
  // '"Jan Kowalski" <jan@x.pl>' -> 'Jan Kowalski <jan@x.pl>', as Gmail shows it.
  const from = rawFrom.replace(/^"(.*)"(\s*<)/, "$1$2");
  const d = new Date(date);
  if (isNaN(d.getTime())) return `${from} napisał(a):`;
  const tz = "Europe/Warsaw";
  const weekday = d.toLocaleDateString("pl-PL", { weekday: "short", timeZone: tz });
  const day = d.toLocaleDateString("pl-PL", { day: "numeric", timeZone: tz });
  const month = d.toLocaleDateString("pl-PL", { month: "short", timeZone: tz });
  const year = d.toLocaleDateString("pl-PL", { year: "numeric", timeZone: tz });
  const time = d.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
  return `W dniu ${weekday}, ${day} ${month} ${year} o ${time} ${from} napisał(a):`;
}

export function buildQuoteHtml(q: QuotedMessage): string {
  const content = q.html
    ? extractBodyInner(q.html)
    : escapeHtml(q.text ?? "").replace(/\r?\n/g, "<br>");
  return (
    `<div class="gmail_quote"><div dir="ltr" class="gmail_attr">` +
    `${escapeHtml(quoteAttribution(q.from, q.date))}<br></div>` +
    `<blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">` +
    `${content}</blockquote></div>`
  );
}

export function buildQuoteText(q: QuotedMessage): string {
  const text = q.text ?? (q.html ? htmlToPlain(q.html) : "");
  const quoted = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => (line ? `> ${line}` : ">"))
    .join("\n");
  return `${quoteAttribution(q.from, q.date)}\n\n${quoted}`;
}

// ----------------------------------------------------------------------------
// Signature
// ----------------------------------------------------------------------------

// Same markup Gmail's composer inserts, so Gmail (and our reader) recognise it.
export function buildSignatureHtml(signatureHtml: string): string {
  return (
    `<br clear="all"><div><br></div>` +
    `<span class="gmail_signature_prefix">-- </span><br>` +
    `<div dir="ltr" class="gmail_signature" data-smartmail="gmail_signature">${signatureHtml}</div>`
  );
}

// ----------------------------------------------------------------------------
// Full draft body
// ----------------------------------------------------------------------------

export interface DraftBodyInput {
  body: string;
  bodyFormat?: BodyFormat;
  signatureHtml?: string | null;
  quote?: QuotedMessage | null;
}

export interface DraftBody {
  html: string;
  text: string;
  // Local images referenced by the content, to attach inline under their cid.
  images: InlineImageRef[];
}

// Order is fixed: content -> signature -> quote (Gmail's default placement).
// Only the content's images are inlined; signature and quote keep their own.
export function buildDraftBody(input: DraftBodyInput): DraftBody {
  const format = input.bodyFormat ?? "markdown";
  const { html: contentHtml, images } = collectLocalImages(
    format === "html" ? input.body : renderMarkdown(input.body)
  );
  const contentText =
    format === "html"
      ? htmlToPlain(input.body)
      : markdownImagesToPlain(input.body.trim());

  let html = `<div dir="ltr">${contentHtml}`;
  let text = contentText;

  if (input.signatureHtml && input.signatureHtml.trim()) {
    html += buildSignatureHtml(input.signatureHtml);
    text += `\n\n-- \n${htmlToPlain(input.signatureHtml)}`;
  }
  html += `</div>`;

  if (input.quote) {
    html += `<br>${buildQuoteHtml(input.quote)}`;
    text += `\n\n${buildQuoteText(input.quote)}`;
  }

  return { html, text, images };
}

// ----------------------------------------------------------------------------
// MIME
// ----------------------------------------------------------------------------

export interface RawAttachment {
  filename: string;
  contentType?: string; // detected from the extension when omitted
  content: Buffer;
  cid?: string; // only for images embedded in the HTML (referenced as cid:)
}

export interface RawMessageInput {
  from?: string;
  to?: string;
  cc?: string;
  bcc?: string;
  subject: string;
  html?: string;
  text?: string;
  inReplyTo?: string;
  references?: string;
  attachments?: RawAttachment[];
}

// nodemailer would write "X-Attachment-ID"; keep Gmail's exact spelling.
const gmailHeaderCase = (key: string) =>
  key.toLowerCase() === "x-attachment-id" ? "X-Attachment-Id" : key;

function appendFile(parent: MimeNode, a: RawAttachment): void {
  const node = parent.createChild(a.contentType || detectMimeType(a.filename), {
    filename: a.filename,
    normalizeHeaderKey: gmailHeaderCase,
  });
  // Exactly what Gmail's composer writes for a pasted image: disposition
  // "attachment" plus matching Content-ID and X-Attachment-Id.
  node.setHeader("Content-Disposition", "attachment");
  if (a.cid) {
    node.setHeader("Content-ID", `<${a.cid}>`);
    node.setHeader("X-Attachment-Id", a.cid);
  }
  node.setContent(a.content);
}

// Same tree as a message written in Gmail:
//   mixed > related > (alternative(text, html), inline images), files
// Each level only when needed. RFC 2047 headers, Bcc kept (it's a draft).
export async function buildMime(input: RawMessageInput): Promise<Buffer> {
  const attachments = input.attachments ?? [];
  const inline = input.html ? attachments.filter((a) => a.cid) : [];
  const files = attachments.filter((a) => !inline.includes(a));

  const root = new MimeNode(
    files.length
      ? "multipart/mixed"
      : inline.length
        ? "multipart/related"
        : "multipart/alternative",
    { keepBcc: true, textEncoding: "B" }
  );
  const related = !files.length
    ? root
    : inline.length
      ? root.createChild("multipart/related")
      : root;
  const alternative =
    inline.length || files.length
      ? related.createChild("multipart/alternative")
      : root;

  alternative
    .createChild("text/plain; charset=utf-8")
    .setContent(input.text ?? "");
  if (input.html) {
    alternative.createChild("text/html; charset=utf-8").setContent(input.html);
  }
  for (const a of inline) appendFile(related, a);
  for (const a of files) appendFile(root, a);

  const headers: [string, string | undefined][] = [
    ["From", input.from],
    ["To", input.to],
    ["Cc", input.cc],
    ["Bcc", input.bcc],
    ["Subject", input.subject],
    ["In-Reply-To", input.inReplyTo],
    ["References", input.references],
  ];
  for (const [key, value] of headers) if (value) root.setHeader(key, value);
  root.messageId();
  return root.build();
}
