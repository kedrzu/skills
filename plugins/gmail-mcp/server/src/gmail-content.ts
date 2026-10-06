// Reading mail: Gmail payloads -> Markdown with quotes and signatures stripped, plus
// the attachment list. Pure functions only (no Gmail API calls).

import type { gmail_v1 } from "@googleapis/gmail";
import TurndownService from "turndown";
import { strikethrough, tables } from "@joplin/turndown-plugin-gfm";
import EmailReplyParser from "email-reply-parser";
import EmailForwardParser from "email-forward-parser";
import type { MessageAttachment } from "./attachments.js";

// Helper to decode base64url
export function decodeBase64Url(data: string): string {
  const base64 = data.replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(base64, "base64").toString("utf-8");
}

// Get header value
export function getHeader(
  headers: gmail_v1.Schema$MessagePartHeader[] | undefined,
  name: string
): string {
  return (
    headers?.find((h) => h.name?.toLowerCase() === name.toLowerCase())?.value ||
    ""
  );
}

export interface AttachmentInfo extends MessageAttachment {
  inline: boolean;
}

interface ProcessedEmail {
  body: string;
  attachments: AttachmentInfo[];
}

// Singleton Turndown instance for performance
let turndownInstance: TurndownService | null = null;

function getTurndownService(): TurndownService {
  if (!turndownInstance) {
    turndownInstance = createTurndownService();
  }
  return turndownInstance;
}

// Drafts are read back for editing: drop the Gmail signature too (update_draft
// regenerates it), so the caller only sees the content it wrote. Tables stay
// Markdown tables here (not in mail reading, where layout tables would be noise).
let draftTurndownInstance: TurndownService | null = null;

function getDraftTurndownService(): TurndownService {
  if (!draftTurndownInstance) {
    draftTurndownInstance = createTurndownService();
    // Our own Markdown must survive a get_draft -> update_draft round trip.
    draftTurndownInstance.use([tables, strikethrough]);
    // Images stay images (inline ones as ![alt](cid:...)), so update_draft keeps them.
    draftTurndownInstance.addRule("draft-image", {
      filter: "img",
      replacement: (_content, node) => {
        const el = node as Element;
        return `![${el.getAttribute("alt") || ""}](${el.getAttribute("src")})`;
      },
    });
    draftTurndownInstance.addRule("gmail-signature", {
      filter: (node) => {
        const className = (node as Element).getAttribute?.("class") || "";
        return /\bgmail_signature(_prefix)?\b/.test(className);
      },
      replacement: () => "",
    });
  }
  return draftTurndownInstance;
}

function createTurndownService(): TurndownService {
  const turndownInstance = new TurndownService({
      headingStyle: "atx",
      hr: "---",
      bulletListMarker: "-",
      codeBlockStyle: "fenced",
      fence: "```",
      emDelimiter: "*",
      strongDelimiter: "**",
      linkStyle: "inlined",
    });

    // Remove style, script, head, meta, link tags
    turndownInstance.remove(["style", "script", "head", "meta", "link"]);

    // Custom rule: Remove Gmail quote containers
    turndownInstance.addRule("gmail-quote", {
      filter: (node) => {
        if (node.nodeName !== "DIV") return false;
        const className = (node as Element).getAttribute("class") || "";
        return className.includes("gmail_quote");
      },
      replacement: () => "",
    });

    // Custom rule: Remove Outlook-style quoted content (blue border)
    turndownInstance.addRule("outlook-quote", {
      filter: (node) => {
        if (node.nodeName !== "DIV" && node.nodeName !== "BLOCKQUOTE") {
          return false;
        }
        const style = (node as Element).getAttribute("style") || "";
        return (
          style.includes("border-left") &&
          (style.includes("blue") ||
            style.includes("#00f") ||
            style.includes("rgb(0, 0, 255)") ||
            style.includes("#1010ff") ||
            style.includes("border:none"))
        );
      },
      replacement: () => "",
    });

    // Custom rule: Simplify images to [alt-text]
    turndownInstance.addRule("images", {
      filter: "img",
      replacement: (_content, node) => {
        const alt = (node as Element).getAttribute("alt") || "image";
        return `[${alt}]`;
      },
    });
  return turndownInstance;
}

// Convert HTML to Markdown
function convertHtmlToMarkdown(html: string): string {
  if (!html || html.trim() === "") {
    return "";
  }

  try {
    const turndown = getTurndownService();
    let markdown = turndown.turndown(html);

    // Clean up excessive whitespace
    markdown = markdown
      .replace(/\n{3,}/g, "\n\n") // Max 2 consecutive newlines
      .replace(/^\s+|\s+$/g, ""); // Trim

    return markdown;
  } catch (error) {
    // Fallback: strip HTML tags
    console.error("HTML to markdown conversion failed:", error);
    return stripHtmlTags(html);
  }
}

