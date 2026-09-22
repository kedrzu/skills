---
name: web-search
description: How to search the web so that the answer is actually found and negative claims are actually true — engine selection (Exa, WebSearch, browser automation, curl), query hygiene, graded negative verdicts, effort budgeting, and going to the primary source when the open web comes up empty. Load this before the first search of any research task, and again before writing any sentence claiming that something does not exist, is unavailable, was discontinued or is not offered. Use it whenever repeated searches return the same domains or nothing useful, when verifying that a specific part number, model variant, package version, API or spec is real, when a site answers 403 / CAPTCHA / empty body, when a PDF datasheet or catalog has to be read, and whenever a research subagent reports it could not find something. Applies to the main agent and to every research subagent alike.
---

# Web search protocol

This governs any task where facts come from the open web — yours and every research
subagent's. Subagents get the same rules as the main agent, because the failure mode
below does not care which one is searching.

## The failure this prevents

A subagent hunting a drawer-slide part number reported `PK-L-H53-550` **does not
exist, independently confirmed**, and the main agent passed that to the user as fact.
The part is in the manufacturer's own catalog and in several shops. That session ran
139 searches and 106 fetches — the problem was never volume. It was **direction**
(resellers and a search engine instead of the source of truth) and a **premature
negative** (the verdict landed exactly on the query limit in force at the time). A
second session repeated it: 161 searches, nine hours, and a link the *user* found
finally moved it.

Three lessons drive everything below:

- **A missing result is evidence about your search, not about the world.** Only the
  primary source can say something does not exist.
- **When a search fails, change the engine, not the wording.** Re-phrasing the same
  question into the same index is the single biggest waste of budget.
- **Reporting is where the damage happens.** A carefully hedged finding costs the user
  nothing; a confident "there is no such thing" closes the topic and sends them down a
  worse path.

---

## 1. Pick the engine on purpose

| Engine | Good at | Reach for it when |
|---|---|---|
| **`mcp__exa__web_search_exa`** | semantic search that returns page *content*, not just links; finds the long tail of small shops, niche docs and specific variant codes | **default starting point**: building a candidate list, "does this variant exist", product pages, obscure vendors |
| `WebSearch` | operators (`site:`, `filetype:`, quoted strings), fresh news, one quick fact | you need a hard operator or something from the last few days |
| **Browser automation** (`mcp__playwright__*`) | sites that block everything else; live prices; anything behind JS | see the blocked-channel table in section 5 |
| `Bash` + `curl` | sitemaps, XML, JSON APIs, PDFs, the primary-source probe | section 4 |

This plugin brings its own Exa server. Browser automation it **expects to already be
there** and deliberately does not install: a `playwright` MCP is the host project's to
provide, because a project that already runs one would otherwise get a second server
under the same name.

**A missing engine is reported, never worked around silently** — it changes which
conclusions you are entitled to. Without Exa, `WebSearch` becomes the default and the
primary-source probe (section 4) carries more weight. Without browser automation, pages
and prices from the blocked hosts in section 5 stay **unverified** and must be labelled
as such — they never become an N2/N3 verdict.

**No `mcp__playwright__*` tools at all?** Say so the first time the task needs them, and
offer to install it rather than quietly downgrading the answer:

- `claude plugin install playwright@claude-plugins-official` — one command, runs
  `npx @playwright/mcp@latest`;
- or, in a project that pins its own tooling, add `@playwright/mcp` to its manifest and
  point `.mcp.json` at the installed binary — pinned and faster, no `npx` on the path.

Then continue on the remaining engines and label what stayed unverified.

**Querying Exa — it is not a keyword engine.**

- `query` is a **full-sentence description of the ideal page**: "product page for a GTV
  ball-bearing drawer slide H53 550 mm with soft-close, in a Polish shop" — not
  `gtv h53 550 price`.
- `objective` is **required** in practice: state what should rank high, what to reject,
  and which numbers to extract. An empty objective measurably degrades results.
- Put codes and SKUs inside the sentence, but **do not trust semantic matching for exact
  strings** — confirm the exact string later on the product page itself.
- When highlights are not enough, `mcp__exa__web_fetch_exa` takes **`urls`** (an array),
  not `url`.

