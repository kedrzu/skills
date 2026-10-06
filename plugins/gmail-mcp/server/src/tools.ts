// MCP tool definitions and handlers. The schemas of search_threads and update_thread are
// generated from the project's label rules, so the agent sees exactly what is enforced.

import type { gmail_v1 } from "@googleapis/gmail";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { Readable } from "stream";
import { NotConfigured, type AccountRegistry } from "./accounts.js";
import { findAttachment, isPartId, savedFileName } from "./attachments.js";
import {
  buildDraftBody,
  buildMime,
  buildReferences,
  replySubject,
  type BodyFormat,
  type QuotedMessage,
  type RawAttachment,
} from "./compose.js";
import { resolvePath } from "./config.js";
import { assertTotalSize, loadLocalFile, type FileAccess } from "./files.js";
import {
  draftBodyToMarkdown,
  extractAttachments,
  extractRawBody,
  formatFileSize,
  getHeader,
  inlineCid,
  processEmailContent,
} from "./gmail-content.js";
import {
  describeRules,
  planThreadChange,
  protectedLabels,
  RuleViolation,
  viewQuery,
  type LabelRulesConfig,
} from "./label-rules.js";

const SYSTEM_LABELS = [
  "INBOX",
  "UNREAD",
  "STARRED",
  "IMPORTANT",
  "SENT",
  "DRAFT",
  "SPAM",
  "TRASH",
  "CATEGORY_PERSONAL",
  "CATEGORY_SOCIAL",
  "CATEGORY_PROMOTIONS",
  "CATEGORY_UPDATES",
  "CATEGORY_FORUMS",
];

const account = { type: "string", description: "Email account (from list_accounts)" };

const FILES_NOTE =
  "Paths are absolute or relative to the project directory, and must live in the project or in a directory the project config allows " +
  "(files.roots; files saved by save_attachment are always allowed). .env files, OAuth client files and tokens are refused.";