// Fallback HTML tag stripping
function stripHtmlTags(html: string): string {
  return html
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

// Format file size for display
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Process text content: handle forwards and strip replies/signatures
function processTextContent(text: string, subject: string): string {
  if (!text || text.trim() === "") {
    return "";
  }

  try {
    // Check if this is a forwarded email
    const forwardParser = new EmailForwardParser();
    const forwardResult = forwardParser.read(text, subject);

    if (forwardResult.forwarded && forwardResult.email) {
      // Format forwarded email nicely
      const forwardingMessage = forwardResult.message?.trim() || "";
      const originalEmail = forwardResult.email;

      let output = "";

      // Add the forwarding message (what the person wrote when forwarding)
      if (forwardingMessage) {
        output += forwardingMessage + "\n\n";
      }

      // Add formatted original email
      output += "---\n**Forwarded Email**\n";
      if (originalEmail.from?.address) {
        output += `From: ${originalEmail.from.name ? `${originalEmail.from.name} <${originalEmail.from.address}>` : originalEmail.from.address}\n`;
      }
      if (originalEmail.to) {
        // Handle both single object and array cases
        const toArray = Array.isArray(originalEmail.to)
          ? originalEmail.to
          : [originalEmail.to];
        const toAddresses = toArray
          .map((t) => (t.name ? `${t.name} <${t.address}>` : t.address))
          .join(", ");
        output += `To: ${toAddresses}\n`;
      }
      if (originalEmail.date) {
        output += `Date: ${originalEmail.date}\n`;
      }
      if (originalEmail.subject) {
        output += `Subject: ${originalEmail.subject}\n`;
      }
      output += "\n";

      // Process the original email body (strip its quotes/signatures too)
      if (originalEmail.body) {
        const replyParser = new EmailReplyParser();
        const parsed = replyParser.read(originalEmail.body);
        output += parsed.getVisibleText();
      }

      return output.trim();
    }

    // Not a forward - strip quoted replies and signatures
    const replyParser = new EmailReplyParser();
    const parsed = replyParser.read(text);
    return parsed.getVisibleText().trim();
  } catch (error) {
    console.error("Text processing failed:", error);
    return text; // Return original on error
  }
}

// Content-ID of an image embedded in the HTML, null for a regular attachment.
// Neither header decides: Gmail gives every attachment a Content-ID and writes
// "attachment" disposition for pasted images too - only a cid: reference does.
export function inlineCid(
  part: gmail_v1.Schema$MessagePart,
  html: string | null
): string | null {
  const cid = getHeader(part.headers, "Content-ID").replace(/^<|>$/g, "");
  return cid && html?.includes(`cid:${cid}`) ? cid : null;
}

// Extract attachments from message payload
export function extractAttachments(
  payload: gmail_v1.Schema$MessagePart
): AttachmentInfo[] {
  const attachments: AttachmentInfo[] = [];
  const { html } = extractRawBody(payload);

  function scanParts(part: gmail_v1.Schema$MessagePart) {
    // Check if this part is an attachment (has filename and attachmentId)
    if (part.filename && part.filename.length > 0 && part.body?.attachmentId) {
      attachments.push({
        partId: part.partId || part.body.attachmentId,
        gmailId: part.body.attachmentId,
        filename: part.filename,
        mimeType: part.mimeType || "application/octet-stream",
        size: part.body?.size || 0,
        inline: inlineCid(part, html) !== null,
      });
    }

    // Recursively scan nested parts
    if (part.parts) {
      for (const subPart of part.parts) {
        scanParts(subPart);
      }
    }
  }

  scanParts(payload);
  return attachments;
}

// Extract raw body content (HTML preferred, fallback to text)
export interface RawBodyContent {
  html: string | null;
  text: string | null;
}

export function extractRawBody(payload: gmail_v1.Schema$MessagePart): RawBodyContent {
  let html: string | null = null;
  let text: string | null = null;

  function scanParts(part: gmail_v1.Schema$MessagePart) {
    // Direct body data
    if (part.body?.data) {
      const decoded = decodeBase64Url(part.body.data);
      if (part.mimeType === "text/html") {
        html = decoded;
      } else if (part.mimeType === "text/plain") {
        text = decoded;
      }
    }

    // Check nested parts
    if (part.parts) {
      for (const subPart of part.parts) {
        // Skip attachments
        if (subPart.filename && subPart.filename.length > 0) continue;
        scanParts(subPart);
      }
    }
  }

  scanParts(payload);
  return { html, text };
}

// Main email processing function
export function processEmailContent(
  payload: gmail_v1.Schema$MessagePart,
  subject: string,
  rawMode: boolean = false
): ProcessedEmail {
  const attachments = extractAttachments(payload);
  const { html, text } = extractRawBody(payload);

  // If raw mode, return unprocessed content
  if (rawMode) {
    return {
      body: html || text || "",
      attachments,
    };
  }

  let processedBody = "";

  if (html) {
    // Convert HTML to markdown first
    const markdown = convertHtmlToMarkdown(html);
    // Then process for forwards/replies
    processedBody = processTextContent(markdown, subject);
  } else if (text) {
    // Process plain text directly
    processedBody = processTextContent(text, subject);
  }

  return {
    body: processedBody,
    attachments,
  };
}

// Draft content as Markdown, without the quote and signature we regenerate.
export function draftBodyToMarkdown(payload: gmail_v1.Schema$MessagePart): string {
  const { html, text } = extractRawBody(payload);
  if (html) {
    return getDraftTurndownService()
      .turndown(html)
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }
  return (text || "").trim();
}