**Query hygiene for `WebSearch`** (from transcript analysis: median query 57 characters
written as full sentences, an operator in ~25% of queries, and 20% of queries returning
two or fewer distinct domains):

1. **2–5 keywords, not a sentence.** Filler words ("price", "where to buy", "best")
   steer results toward SEO pages instead of sources.
2. **A domain belongs in `site:`, never in the words.** `site:example.com "H-53" 750`,
   not `example.com Sevroll H-53 100kg L-750 price` — in the second form the domain is
   just a token and you get some other shop entirely.
3. **Always quote a code or SKU:** `"PK-L-H53-550"`. Unquoted, the engine quietly
   substitutes a neighbouring code and hands you a coherent summary **of a different
   product** (observed: asked for `PK-L-H53-550`, results and summary about
   `PK-0-H53-550`).
4. **Search the family, not the single variant.** Drop the last segment (`"PK-L-H53"`)
   and you see the whole series — which tells you which variants exist at all. A single
   variant is often unindexed; a family almost never is.
5. **Use the language of the manufacturer's market.** A Turkish manufacturer → query in
   Turkish; German → `Vollauszug`, `Datenblatt`. Querying in your own language about a
   foreign maker just finds local resellers, i.e. what you already know.
6. **`filetype:pdf` for specs, datasheets and price lists.**

**Loop detector:** two consecutive queries returning the same domains means **change
engine or change angle** — not wording. A third rephrasing of the same question is pure
waste.

---

## 2. Negative verdicts come in three grades

"It's not there" is three different claims with wildly different costs. Name the one you
actually proved:

| Grade | How it reads | What it requires |
|---|---|---|
| **N1 — I did not find it** | "I did not find [X]. I checked: [list]" | an honest list of what you checked. **This is the default** |
| **N2 — not currently offered** | "None of the sources I checked has [X] (as of [date]): [source 1], [2], [3]" | ≥3 **named** vendors/sources + a date. It speaks about **availability**, not existence |
| **N3 — the source of truth does not have it** | "[Manufacturer/project] does not list [X]" | you **touched the primary source** (section 4): sitemap, on-site search, catalog/price list/PDF, official registry or repository — quoted, with a link. Forbidden without that |

**Why the asymmetry matters:** "I did not find it" is cheap and reversible — the user
keeps looking, asks the vendor, comes back tomorrow. "It does not exist" is expensive and
irreversible — it closes the question, and they buy the wrong thing or redesign around a
constraint that was never real. So at any uncertainty you step **down** a grade
(N3 → N2 → N1), never up.

**What is not negative evidence:**

- **A vendor's statement about its own range.** "The 550 mm soft-close length is not
  available" is a fact about *one shop*, which does not know the manufacturer's catalog
  and has an interest in selling what is on its shelf. Quoting it as the manufacturer's
  position swaps the subject of the sentence — that is exactly how the false negative
  above was produced.
- **A summary from a search engine that swapped your code.** No hit on the *exact*
  string is zero information about existence. Before writing anything negative, check
  whether the exact string appears in the results at all; if it does not, you have N1.
- **An empty marketplace or aggregator.** They index what someone listed, not what
  exists.
- **An HTTP status on its own.** 200 does not mean "exists" — see section 4.

**Who may rule:** a subagent **never** returns N3. If it concludes something is missing,
it returns **`UNRESOLVED`** plus the leads it gathered — exactly what it searched for,
which **neighbouring codes or versions** it saw, the manufacturer's domain, the URL
pattern product pages follow — and stops. N2 and N3 are ruled **only by the main agent**,
after the primary-source probe. The reason is structural: a subagent does not know how
much is already known, and systematically confuses "my budget ran out" with "it isn't
there".

---

## 3. Budget the effort; do not count queries

An earlier version of this protocol capped research at "~8 searches/fetches". The cap
existed for a real reason — a watchdog kills sessions that hang for ~10 minutes — but it
**measured the wrong thing**. Sessions are not killed by query count (queries are fast);
they are killed by **one fetch that hangs**. Meanwhile the model reads "8" as "draw a
conclusion after the eighth". That is how the false negative happened: exactly 8
searches, 3 fetches, verdict "DOES NOT EXIST".

