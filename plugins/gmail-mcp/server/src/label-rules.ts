// Optional label rules a project declares in its config. Four building blocks:
//
//   groups          mutually exclusive label sets, changed only through update_thread.set
//   require         "a thread with label X must also carry one label of group G"
//   archiveMarkers  the only labels that may take a thread out of INBOX
//   views           named Gmail queries for search_threads.view
//
// Pure functions only: the Gmail calls live in tools.ts, so every rule is unit-testable.

export interface RequireRule {
  when: string; // label name
  group: string; // group key
}

export interface LabelRulesConfig {
  groups?: Record<string, string[]>;
  require?: RequireRule[];
  archiveMarkers?: string[];
  views?: Record<string, string>;
}

const IDENT = /^[A-Za-z][A-Za-z0-9_-]*$/;

export function validateLabelRules(r: LabelRulesConfig): string[] {
  const errors: string[] = [];
  if (!r || typeof r !== "object") return ["expected an object"];
  const owner = new Map<string, string>();
  for (const [group, labels] of Object.entries(r.groups ?? {})) {
    if (!IDENT.test(group)) errors.push(`groups.${group}: group names must be identifiers`);
    if (!Array.isArray(labels) || labels.length === 0 || labels.some((l) => typeof l !== "string" || !l)) {
      errors.push(`groups.${group}: expected a non-empty array of label names`);
      continue;
    }
    for (const label of labels) {
      const prev = owner.get(label.toLowerCase());
      if (prev) errors.push(`groups.${group}: '${label}' is already in group '${prev}'`);
      owner.set(label.toLowerCase(), group);
    }
  }
  for (const [i, rule] of (r.require ?? []).entries()) {
    if (!rule?.when || !rule?.group) {
      errors.push(`require[${i}]: needs 'when' and 'group'`);
    } else if (!r.groups?.[rule.group]) {
      errors.push(`require[${i}]: unknown group '${rule.group}'`);
    }
  }
  for (const m of r.archiveMarkers ?? []) {
    if (owner.has(m.toLowerCase())) {
      errors.push(`archiveMarkers: '${m}' is also in group '${owner.get(m.toLowerCase())}'`);
    }
  }
  for (const [view, query] of Object.entries(r.views ?? {})) {
    if (!IDENT.test(view)) errors.push(`views.${view}: view names must be identifiers`);
    if (typeof query !== "string" || !query.trim()) errors.push(`views.${view}: expected a Gmail query`);
  }
  return errors;
}

const lower = (s: string) => s.toLowerCase();
const has = (list: string[], name: string) => list.some((l) => lower(l) === lower(name));

export function groupOf(rules: LabelRulesConfig, label: string): string | undefined {
  for (const [group, labels] of Object.entries(rules.groups ?? {})) {
    if (has(labels, label)) return group;
  }
  return undefined;
}

export function isMarker(rules: LabelRulesConfig, label: string): boolean {
  return has(rules.archiveMarkers ?? [], label);
}

// Labels cleanup_labels must never delete: the project's rules depend on them.
export function protectedLabels(rules: LabelRulesConfig | undefined): string[] {
  if (!rules) return [];
  return [...Object.values(rules.groups ?? {}).flat(), ...(rules.archiveMarkers ?? [])];
}

export interface ThreadChange {
  add: string[]; // plain label names from addLabels
  remove: string[]; // plain label names from removeLabels
  set: Record<string, string | null>; // group -> label, null clears the group
}

export interface PlannedChange {
  add: string[]; // label names to add (group labels may not exist yet)
  remove: string[]; // label names to remove
  setLabels: string[]; // the subset of add that came from set (created when missing)
  summary: string[];
}

export class RuleViolation extends Error {}

