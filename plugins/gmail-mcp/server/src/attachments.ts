// Identifying and naming message attachments for save_attachment.
//
// Gmail issues a NEW body.attachmentId on every messages.get, so an id handed
// out by get_message never matches a later fetch of the same message. The MIME
// partId ("1", "2.1") is stable, so that is the id the tools expose.

export interface MessageAttachment {
  partId: string;
  gmailId: string; // body.attachmentId of the fetch it came from - for download only
  filename: string;
  mimeType: string;
  size: number;
}

// Clients holding an id from before the switch to partIds (a long Gmail token)
// still work: the bytes download fine, and the size tells which part it was.
export function findAttachment(
  all: MessageAttachment[],
  ref: string,
  downloadedSize?: number
): MessageAttachment | undefined {
  const byPart = all.find((a) => a.partId === ref || a.gmailId === ref);
  if (byPart || downloadedSize === undefined) return byPart;
  const bySize = all.filter((a) => a.size === downloadedSize);
  return bySize.length === 1 ? bySize[0] : undefined;
}

export function isPartId(ref: string): boolean {
  return /^\d+(\.\d+)*$/.test(ref);
}

// Gmail filenames can contain slashes/illegal chars (e.g. "2025-FP/I/27707.pdf")
export function safeFileName(name: string): string {
  return name.replace(/[\/\\:*?"<>|]/g, "_") || "attachment";
}

// On-disk name, unique within the message: two parts called "image.png" must
// not overwrite each other, while saving the same part twice stays idempotent.
export function savedFileName(
  target: MessageAttachment,
  all: MessageAttachment[]
): string {
  const name = safeFileName(target.filename);
  const clash = all.some(
    (a) => a.partId !== target.partId && safeFileName(a.filename) === name
  );
  if (!clash) return name;
  const dot = name.lastIndexOf(".");
  const suffix = `-part${target.partId}`;
  return dot > 0 ? name.slice(0, dot) + suffix + name.slice(dot) : name + suffix;
}