- **The anti-hang rule is what actually protects you.** No single fetch blocks for more
  than ~15 s. 403 / CAPTCHA / empty body → **skip immediately**, no retry, no
  workaround-hunting. The same host does not get a third chance.
- **Soft budget ~20 actions, ceiling ~35** — and that is not a target to exhaust.
- **A coverage checklist beats a counter.** You are done when coverage is ticked off, not
  when a counter fills. Choose the checklist from the domain: for a product, ≥2
  independent price channels + ≥1 user-opinion source + ≥1 deliberate query about flaws +
  the manufacturer's own page; for a library or API, the official docs + the changelog or
  release notes + the issue tracker + one real usage example. Whatever you did not tick
  goes into **"Gaps"**, not into the conclusion.
- **Report your usage** alongside the findings ("budget and coverage"). It gives the main
  agent an alarm signal: **a negative verdict reported with low usage and incomplete
  coverage is suspect.**
- **Two turns beat one long session.** Do not stretch a single subagent — that feeds the
  watchdog directly. Turn 1 is the normal research pass. When it comes back `UNRESOLVED`
  or negative, the main agent launches **turn 2: a primary-source probe subagent** with
  one narrow goal. Each session stays short while total searching stays unbounded. The
  cure for a watchdog is **more agents in sequence**, not less searching in one.

---

## 4. When the open web comes up empty, go to the primary source

Trigger it when: a subagent returned `UNRESOLVED`; you are about to rule N2 or N3; you
are chasing a variant/size/version the resellers do not carry; you can see the search
engine substituting your code; or the user brought you a link to the source. Cost:
1–3 minutes.

The procedure — sitemap discovery, grepping by code *pattern*, calibrating against a
deliberate 404, on-site search URLs per platform, and getting text out of PDFs — is in
**`${CLAUDE_PLUGIN_ROOT}/skills/web-search/references/primary-source-probe.md`**. Read it
before you run the probe; it is the only thing that earns you an N3.

The headline you must not skip: **an HTTP 200 proves nothing on its own.** Many CMSes
serve 200 together with a "not found" page. Always fetch a deliberately nonexistent code
in parallel and compare **status + `<title>`**; only the *difference* proves existence.

---

## 5. Tooling and known blocks

A research subagent loads its tools with `ToolSearch`:
**`select:mcp__exa__web_search_exa,mcp__exa__web_fetch_exa,WebSearch,WebFetch,Bash`**.
Handing it only `WebSearch`+`WebFetch` is why the word "sitemap" never appeared once in a
15-subagent session: **what is not in the toolbox does not get invented** — the model
just runs a twentieth search instead.

| Channel | State (verified 2026-09-21) | What to do |
|---|---|---|
| **Allegro** | 403 to `WebFetch`, `curl`, Jina **and** Exa's crawler | **browser automation only**; otherwise take the price from an aggregator and label it unverified |
| **Häfele** | Cloudflare — same | browser automation, or the PDF datasheet instead of the page |
| Amazon | often renders nothing for `WebFetch` | browser automation or an aggregator; label as unverified |
| Ceneo, Pepper (PL aggregators) | work through `WebFetch` | fine as baseline price channels |
| `WebFetch` on a sitemap or XML | **unreliable** — it summarises and drops URLs (a sub-map can come back as a handful of image links with the products missing) | always `Bash` + `curl` + `grep` |
| `WebFetch` on a PDF | binary garbage | Jina (`r.jina.ai/<url>`) or `curl` + `pdftotext -layout` |
| Jina Reader | works with no key, **20 req/min**; bounces off Cloudflare (Allegro, Häfele) | for PDFs and pages `WebFetch` mangles |
| Exa without a key | works; limits undocumented | on 429 from many parallel subagents, tell the user — do not route around it |

**Network sandbox.** `Bash` goes through a domain-allowlist proxy
(`.claude/settings.json` → `sandbox.network.allowedDomains`). A manufacturer's domain is
usually not on it — **pass it in the `Bash` call's `allowed_domains`**, otherwise `curl`
may hang until timeout instead of failing fast. If the connection is still refused,
**do not engineer around it**: record the gap ("primary-source probe impossible — domain
outside the allowlist"), tell the user, and rule N1/N2 at most. Temporary files always go
to `"$TMPDIR"`, never to `/tmp`.
