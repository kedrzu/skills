# State folder format

`docs/naming/<slug>/` — the slug names the thing being named, not a candidate (`habit-app`, not
`streak`).

## `names.json`

The script reads `tlds` and `required_tlds` and writes `domains`; everything else is yours.

```json
{
  "tlds": ["com", "app", "io"],
  "required_tlds": ["com"],
  "names": {
    "Streak": {
      "direction": "everyday verbs and nouns about keeping going",
      "round": 2,
      "domains": {
        "streak.com": { "status": "taken", "method": "dns", "checked_at": "2026-10-05" },
        "streak.app": { "status": "premium", "method": "porkbun", "price": "$2,800", "checked_at": "2026-10-05" },
        "getstreak.com": { "status": "likely-free", "method": "rdap", "checked_at": "2026-10-05" }
      },
      "conflicts": [
        {
          "who": "Streaks (iOS habit tracker)",
          "space": "habit tracking",
          "severity": "blocking",
          "url": "https://apps.apple.com/app/streaks/id963034692",
          "checked_at": "2026-10-05"
        }
      ],
      "phonetics": "one spelling; plural 'Streaks' is the established competitor",
      "verdict": "dropped",
      "reason": "same name, same category",
      "feedback": []
    }
  }
}
```

- **`tlds`** — checked for every name. **`required_tlds`** — must be open for a name to reach the
  shortlist; without it, any one open TLD from `tlds` is enough.
- **`domains`** — keyed by full domain, so variants (`getstreak.com`) sit next to the bare name.
  Statuses: `taken`, `likely-free` (registry has no record), `free` and `premium` (a registrar
  answered; add `price`), `unknown` (lookup failed — re-run, don't guess). The script never
  downgrades `free`/`premium` back to `likely-free`.
- **`conflicts`** — severity as defined in `conflict-check.md`. An empty list means you searched and
  found nothing; a missing field means you have not searched yet.
- **`verdict`** — `candidate` (default), `liked` and `rejected` (the user's), `dropped` (yours: taste,
  conflict, domains; give `reason`).
- **`feedback`** — the user's words about this name, one string each.

Keys are the names as the user would write them (`"Quiet Harbor"`); the domain label is derived by
lower-casing and stripping everything but letters, digits and hyphens.

## `BRIEF.md`

```markdown
# Naming: habit-tracking app

**What it is.** A mobile app that helps people keep small daily habits. Consumer, iOS first.
**Space.** Habit trackers, productivity apps.
**Languages.** English name; Polish and Spanish words welcome if easy for English speakers.
**TLDs.** .com required; .app nice to have.

## Standing preferences
- Plain over cute — "too cute" about Sprout and Bloomy (round 1).
- No food words (round 2).
- Likes verbs (round 2). *(Inferred by the agent, not yet confirmed.)*

## Rejected directions
- Plant and growth metaphors — crowded and "too cute" (round 1).
```

## `LOG.md`

Append only; never rewrite an earlier round.

```markdown
## Round 2 — 2026-10-05

**User on round 1.** Plant names too cute; drop growth metaphors. Go with verbs, as proposed.
**Directions.** Everyday verbs about continuing (34 generated, 9 checked); Polish everyday words (20/6).
**What came out.** Verb .coms are almost all taken or premium; `get`-prefixed variants are open
but the user dislikes prefixes. Polish words pass the domain check but fail the hearing test for
English speakers (ł, sz).
**Best.** Keepon (.com likely-free, no conflict found in app stores or TMview).
**Proposed next.** Drop Polish; two-word compounds with a warm verb ("keep going", "show up");
confirm Keepon at Porkbun.
```