export function toolDefinitions(rules: LabelRulesConfig | undefined): Tool[] {
  const views = Object.entries(rules?.views ?? {});
  const groups = Object.entries(rules?.groups ?? {});

  const searchProps: Record<string, object> = {
    account,
    query: {
      type: "string",
      description:
        "Gmail search query (e.g. 'is:unread', 'from:example@gmail.com', 'subject:meeting', 'older_than:1y'). " +
        (views.length ? "With 'view' it narrows the view (ANDed); without 'view' it runs verbatim across all mail." : "Runs verbatim across all mail."),
    },
    maxResults: { type: "number", description: "Maximum number of threads to return (default: 20)" },
  };
  if (views.length) {
    searchProps.view = {
      type: "string",
      enum: views.map(([v]) => v),
      description:
        "Optional named view defined by this project: " +
        views.map(([v, q]) => `'${v}' = ${q}`).join("; ") +
        ". Omit it to search all mail (inbox, archived, processed) with the raw 'query'.",
    };
  }

  const updateProps: Record<string, object> = {
    account,
    threadId: { type: "string", description: "Thread ID to update" },
    addLabels: {
      type: "array",
      items: { type: "string" },
      description: "Label names to add (user labels must exist - create_label makes new ones; system: STARRED, IMPORTANT, UNREAD, INBOX, CATEGORY_*).",
    },
    removeLabels: {
      type: "array",
      items: { type: "string" },
      description: "Label names to remove (e.g. 'INBOX' archives, 'UNREAD' marks read).",
    },
  };
  if (groups.length) {
    updateProps.set = {
      type: "object",
      description:
        "Set exclusive label groups: { <group>: <label> } applies the label and removes the rest of its group; { <group>: null } clears the group. Missing labels are created.",
      properties: Object.fromEntries(
        groups.map(([g, labels]) => [g, { type: ["string", "null"], enum: [...labels, null], description: `One of: ${labels.join(", ")}` }])
      ),
      additionalProperties: false,
    };
  }

  return [
    {
      name: "list_accounts",
      description:
        "List the Gmail accounts this project may use, plus any setup problem (missing config, undecryptable client file, revoked token). Every other tool takes one of these as 'account'.",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "search_threads",
      description:
        "Search email threads with Gmail search syntax. Filtering runs per message, then results are de-duplicated into threads, newest matching message first - " +
        "so a new reply resurfaces its thread even when older messages carry labels the query excludes. " +
        (views.length ? "Pass 'view' for one of this project's named views. " : "") +
        "Returns ids, subject, sender, date and snippet; read a thread with get_thread.",
      inputSchema: { type: "object", properties: searchProps, required: ["account"] },
    },
    {
      name: "get_message",
      description:
        "Get one message: body as Markdown with quoted replies and signatures stripped (rawBody for the original), its label NAMES, and attachments with stable attachmentIds for save_attachment.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          messageId: { type: "string", description: "The ID of the message to retrieve" },
          rawBody: { type: "boolean", description: "Return raw HTML/text without Markdown conversion or quote stripping (default: false)" },
        },
        required: ["account", "messageId"],
      },
    },
    {
      name: "get_thread",
      description:
        "Get all messages of a thread: bodies as Markdown with quoted replies and signatures stripped (rawBody for the originals), each message's label NAMES, and attachments.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          threadId: { type: "string", description: "The ID of the thread to retrieve" },
          rawBody: { type: "boolean", description: "Return raw HTML/text without Markdown conversion or quote stripping (default: false)" },
        },
        required: ["account", "threadId"],
      },
    },
    {
      name: "create_draft",
      description:
        "Create a draft (never sends - the user sends it from Gmail). Write the body in Markdown: the server renders Gmail-looking HTML plus a plain-text part, " +
        "appends the account's Gmail signature and, for replies (threadId), a Gmail-style quote of the last message. " +
        "With threadId, 'to', 'subject', In-Reply-To and References are derived from the thread when omitted. " +
        "Images in the body as ![alt](path) are embedded inline; other files go in 'attachments'. " +
        FILES_NOTE +
        " Before drafting a reply, check list_drafts(threadId) and fix an existing draft with update_draft instead of creating a second one.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          to: { type: "string", description: "Recipients, comma-separated. Optional with threadId (defaults to Reply-To/From of the last message)" },
          subject: { type: "string", description: "Subject. Optional with threadId (defaults to 'Re: <thread subject>')" },
          body: {
            type: "string",
            description:
              "Body in Markdown (GFM: headings, lists, tables, **bold**, links; single newline = line break). " +
              "Images: ![alt](/abs/path.png) or ![alt](<path with spaces.png>) - local files are embedded inline, http(s) URLs stay links. " +
              "Do not add a signature - it is appended automatically",
          },
          bodyFormat: { type: "string", enum: ["markdown", "html"], description: "Format of body (default: markdown). Use html only for ready-made HTML" },
          cc: { type: "string", description: "CC recipients, comma-separated" },
          bcc: { type: "string", description: "BCC recipients, comma-separated" },
          threadId: { type: "string", description: "Thread ID to reply to (optional)" },
          inReplyTo: { type: "string", description: "Message-ID to reply to (optional; derived from threadId when omitted)" },
          signature: { type: "boolean", description: "Append the account's Gmail signature (default: true)" },
          quote: { type: "boolean", description: "Quote the last thread message below the reply (default: true when threadId is set)" },
          attachments: { type: "array", items: { type: "string" }, description: "Files to attach (see paths above). Max 25 MB in total" },
        },
        required: ["account", "body"],
      },
    },
    {
      name: "list_drafts",
      description: "List drafts (newest first). Use threadId to find an existing reply draft in a thread",
      inputSchema: {
        type: "object",
        properties: {
          account,
          query: { type: "string", description: "Gmail search query to narrow drafts (e.g. 'to:jan@x.pl', 'subject:invoice')" },
          threadId: { type: "string", description: "Only drafts in this thread" },
          maxResults: { type: "number", description: "Maximum drafts to return (default: 20)" },
        },
        required: ["account"],
      },
    },
    {
      name: "get_draft",
      description: "Get a draft: headers and the body as Markdown (without the signature and quoted reply, which update_draft regenerates)",
      inputSchema: {
        type: "object",
        properties: { account, draftId: { type: "string", description: "Draft ID (from create_draft or list_drafts)" } },
        required: ["account", "draftId"],
      },
    },
    {
      name: "update_draft",
      description:
        "Edit a draft in place (same draftId; never sends). Only the given fields change. " +
        "A new body (Markdown) replaces the whole content; signature and reply quote are regenerated. " +
        "Inline images: new local ![alt](path) are embedded; existing ones appear in get_draft as ![alt](cid:...) - keep that reference to keep the image. " +
        "Attachments survive every update; 'attachments' adds files, 'removeAttachments' drops them by filename. Without body the content stays untouched. " +
        FILES_NOTE,
      inputSchema: {
        type: "object",
        properties: {
          account,
          draftId: { type: "string", description: "Draft ID (from create_draft or list_drafts)" },
          to: { type: "string", description: "New recipients, comma-separated" },
          cc: { type: "string", description: "New CC recipients, comma-separated (empty string clears)" },
          bcc: { type: "string", description: "New BCC recipients, comma-separated (empty string clears)" },
          subject: { type: "string", description: "New subject" },
          body: { type: "string", description: "New full body in Markdown (without signature/quote - they are appended automatically)" },
          bodyFormat: { type: "string", enum: ["markdown", "html"], description: "Format of body (default: markdown)" },
          signature: { type: "boolean", description: "Append the account's Gmail signature when body is given (default: true)" },
          quote: { type: "boolean", description: "Quote the last thread message when body is given (default: true for reply drafts)" },
          attachments: { type: "array", items: { type: "string" }, description: "Files to ADD (existing attachments stay)" },
          removeAttachments: { type: "array", items: { type: "string" }, description: "Filenames of existing attachments to remove (as listed by get_draft)" },
        },
        required: ["account", "draftId"],
      },
    },
    {
      name: "discard_draft",
      description:
        "Discard a draft (Gmail's 'Discard draft'): it moves to Trash, recoverable there for 30 days - never a permanent delete. Sent or received messages are refused",
      inputSchema: {
        type: "object",
        properties: { account, draftId: { type: "string", description: "Draft ID (from create_draft or list_drafts)" } },
        required: ["account", "draftId"],
      },
    },
    {
      name: "list_labels",
      description: "List all labels of an account",
      inputSchema: { type: "object", properties: { account }, required: ["account"] },
    },
    {
      name: "update_thread",
      description:
        "Change a thread's labels in one atomic call. Takes label NAMES, not ids. Archive = remove INBOX; mark read = remove UNREAD; star = add STARRED. " +
        (describeRules(rules) || "This project defines no label rules."),
      inputSchema: { type: "object", properties: updateProps, required: ["account", "threadId"] },
    },
    {
      name: "create_label",
      description:
        "Create a user label (idempotent - an existing one returns its id). Nested names like 'Work/Invoices' create the parent hierarchy. Does not apply the label (use update_thread).",
      inputSchema: {
        type: "object",
        properties: { account, name: { type: "string", description: "Label name, e.g. 'Work/Invoices'" } },
        required: ["account", "name"],
      },
    },
    {
      name: "cleanup_labels",
      description:
        "Housekeeping: delete user labels whose name starts with 'prefix'. Mail is never deleted - Gmail just detaches the label. By default only empty labels go; " +
        "onlyEmpty:false also deletes labels still in use. Run with dryRun:true first. System labels and labels this project's rules use are always kept.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          prefix: { type: "string", description: "Label name prefix, e.g. 'Old/'. Case-insensitive, must not be empty" },
          onlyEmpty: { type: "boolean", description: "Default true: skip labels that still carry messages" },
          dryRun: { type: "boolean", description: "Report what would be deleted without deleting" },
        },
        required: ["account", "prefix"],
      },
    },
    {
      name: "save_attachment",
      description:
        "Download an attachment to disk and return its path (never base64 - the file does not pass through the conversation). Get the attachmentId from get_message or get_thread. " +
        "The returned path can be attached to a draft as is.",
      inputSchema: {
        type: "object",
        properties: {
          account,
          messageId: { type: "string", description: "Message ID containing the attachment" },
          attachmentId: { type: "string", description: 'attachmentId from get_message (a stable MIME part id such as "2" or "1.3")' },
        },
        required: ["account", "messageId", "attachmentId"],
      },
    },
  ];
}

