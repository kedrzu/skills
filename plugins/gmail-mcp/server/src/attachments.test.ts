import { describe, expect, it } from "bun:test";
import {
  findAttachment,
  isPartId,
  safeFileName,
  savedFileName,
  type MessageAttachment,
} from "./attachments.js";

const att = (partId: string, filename: string, size: number): MessageAttachment => ({
  partId,
  gmailId: `ANGjdJ-${partId}-fresh`,
  filename,
  mimeType: "image/jpeg",
  size,
});

const msg = [
  att("2", "Screenshot_1.jpg", 131117),
  att("3", "Screenshot_4.jpg", 141035),
  att("4", "image.png", 500),
  att("5", "image.png", 500),
];

describe("findAttachment", () => {
  it("finds a part by its stable part id", () => {
    expect(findAttachment(msg, "3")?.filename).toBe("Screenshot_4.jpg");
  });

  it("recognises a stale Gmail id by the downloaded size", () => {
    expect(findAttachment(msg, "ANGjdJ-stale", 131117)?.filename).toBe("Screenshot_1.jpg");
  });

  it("refuses to guess when the size is ambiguous or unknown", () => {
    expect(findAttachment(msg, "ANGjdJ-stale", 500)).toBeUndefined();
    expect(findAttachment(msg, "ANGjdJ-stale")).toBeUndefined();
  });
});

describe("isPartId", () => {
  it("tells MIME part ids from Gmail attachment tokens", () => {
    expect(isPartId("2")).toBe(true);
    expect(isPartId("1.3")).toBe(true);
    expect(isPartId("ANGjdJ8JtaAH")).toBe(false);
  });
});

describe("savedFileName", () => {
  it("keeps the original name when it is unique in the message", () => {
    expect(savedFileName(msg[0], msg)).toBe("Screenshot_1.jpg");
  });

  it("disambiguates parts sharing a name, so neither overwrites the other", () => {
    expect(savedFileName(msg[2], msg)).toBe("image-part4.png");
    expect(savedFileName(msg[3], msg)).toBe("image-part5.png");
  });

  it("strips path separators and characters illegal on disk", () => {
    expect(safeFileName("2025-FP/I/27707.pdf")).toBe("2025-FP_I_27707.pdf");
  });
});
