import { describe, expect, it } from "bun:test";
import {
  DOCUMENT,
  downloadFormat,
  fileIdFrom,
  FOLDER,
  importTarget,
  isTextMime,
  mimeTypeFrom,
  PRESENTATION,
  quote,
  searchQuery,
  SPREADSHEET,
  textExport,
} from "./formats.js";

describe("exports", () => {
  it("defaults to an Office format and checks requested ones", () => {
    expect(downloadFormat(DOCUMENT)).toEqual({
      ext: "docx",
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    expect(downloadFormat(SPREADSHEET, ".PDF")).toEqual({ ext: "pdf", mimeType: "application/pdf" });
    expect(() => downloadFormat(SPREADSHEET, "docx")).toThrow(/Google Sheet exports to xlsx/);
    expect(() => downloadFormat("application/pdf")).toThrow(/cannot be exported/);
  });

  it("reads Docs as Markdown and Sheets as CSV with a note", () => {
    expect(textExport(DOCUMENT)).toEqual({ mimeType: "text/markdown", note: undefined });
    expect(textExport(SPREADSHEET)?.note).toMatch(/first sheet/);
    expect(textExport(PRESENTATION)?.mimeType).toBe("text/plain");
    expect(textExport("application/vnd.google-apps.drawing")).toBeNull();
  });

  it("knows which regular files are text", () => {
    for (const t of ["text/plain", "text/markdown", "application/json", "application/ld+json", "application/xml", "application/x-yaml"]) {
      expect(isTextMime(t)).toBe(true);
    }
    for (const t of ["application/pdf", "image/png", "application/zip", undefined]) expect(isTextMime(t)).toBe(false);
  });
});

describe("imports", () => {
  it("converts documents, sheets and decks into their Google type", () => {
    expect(importTarget("text/markdown")).toBe(DOCUMENT);
    expect(importTarget("text/csv")).toBe(SPREADSHEET);
    expect(importTarget("application/vnd.openxmlformats-officedocument.presentationml.presentation")).toBe(PRESENTATION);
    expect(() => importTarget("image/png")).toThrow(/cannot be converted/);
  });
});

describe("file references", () => {
  it("takes bare ids and the usual Drive and Docs URLs", () => {
    const id = "1AbC_d-EfGhIjKlMnOpQ";
    expect(fileIdFrom(id)).toBe(id);
    expect(fileIdFrom(` https://drive.google.com/file/d/${id}/view?usp=sharing `)).toBe(id);
    expect(fileIdFrom(`https://docs.google.com/document/d/${id}/edit#heading=h.1`)).toBe(id);
    expect(fileIdFrom(`https://docs.google.com/spreadsheets/u/1/d/${id}/edit`)).toBe(id);
    expect(fileIdFrom(`https://drive.google.com/drive/u/0/folders/${id}`)).toBe(id);
    expect(fileIdFrom(`https://drive.google.com/open?id=${id}`)).toBe(id);
  });

  it("refuses anything else", () => {
    expect(() => fileIdFrom(undefined)).toThrow(/'fileId' is required/);
    expect(() => fileIdFrom("https://evil.example/d/abc")).toThrow(/not a Google Drive URL/);
    expect(() => fileIdFrom("https://drive.google.com/drive/my-drive")).toThrow(/no file id/);
    expect(() => fileIdFrom("a b", "folderId")).toThrow(/'folderId'/);
  });
});

describe("search queries", () => {
  it("turns plain words into a full-text search and leaves syntax alone", () => {
    expect(searchQuery("faktura maj")).toBe("fullText contains 'faktura maj' and trashed = false");
    expect(searchQuery("name contains 'x'")).toBe("(name contains 'x') and trashed = false");
    expect(searchQuery("trashed = true")).toBe("(trashed = true)");
  });

  it("adds folder and type filters", () => {
    expect(searchQuery(undefined, "F1", FOLDER)).toBe(`'F1' in parents and mimeType = '${FOLDER}' and trashed = false`);
  });

  it("escapes quotes and backslashes", () => {
    expect(quote("O'Brien\\x")).toBe("'O\\'Brien\\\\x'");
  });

  it("accepts short type names", () => {
    expect(mimeTypeFrom("Sheet")).toBe(SPREADSHEET);
    expect(mimeTypeFrom("image/png")).toBe("image/png");
  });
});