interface LabelInfo {
  id: string;
  name: string;
  type: string;
}

function jsonResult(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

// A list of strings; clients with a stale tool schema send it JSON-encoded or as a single value.
function stringList(value: unknown, name: string): string[] {
  if (value === undefined || value === null) return [];
  let list = value;
  if (typeof list === "string") {
    const s = list.trim();
    try {
      list = s.startsWith("[") ? JSON.parse(s) : [s];
    } catch {
      list = [s];
    }
  }
  if (!Array.isArray(list)) throw new Error(`'${name}' must be an array of strings`);
  return list.map(String);
}

function fileSummary(a: RawAttachment) {
  return { filename: a.filename, mimeType: a.contentType, size: formatFileSize(a.content.length) };
}

// The whole RFC 822 message goes as a media upload, so multi-MB attachments
// don't hit the size limit of a plain JSON request.
function draftMedia(message: Buffer) {
  return { mimeType: "message/rfc822", body: Readable.from([message]) };
}

interface ReplyContext {
  to: string;
  subject: string;
  inReplyTo: string;
  references: string;
  quote: QuotedMessage;
}

const SIGNATURE_TTL_MS = 10 * 60 * 1000;

export class GmailTools {
  private labelCache = new Map<string, LabelInfo[]>();
  private signatureCache = new Map<string, { html: string; fetchedAt: number }>();

  constructor(readonly registry: AccountRegistry) {}

  get rules(): LabelRulesConfig | undefined {
    return this.registry.loaded?.config.labels;
  }

  attachmentsDir(): string {
    const configured = this.registry.loaded?.config.files?.attachmentsDir;
    return configured
      ? resolvePath(this.registry.projectDir, configured)
      : path.join(os.tmpdir(), "gmail-mcp", "attachments");
  }

  fileAccess(): FileAccess {
    const projectDir = this.registry.projectDir;
    const roots = (this.registry.loaded?.config.files?.roots ?? []).map((r) => resolvePath(projectDir, r));
    return {
      baseDir: projectDir,
      roots: [projectDir, ...roots, this.attachmentsDir()],
      denied: this.registry.deniedFiles(),
    };
  }

  private gmail(email: string): gmail_v1.Gmail {
    return this.registry.get(email).gmail;
  }

  private async labels(email: string): Promise<LabelInfo[]> {
    const cached = this.labelCache.get(email);
    if (cached) return cached;
    const response = await this.gmail(email).users.labels.list({ userId: "me" });
    const labels = (response.data.labels || []).map((l) => ({ id: l.id || "", name: l.name || "", type: l.type || "" }));
    this.labelCache.set(email, labels);
    return labels;
  }

  // Label name -> id. System labels pass through; user labels must exist, so a typo
  // errors out instead of silently spawning a junk label.
  private async labelId(email: string, name: string): Promise<string> {
    if (SYSTEM_LABELS.includes(name.toUpperCase())) return name.toUpperCase();
    const labels = await this.labels(email);
    const label = labels.find((l) => l.name.toLowerCase() === name.toLowerCase());
    if (label) return label.id;
    throw new Error(
      `Label "${name}" not found (create it with create_label). Available labels: ${labels
        .filter((l) => l.type === "user")
        .map((l) => l.name)
        .join(", ")}`
    );
  }

  // Find a user label by name (case-insensitive); create it if missing. Gmail
  // auto-creates the parent hierarchy for nested names.
  private async ensureLabel(email: string, name: string): Promise<string> {
    const labels = await this.labels(email);
    const existing = labels.find((l) => l.name.toLowerCase() === name.toLowerCase());
    if (existing) return existing.id;
    const created = await this.gmail(email).users.labels.create({
      userId: "me",
      requestBody: { name, labelListVisibility: "labelShow", messageListVisibility: "show" },
    });
    const info = { id: created.data.id || "", name: created.data.name || name, type: created.data.type || "user" };
    labels.push(info);
    return info.id;
  }

  // Gmail signature of the default send-as address, cached with a TTL so an edited
  // signature shows up without restarting the server.
  private async signature(email: string): Promise<string> {
    const cached = this.signatureCache.get(email);
    if (cached && Date.now() - cached.fetchedAt < SIGNATURE_TTL_MS) return cached.html;
    let html = "";
    try {
      const response = await this.gmail(email).users.settings.sendAs.list({ userId: "me" });
      const sendAs = response.data.sendAs || [];
      const entry = sendAs.find((a) => a.isDefault) || sendAs.find((a) => a.sendAsEmail?.toLowerCase() === email.toLowerCase());
      html = entry?.signature || "";
    } catch (error) {
      // A missing signature must never block a draft.
      console.error(`Signature lookup failed for ${email}:`, error);
    }
    this.signatureCache.set(email, { html, fetchedAt: Date.now() });
    return html;
  }

  // Reply headers and quote from the thread's last real (non-draft) message.
  private async replyContext(email: string, threadId: string): Promise<ReplyContext | null> {
    const thread = await this.gmail(email).users.threads.get({ userId: "me", id: threadId, format: "full" });
    const messages = (thread.data.messages || []).filter((m) => !(m.labelIds || []).includes("DRAFT"));
    const last = messages[messages.length - 1];
    if (!last?.payload) return null;
    const headers = last.payload.headers;
    const messageId = getHeader(headers, "Message-ID");
    // Following up on my own message goes to its recipients, not back to me.
    const fromMe = (last.labelIds || []).includes("SENT");
    const to = fromMe ? getHeader(headers, "To") : getHeader(headers, "Reply-To") || getHeader(headers, "From");
    const { html, text } = extractRawBody(last.payload);
    return {
      to,
      subject: replySubject(getHeader(headers, "Subject")),
      inReplyTo: messageId,
      references: buildReferences(getHeader(headers, "References"), messageId),
      quote: { from: getHeader(headers, "From"), date: getHeader(headers, "Date"), html, text },
    };
  }

  // Draft attachments re-read as bytes, so rewriting the draft doesn't drop them.
  private async draftAttachments(gmail: gmail_v1.Gmail, messageId: string, payload: gmail_v1.Schema$MessagePart): Promise<RawAttachment[]> {
    const result: RawAttachment[] = [];
    const { html } = extractRawBody(payload);
    const scan = async (part: gmail_v1.Schema$MessagePart) => {
      if (part.filename && part.body?.attachmentId) {
        const data = await gmail.users.messages.attachments.get({ userId: "me", messageId, id: part.body.attachmentId });
        result.push({
          filename: part.filename,
          contentType: part.mimeType || "application/octet-stream",
          content: Buffer.from(data.data.data || "", "base64url"),
          cid: inlineCid(part, html) ?? undefined,
        });
      }
      for (const sub of part.parts || []) await scan(sub);
    };
    await scan(payload);
    return result;
  }

  private async localFiles(paths: unknown): Promise<RawAttachment[]> {
    const access = this.fileAccess();
    return Promise.all(stringList(paths, "attachments").map((p) => loadLocalFile(p, access)));
  }

  private async inlineImages(images: { path: string; cid: string }[]): Promise<RawAttachment[]> {
    const access = this.fileAccess();
    return Promise.all(images.map(async (img) => ({ ...(await loadLocalFile(img.path, access)), cid: img.cid })));
  }

  private async labelNames(email: string): Promise<Map<string, string>> {
    return new Map((await this.labels(email)).map((l) => [l.id, l.name]));
  }

  async call(name: string, args: Record<string, any> = {}) {
    try {
      this.registry.refreshIfChanged();
      return await this.dispatch(name, args);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const hint = error instanceof NotConfigured || error instanceof RuleViolation ? "" : this.authHint(message);
      return { content: [{ type: "text" as const, text: `Error: ${message}${hint}` }], isError: true };
    }
  }

  private authHint(message: string): string {
    return /invalid_grant|invalid_client|unauthorized_client/i.test(message)
      ? " - the sign-in for this account is no longer valid (revoked, expired, or the OAuth client changed). Run /gmail-mcp:setup to sign in again."
      : "";
  }

  private async dispatch(name: string, args: Record<string, any>) {
    switch (name) {
      case "list_accounts": {
        this.registry.reload();
        if (!this.registry.loaded) return jsonResult({ accounts: [], setup: this.registry.notConfiguredMessage() });
        const accounts = [...this.registry.accounts.values()].map((a) => ({ email: a.email, client: a.client.name }));
        return jsonResult({
          accounts,
          notAllowedHere: this.registry.hidden.length ? this.registry.hidden : undefined,
          problems: this.registry.problems.length ? this.registry.problems : undefined,
          setup: accounts.length ? undefined : "No account is signed in for this project - run /gmail-mcp:setup",
        });
      }

      case "search_threads": {
        const gmail = this.gmail(args.account);
        const maxResults = args.maxResults || 20;
        const q = [args.query as string | undefined, viewQuery(this.rules, args.view)].filter(Boolean).join(" ");
        if (!q) throw new Error("Pass a 'query'" + (Object.keys(this.rules?.views ?? {}).length ? " or a 'view'" : ""));

        // Filter per message (Gmail thread-level label negation is unreliable - a whole
        // conversation disappears from -label:X once any message has X, so new replies to
        // processed threads would never resurface). messages.list is newest first, so
        // first-seen order sorts threads by their most recent matching message.
        const threadIds: string[] = [];
        const seen = new Set<string>();
        let pageToken: string | undefined;
        for (let page = 0; page < 5 && threadIds.length < maxResults; page++) {
          const res = await gmail.users.messages.list({ userId: "me", q, maxResults: 100, pageToken });
          for (const m of res.data.messages || []) {
            if (m.threadId && !seen.has(m.threadId)) {
              seen.add(m.threadId);
              threadIds.push(m.threadId);
              if (threadIds.length >= maxResults) break;
            }
          }
          pageToken = res.data.nextPageToken || undefined;
          if (!pageToken) break;
        }

        const threads = await Promise.all(
          threadIds.map(async (id) => {
            const t = await gmail.users.threads.get({
              userId: "me",
              id,
              format: "metadata",
              metadataHeaders: ["Subject", "From", "Date"],
            });
            const first = t.data.messages?.[0];
            const headers = first?.payload?.headers;
            return {
              id,
              snippet: first?.snippet,
              subject: getHeader(headers, "Subject"),
              from: getHeader(headers, "From"),
              date: getHeader(headers, "Date"),
              messageCount: t.data.messages?.length,
            };
          })
        );
        return jsonResult({ threads, count: threads.length });
      }

      case "get_message": {
        const gmail = this.gmail(args.account);
        const message = await gmail.users.messages.get({ userId: "me", id: args.messageId, format: "full" });
        const headers = message.data.payload?.headers;
        const subject = getHeader(headers, "Subject");
        const { body, attachments } = processEmailContent(message.data.payload!, subject, args.rawBody === true);
        const names = await this.labelNames(args.account);
        return jsonResult({
          id: message.data.id,
          threadId: message.data.threadId,
          messageId: getHeader(headers, "Message-ID"),
          subject,
          from: getHeader(headers, "From"),
          to: getHeader(headers, "To"),
          cc: getHeader(headers, "Cc"),
          date: getHeader(headers, "Date"),
          labels: (message.data.labelIds || []).map((id) => names.get(id) || id),
          snippet: message.data.snippet,
          body,
          attachments: attachments.length
            ? attachments.map((a) => ({
                attachmentId: a.partId,
                filename: a.filename,
                mimeType: a.mimeType,
                size: formatFileSize(a.size),
                sizeBytes: a.size,
              }))
            : undefined,
        });
      }

      case "get_thread": {
        const gmail = this.gmail(args.account);
        const thread = await gmail.users.threads.get({ userId: "me", id: args.threadId, format: "full" });
        const names = await this.labelNames(args.account);
        const messages = (thread.data.messages || []).map((msg) => {
          const headers = msg.payload?.headers;
          const subject = getHeader(headers, "Subject");
          const { body, attachments } = processEmailContent(msg.payload!, subject, args.rawBody === true);
          return {
            id: msg.id,
            messageId: getHeader(headers, "Message-ID"),
            labels: (msg.labelIds || []).map((id) => names.get(id) || id),
            from: getHeader(headers, "From"),
            to: getHeader(headers, "To"),
            cc: getHeader(headers, "Cc"),
            date: getHeader(headers, "Date"),
            subject,
            snippet: msg.snippet,
            body,
            attachments: attachments.length
              ? attachments.map((a) => ({
                  attachmentId: a.partId,
                  filename: a.filename,
                  mimeType: a.mimeType,
                  size: formatFileSize(a.size),
                  sizeBytes: a.size,
                }))
              : undefined,
          };
        });
        return jsonResult({ threadId: thread.data.id, messageCount: messages.length, messages });
      }

      case "create_draft": {
        const email = args.account as string;
        const gmail = this.gmail(email);
        const threadId = args.threadId as string | undefined;
        const reply = threadId ? await this.replyContext(email, threadId) : null;

        const to = (args.to as string) || reply?.to;
        if (!to) throw new Error("'to' is required (or pass threadId to reply)");
        const subject = (args.subject as string) ?? reply?.subject ?? "";
        const inReplyTo = (args.inReplyTo as string) || reply?.inReplyTo;
        const references = reply ? buildReferences(reply.references, inReplyTo || "") : inReplyTo;

        const wantQuote = (args.quote as boolean | undefined) ?? true;
        const { html, text, images } = buildDraftBody({
          body: args.body as string,
          bodyFormat: args.bodyFormat as BodyFormat | undefined,
          signatureHtml: args.signature === false ? null : await this.signature(email),
          quote: wantQuote && reply ? reply.quote : null,
        });

        // All files are read before any API call: a bad path means no draft at all.
        const inline = await this.inlineImages(images);
        const files = await this.localFiles(args.attachments);
        assertTotalSize([...inline, ...files]);

        const message = await buildMime({
          to,
          cc: args.cc,
          bcc: args.bcc,
          subject,
          html,
          text,
          inReplyTo,
          references,
          attachments: [...inline, ...files],
        });
        const draft = await gmail.users.drafts.create({
          userId: "me",
          requestBody: { message: { threadId } },
          media: draftMedia(message),
        });
        return jsonResult({
          status: "Draft created",
          draftId: draft.data.id,
          messageId: draft.data.message?.id,
          threadId: draft.data.message?.threadId,
          to,
          subject,
          inlineImages: inline.length ? inline.map(fileSummary) : undefined,
          attachments: files.length ? files.map(fileSummary) : undefined,
        });
      }

      case "list_drafts": {
        const gmail = this.gmail(args.account);
        const threadId = args.threadId as string | undefined;
        const maxResults = args.maxResults || 20;
        const response = await gmail.users.drafts.list({
          userId: "me",
          q: args.query,
          // Thread filtering happens client-side, so look further back.
          maxResults: threadId ? 100 : maxResults,
        });
        const drafts = (response.data.drafts || []).filter((d) => !threadId || d.message?.threadId === threadId).slice(0, maxResults);
        const items = await Promise.all(
          drafts.map(async (d) => {
            const full = await gmail.users.drafts.get({ userId: "me", id: d.id!, format: "metadata" });
            const msg = full.data.message;
            const headers = msg?.payload?.headers;
            return {
              draftId: d.id,
              messageId: msg?.id,
              threadId: msg?.threadId,
              to: getHeader(headers, "To"),
              cc: getHeader(headers, "Cc") || undefined,
              subject: getHeader(headers, "Subject"),
              date: getHeader(headers, "Date"),
              isReply: !!getHeader(headers, "In-Reply-To"),
              snippet: msg?.snippet,
            };
          })
        );
        return jsonResult({ count: items.length, drafts: items });
      }

      case "get_draft": {
        const gmail = this.gmail(args.account);
        const draft = await gmail.users.drafts.get({ userId: "me", id: args.draftId, format: "full" });
        const msg = draft.data.message;
        if (!msg?.payload) throw new Error(`Draft ${args.draftId} has no message`);
        const headers = msg.payload.headers;
        const attachments = extractAttachments(msg.payload);
        return jsonResult({
          draftId: draft.data.id,
          messageId: msg.id,
          threadId: msg.threadId,
          from: getHeader(headers, "From"),
          to: getHeader(headers, "To"),
          cc: getHeader(headers, "Cc") || undefined,
          bcc: getHeader(headers, "Bcc") || undefined,
          subject: getHeader(headers, "Subject"),
          inReplyTo: getHeader(headers, "In-Reply-To") || undefined,
          body: draftBodyToMarkdown(msg.payload),
          attachments: attachments.length
            ? attachments.map((a) => ({
                filename: a.filename,
                mimeType: a.mimeType,
                size: formatFileSize(a.size),
                inline: a.inline || undefined,
              }))
            : undefined,
        });
      }

      case "update_draft": {
        const email = args.account as string;
        const gmail = this.gmail(email);
        const draftId = args.draftId as string;
        const draft = await gmail.users.drafts.get({ userId: "me", id: draftId, format: "full" });
        const msg = draft.data.message;
        if (!msg?.payload || !msg.id) throw new Error(`Draft ${draftId} has no message`);
        const headers = msg.payload.headers;

        // Unspecified fields keep the draft's current values.
        const pick = (key: string, header: string): string => (args[key] !== undefined ? (args[key] as string) : getHeader(headers, header));
        const to = pick("to", "To");
        const cc = pick("cc", "Cc");
        const bcc = pick("bcc", "Bcc");
        const subject = pick("subject", "Subject");
        let inReplyTo = getHeader(headers, "In-Reply-To");
        let references = getHeader(headers, "References");

        const existing = await this.draftAttachments(gmail, msg.id, msg.payload);
        let html: string | undefined;
        let text: string | undefined;
        let inline: RawAttachment[];
        let files = existing.filter((a) => !a.cid);

        const toRemove = stringList(args.removeAttachments, "removeAttachments");
        const missing = toRemove.filter((n) => !files.some((a) => a.filename === n));
        if (missing.length) {
          throw new Error(
            `No attachment named ${missing.map((n) => `'${n}'`).join(", ")} (draft has: ${files.map((a) => a.filename).join(", ") || "none"})`
          );
        }
        files = files.filter((a) => !toRemove.includes(a.filename));
        files.push(...(await this.localFiles(args.attachments)));

        if (args.body !== undefined) {
          // New content: re-render and re-attach signature + quote of the latest message.
          const reply = msg.threadId ? await this.replyContext(email, msg.threadId) : null;
          if (reply) {
            inReplyTo = reply.inReplyTo;
            references = reply.references;
          }
          const wantQuote = (args.quote as boolean | undefined) ?? true;
          const rendered = buildDraftBody({
            body: args.body as string,
            bodyFormat: args.bodyFormat as BodyFormat | undefined,
            signatureHtml: args.signature === false ? null : await this.signature(email),
            quote: wantQuote && reply ? reply.quote : null,
          });
          ({ html, text } = rendered);
          // Old inline images survive only while the new body still points at their cid.
          const kept = existing.filter((a) => a.cid && rendered.html.includes(`cid:${a.cid}`));
          const fresh = await this.inlineImages(rendered.images.filter((img) => !kept.some((a) => a.cid === img.cid)));
          inline = [...kept, ...fresh];
        } else {
          const body = extractRawBody(msg.payload);
          html = body.html ?? undefined;
          text = body.text ?? undefined;
          inline = existing.filter((a) => a.cid);
        }
        assertTotalSize([...inline, ...files]);

        const message = await buildMime({
          from: getHeader(headers, "From"),
          to,
          cc,
          bcc,
          subject,
          html,
          text,
          inReplyTo,
          references,
          attachments: [...inline, ...files],
        });
        const updated = await gmail.users.drafts.update({
          userId: "me",
          id: draftId,
          requestBody: { id: draftId, message: { threadId: msg.threadId } },
          media: draftMedia(message),
        });
        const changed = ["to", "cc", "bcc", "subject", "body", "attachments", "removeAttachments"].filter((k) => args[k] !== undefined);
        return jsonResult({
          status: "Draft updated",
          draftId: updated.data.id,
          messageId: updated.data.message?.id,
          threadId: updated.data.message?.threadId,
          changed,
          inlineImages: inline.length ? inline.map(fileSummary) : undefined,
          attachments: files.length ? files.map(fileSummary) : undefined,
        });
      }

      case "discard_draft": {
        const gmail = this.gmail(args.account);
        const draftId = args.draftId as string;
        const draft = await gmail.users.drafts.get({ userId: "me", id: draftId, format: "metadata" });
        const msg = draft.data.message;
        if (!msg?.id || !(msg.labelIds || []).includes("DRAFT")) {
          throw new Error(`${draftId} is not a draft - refusing to discard`);
        }
        // Trash, not drafts.delete: the latter is permanent and skips the Trash.
        await gmail.users.messages.trash({ userId: "me", id: msg.id });
        return jsonResult({
          status: "Draft discarded (moved to Trash, recoverable for 30 days)",
          draftId,
          messageId: msg.id,
          threadId: msg.threadId,
          subject: getHeader(msg.payload?.headers, "Subject"),
        });
      }

      case "list_labels": {
        const response = await this.gmail(args.account).users.labels.list({ userId: "me" });
        const labels = (response.data.labels || []).map((l) => ({ id: l.id, name: l.name, type: l.type }));
        this.labelCache.set(args.account, labels.map((l) => ({ id: l.id || "", name: l.name || "", type: l.type || "" })));
        return jsonResult({ labels });
      }

      case "update_thread": {
        const email = args.account as string;
        const gmail = this.gmail(email);
        const threadId = args.threadId as string;
        const add = stringList(args.addLabels, "addLabels");
        const remove = stringList(args.removeLabels, "removeLabels");
        let set = args.set ?? {};
        if (typeof set === "string") set = JSON.parse(set);
        if (!add.length && !remove.length && !Object.keys(set).length) return jsonResult({ status: "Nothing to change" });

        // The rules reason over the thread's resulting state, so read its labels first.
        let current: string[] = [];
        if (this.rules) {
          const meta = await gmail.users.threads.get({ userId: "me", id: threadId, format: "minimal" });
          const names = await this.labelNames(email);
          const all = new Set<string>();
          for (const m of meta.data.messages || []) for (const id of m.labelIds || []) all.add(names.get(id) || id);
          current = [...all];
        }
        const plan = planThreadChange(this.rules, { add, remove, set }, current);

        const addIds: string[] = [];
        for (const label of plan.add) {
          addIds.push(plan.setLabels.includes(label) ? await this.ensureLabel(email, label) : await this.labelId(email, label));
        }
        const removeIds = await Promise.all(plan.remove.map((l) => this.labelId(email, l)));

        await gmail.users.threads.modify({
          userId: "me",
          id: threadId,
          requestBody: {
            addLabelIds: addIds.length ? addIds : undefined,
            removeLabelIds: removeIds.length ? removeIds : undefined,
          },
        });
        return jsonResult({ status: "Thread updated", threadId, changes: plan.summary, added: plan.add, removed: plan.remove });
      }

      case "create_label": {
        const label = (args.name as string)?.trim();
        if (!label) throw new Error("Label name is required");
        const existing = (await this.labels(args.account)).find((l) => l.name.toLowerCase() === label.toLowerCase());
        const id = await this.ensureLabel(args.account, label);
        return jsonResult({ id, name: label, created: !existing });
      }

      case "cleanup_labels": {
        const email = args.account as string;
        const gmail = this.gmail(email);
        const prefix = ((args.prefix as string) || "").trim();
        const onlyEmpty = args.onlyEmpty !== false;
        const dryRun = args.dryRun === true;
        // A sweep with no prefix would mean "delete every user label", which nobody means.
        if (!prefix) throw new Error("'prefix' is required and must not be empty - it scopes which labels get deleted");

        const kept = protectedLabels(this.rules).map((l) => l.toLowerCase());
        const labels = (await this.labels(email)).filter(
          (l) => l.type === "user" && !kept.includes(l.name.toLowerCase()) && l.name.toLowerCase().startsWith(prefix.toLowerCase())
        );
        const deleted: string[] = [];
        const skipped: { name: string; messagesTotal: number }[] = [];
        for (const label of labels) {
          const info = await gmail.users.labels.get({ userId: "me", id: label.id });
          const messagesTotal = info.data.messagesTotal || 0;
          if (onlyEmpty && messagesTotal > 0) {
            skipped.push({ name: label.name, messagesTotal });
            continue;
          }
          if (!dryRun) {
            await gmail.users.labels.delete({ userId: "me", id: label.id });
            const cached = this.labelCache.get(email);
            const idx = cached?.findIndex((l) => l.id === label.id) ?? -1;
            if (idx >= 0) cached!.splice(idx, 1);
          }
          deleted.push(label.name);
        }
        return jsonResult({ prefix, onlyEmpty, dryRun, deleted, count: deleted.length, skipped });
      }

      case "save_attachment": {
        const gmail = this.gmail(args.account);
        const messageId = args.messageId as string;
        const ref = args.attachmentId as string;
        const message = await gmail.users.messages.get({ userId: "me", id: messageId, format: "full" });
        const attachments = extractAttachments(message.data.payload!);

        let target = findAttachment(attachments, ref);
        const attachment = await gmail.users.messages.attachments.get({ userId: "me", messageId, id: target?.gmailId ?? ref });
        // An old-style Gmail id that changed since: recognise the part by size.
        if (!target && !isPartId(ref)) target = findAttachment(attachments, ref, attachment.data.size ?? undefined);
        if (!target) {
          throw new Error(
            `Attachment '${ref}' not found in message ${messageId}; available: ` +
              (attachments.map((a) => `${a.partId} (${a.filename})`).join(", ") || "none")
          );
        }

        // The decoded file goes to disk and only its path comes back - the binary never
        // passes through the model context.
        const fileName = savedFileName(target, attachments);
        const destDir = path.join(this.attachmentsDir(), messageId);
        await fs.mkdir(destDir, { recursive: true });
        const buffer = Buffer.from(attachment.data.data || "", "base64url");
        const dest = path.join(destDir, fileName);
        await fs.writeFile(dest, buffer);
        const rel = path.relative(this.registry.projectDir, dest);
        return jsonResult({
          filename: fileName,
          originalFilename: target.filename,
          mimeType: target.mimeType,
          size: buffer.length,
          path: rel.startsWith("..") || path.isAbsolute(rel) ? dest : rel,
        });
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  }
}