// What update_thread should do to a thread that currently carries `current` (label
// names, summed over its messages). Throws RuleViolation before anything is written.
export function planThreadChange(
  rules: LabelRulesConfig | undefined,
  change: ThreadChange,
  current: string[]
): PlannedChange {
  const r = rules ?? {};
  const groups = r.groups ?? {};
  const add: string[] = [];
  const remove: string[] = [];
  const setLabels: string[] = [];
  const summary: string[] = [];
  const push = (list: string[], name: string) => {
    if (!has(list, name)) list.push(name);
  };

  const managed = [...change.add, ...change.remove].filter((l) => groupOf(r, l));
  if (managed.length) {
    const hints = managed.map((l) => `${l} -> set.${groupOf(r, l)}`).join(", ");
    throw new RuleViolation(
      `Labels ${managed.join(", ")} belong to an exclusive group and can only be changed through 'set' (${hints}). ` +
        `Setting one label of a group removes the others.`
    );
  }

  for (const [group, value] of Object.entries(change.set)) {
    const members = groups[group];
    if (!members) {
      const known = Object.keys(groups);
      throw new RuleViolation(
        `Unknown group '${group}' in 'set'. ` + (known.length ? `Groups: ${known.join(", ")}` : "This project defines no label groups.")
      );
    }
    let canonical: string | null = null;
    if (value !== null && value !== undefined && value !== "") {
      canonical = members.find((m) => lower(m) === lower(String(value))) ?? null;
      if (!canonical) {
        throw new RuleViolation(`'${value}' is not in group '${group}' (${members.join(", ")}); use null to clear the group`);
      }
      push(add, canonical);
      push(setLabels, canonical);
      summary.push(`${group}: ${canonical}`);
    } else {
      summary.push(`${group}: cleared`);
    }
    for (const m of members) {
      if (m !== canonical && has(current, m)) push(remove, m);
    }
  }

  for (const l of change.add) push(add, l);
  for (const l of change.remove) push(remove, l);
  if (change.add.length) summary.push(`added: ${change.add.join(", ")}`);
  if (change.remove.length) summary.push(`removed: ${change.remove.join(", ")}`);

  const resulting = current.filter((l) => !has(remove, l));
  for (const l of add) if (!has(resulting, l) && !has(remove, l)) resulting.push(l);

  const markers = r.archiveMarkers ?? [];
  if (markers.length) {
    const removingInbox = has(change.remove, "INBOX");
    const addingMarker = change.add.some((l) => isMarker(r, l));
    const markerAfter = resulting.some((l) => isMarker(r, l));
    if (removingInbox && !markerAfter) {
      throw new RuleViolation(
        `Removing INBOX (archiving) requires an archive marker: add ${markers.map((m) => `'${m}'`).join(" or ")} in addLabels ` +
          `and INBOX is removed for you. Other labels only tag the thread and leave it in INBOX.`
      );
    }
    if (addingMarker && !has(remove, "INBOX")) {
      push(remove, "INBOX");
      summary.push("archived (INBOX removed)");
    }
  }

  for (const rule of r.require ?? []) {
    const members = groups[rule.group] ?? [];
    const whenGroup = groupOf(r, rule.when);
    const touched =
      has(change.add, rule.when) ||
      rule.group in change.set ||
      (whenGroup !== undefined && whenGroup in change.set);
    if (!touched) continue;
    if (has(resulting, rule.when) && !members.some((m) => has(resulting, m))) {
      throw new RuleViolation(
        `A thread labelled '${rule.when}' must also carry one of group '${rule.group}' (${members.join(", ")}). ` +
          `Pass set.${rule.group} in this call.`
      );
    }
  }

  // Never add and remove the same label in one call: removal wins.
  return { add: add.filter((l) => !has(remove, l)), remove, setLabels, summary };
}

export function viewQuery(rules: LabelRulesConfig | undefined, view: string | undefined): string {
  if (!view) return "";
  const views = rules?.views ?? {};
  const q = views[view];
  if (q === undefined) {
    const known = Object.keys(views);
    throw new RuleViolation(
      `Unknown view '${view}'. ` + (known.length ? `Views: ${known.join(", ")}.` : "This project defines no views.") +
        " Omit 'view' to run the query across all mail."
    );
  }
  return q;
}

// The rules spelled out for the update_thread description, so the agent sees exactly
// what this project enforces.
export function describeRules(rules: LabelRulesConfig | undefined): string {
  if (!rules) return "";
  const parts: string[] = [];
  const groups = Object.entries(rules.groups ?? {});
  if (groups.length) {
    parts.push(
      "EXCLUSIVE GROUPS (change them only via 'set'; setting one label removes the rest of its group; passing them in addLabels/removeLabels is rejected): " +
        groups.map(([g, ls]) => `${g} = ${ls.join(" | ")}`).join("; ") +
        "."
    );
  }
  for (const req of rules.require ?? []) {
    parts.push(`REQUIRED: a thread labelled '${req.when}' must also carry one label of group '${req.group}' - pass set.${req.group} in the same call.`);
  }
  if (rules.archiveMarkers?.length) {
    parts.push(
      `ARCHIVING: only the markers ${rules.archiveMarkers.map((m) => `'${m}'`).join(", ")} take a thread out of INBOX. ` +
        "Add one in addLabels and INBOX is removed for you; removing INBOX without a marker is rejected."
    );
  }
  return parts.join(" ");
}
