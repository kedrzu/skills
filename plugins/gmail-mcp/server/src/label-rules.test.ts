import { describe, expect, it } from "bun:test";
import { describeRules, planThreadChange, protectedLabels, RuleViolation, validateLabelRules, viewQuery, type LabelRulesConfig } from "./label-rules.js";
import { toolDefinitions } from "./tools.js";

const umbra: LabelRulesConfig = {
  groups: {
    status: ["AI/Done", "AI/Triage"],
    priority: ["P/0", "P/1", "P/2", "P/3"],
  },
  require: [{ when: "AI/Done", group: "priority" }],
  archiveMarkers: ["Nieaktualne", "Śmieci"],
  views: { unprocessed: "-label:AI/Done -label:AI/Triage", triage: "label:AI/Triage" },
};

const plan = (change: Partial<{ add: string[]; remove: string[]; set: Record<string, string | null> }>, current: string[], rules = umbra) =>
  planThreadChange(rules, { add: [], remove: [], set: {}, ...change }, current);

describe("validateLabelRules", () => {
  it("accepts a well-formed config", () => {
    expect(validateLabelRules(umbra)).toEqual([]);
  });

  it("reports overlapping groups, unknown groups and bad names", () => {
    const errors = validateLabelRules({
      groups: { a: ["X", "Y"], b: ["x"], "bad name": ["Z"] },
      require: [{ when: "X", group: "nope" }],
      archiveMarkers: ["Y"],
      views: { ok: "" },
    });
    expect(errors.join("\n")).toMatch(/'x' is already in group 'a'/);
    expect(errors.join("\n")).toMatch(/unknown group 'nope'/);
    expect(errors.join("\n")).toMatch(/bad name/);
    expect(errors.join("\n")).toMatch(/archiveMarkers: 'Y'/);
    expect(errors.join("\n")).toMatch(/views.ok/);
  });
});

describe("planThreadChange - groups", () => {
  it("sets a label and strips the rest of its group present on the thread", () => {
    const p = plan({ set: { status: "AI/Done", priority: "P/2" } }, ["INBOX", "AI/Triage", "P/0"]);
    expect(p.add).toEqual(["AI/Done", "P/2"]);
    expect(p.remove).toEqual(["AI/Triage", "P/0"]);
    expect(p.setLabels).toEqual(["AI/Done", "P/2"]);
  });

  it("matches group labels case-insensitively and keeps their canonical name", () => {
    expect(plan({ set: { priority: "p/1" } }, []).add).toEqual(["P/1"]);
  });

  it("clears a group with null", () => {
    const p = plan({ set: { status: null } }, ["AI/Triage", "INBOX"]);
    expect(p.add).toEqual([]);
    expect(p.remove).toEqual(["AI/Triage"]);
  });

  it("rejects group labels in addLabels/removeLabels, unknown groups and foreign values", () => {
    expect(() => plan({ add: ["AI/Done"] }, [])).toThrow(/set\.status/);
    expect(() => plan({ remove: ["p/3"] }, [])).toThrow(RuleViolation);
    expect(() => plan({ set: { colour: "red" } }, [])).toThrow(/Unknown group 'colour'/);
    expect(() => plan({ set: { priority: "P/9" } }, [])).toThrow(/not in group 'priority'/);
  });
});

describe("planThreadChange - require", () => {
  it("rejects a Done thread without a priority", () => {
    expect(() => plan({ set: { status: "AI/Done" } }, ["INBOX"])).toThrow(/must also carry one of group 'priority'/);
  });

  it("accepts it when the thread already has a priority", () => {
    expect(plan({ set: { status: "AI/Done" } }, ["P/3"]).add).toEqual(["AI/Done"]);
  });

  it("rejects clearing the priority of a Done thread", () => {
    expect(() => plan({ set: { priority: null } }, ["AI/Done", "P/1"])).toThrow(/priority/);
  });

  it("leaves unrelated edits of a legacy thread alone", () => {
    expect(plan({ add: ["Finance"] }, ["AI/Done"]).add).toEqual(["Finance"]);
  });
});

describe("planThreadChange - archive markers", () => {
  it("adding a marker removes INBOX", () => {
    const p = plan({ add: ["Nieaktualne"] }, ["INBOX"]);
    expect(p.remove).toContain("INBOX");
    expect(p.summary).toContain("archived (INBOX removed)");
  });

  it("removing INBOX without a marker is rejected, with one it passes", () => {
    expect(() => plan({ remove: ["INBOX"] }, ["INBOX", "Finance"])).toThrow(/archive marker/);
    expect(plan({ remove: ["INBOX"] }, ["INBOX", "Śmieci"]).remove).toEqual(["INBOX"]);
  });

  it("without markers archiving is free", () => {
    expect(plan({ remove: ["INBOX"] }, ["INBOX"], {}).remove).toEqual(["INBOX"]);
    expect(planThreadChange(undefined, { add: ["A"], remove: ["INBOX"], set: {} }, []).remove).toEqual(["INBOX"]);
  });
});

describe("views and descriptions", () => {
  it("resolves a view and rejects an unknown one", () => {
    expect(viewQuery(umbra, "triage")).toBe("label:AI/Triage");
    expect(viewQuery(umbra, undefined)).toBe("");
    expect(() => viewQuery(umbra, "done")).toThrow(/Views: unprocessed, triage/);
    expect(() => viewQuery(undefined, "x")).toThrow(/no views/);
  });

  it("protects group labels and markers from cleanup", () => {
    expect(protectedLabels(umbra)).toContain("AI/Done");
    expect(protectedLabels(umbra)).toContain("Śmieci");
    expect(protectedLabels(undefined)).toEqual([]);
  });

  it("spells the rules out in update_thread", () => {
    const text = describeRules(umbra);
    expect(text).toContain("status = AI/Done | AI/Triage");
    expect(text).toContain("'AI/Done' must also carry one label of group 'priority'");
    expect(text).toContain("'Nieaktualne', 'Śmieci'");
  });

  it("generates schemas from the rules", () => {
    const find = (rules: LabelRulesConfig | undefined, name: string) => toolDefinitions(rules).find((t) => t.name === name)!;
    const plainUpdate = find(undefined, "update_thread").inputSchema.properties as Record<string, any>;
    expect(plainUpdate.set).toBeUndefined();
    expect((find(undefined, "search_threads").inputSchema.properties as any).view).toBeUndefined();

    const update = find(umbra, "update_thread").inputSchema.properties as Record<string, any>;
    expect(update.set.properties.priority.enum).toEqual(["P/0", "P/1", "P/2", "P/3", null]);
    expect((find(umbra, "search_threads").inputSchema.properties as any).view.enum).toEqual(["unprocessed", "triage"]);
  });
});
