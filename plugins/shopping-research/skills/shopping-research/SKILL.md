---
name: shopping-research
description: Shopping research — find the best product or service in a category against the user's criteria and present a ranking from most to least recommended (pros, cons, features, prices, links to buy). Use whenever the user wants to buy something and is looking for the best option, asks for a comparison or ranking ("jaki X kupić", "co polecasz", "pomóż wybrać", "który najlepszy", "porównaj te modele", "research zakupowy"), or gives a budget and a category (laptop, headphones, coffee machine, mattress, tyres, bike, monitor, subscription, software…). Starts with Socratic clarification of criteria, gets an explicitly accepted spec, then runs deep structured research (wide longlist → screening → parallel deep dives → ranking). Not for searching a notes vault, and not for general topic research without intent to buy.
---

# Shopping research

Your job is to find the **best** product (or service, subscription, software) in the given category
against the user's criteria, and to present an honest ranking from most to least recommended.

## What this skill guards against

Language models have a strong tendency to **pick the first sensible product they come across** and
build a justification around it. The natural reflex is: one query → the first few results → "this
one looks good" → recommendation. That is exactly the error this skill exists to prevent. The whole
procedure is therefore built to **separate gathering from judging** and to **force breadth before
anything may be recommended**. If you catch yourself thinking "I think I already know what to
recommend" — that is the signal you are cutting corners. Go back to the procedure.

Keep three principles in mind the whole time:
- **Don't fall for the first candidate.** Until the longlist is complete, you may not favour anyone
  or reject anyone "by eye".
- **Every shortlisted candidate gets the same attention.** The last product examined must be analysed
  as deeply as the first — which is why the deep dives are done by parallel subagents from one
  template.
- **You are a sceptical analyst, not a salesperson.** Your value is finding flaws, hidden costs and
  better alternatives — not confirming your first thought.

## Defaults

- **Market: Poland, PLN**, unless the user says otherwise. Polish shops and price comparators
  (Allegro, Ceneo, x-kom, Morele, Media Expert, RTV Euro AGD, Media Markt, Amazon.pl…), reviews in
  Polish and English. **Pepper (pepper.pl)** — a deal-hunting community: not just recommendations
  and candid opinions, but above all **a discovery engine for prices, discount codes, current
  promotions and historical lows** — valuable **even when the deal has expired** (it shows the real
  price ceiling and what people actually pay). Foreign shops (Amazon.de, AliExpress) **only** when
  the user asks for them — and then open the offer with a Polish delivery address before recommending
  it, because many foreign listings do not ship to Poland.
- **Price = the best real price obtainable today, not the first one seen.** Distinguish the
  *observed range* (what shops show — often with an inflated, artificial "regular" MSRP) from the
  *best real obtainable price* — the lowest credible channel, taking into account **active discount
  codes, promotions and deals (Pepper)**. With conflicting prices, investigate **towards the lowest
  credible one, not the highest**. You are the one doing the price hunt — otherwise the user would
  have to (and will) look for it themselves, and the skill has failed.
- **Always deep mode** with a subagent fan-out (see Phase 2). There is no "quick" mode — serious
  research is the point of this skill.
- **Freshness:** anchor on today's date (you have it in context). Products change, prices change,
  models get discontinued — prefer fresh sources and flag when data may be stale.
- **Language:** all communication and the report in the user's language.

## Two phases and a hard gate between them

```
PHASE 1: SPEC (interactive)          ──[explicit acceptance]──▶     PHASE 2: RESEARCH (autonomous)
Socratic questions → written spec              ⛔ gate              longlist → screening → deep dives → ranking
```

**The gate may not be crossed without the user's explicit consent.** Do not run any search or
subagent until the user has accepted the spec with an unambiguous "start". The reason is practical:
deep research is expensive, and research into the wrong thing is worse than none. The user gets
control over the scope before you move.

---

# PHASE 1 — Search spec

Goal: turn a loose "I'm looking for a good X" into a precise, written spec that the user knowingly
accepts.

## 1.1. Understand the intent and check what you already know

Before asking, use the context you already have — don't ask questions the project can answer. If the
project keeps a memory or knowledge base (its `CLAUDE.md` says where and how to search it), look
there for known preferences, constraints, earlier purchases in this category and earlier shopping
research. Use what you find as **default assumptions in the spec** (marked, so the user can correct
them) instead of asking from scratch.

## 1.2. Derive criteria specific to THIS category

Don't run a rigid, universal questionnaire. First **think like an expert in this particular
category**: which dimensions actually differentiate products and actually drive the purchase
decision? They differ for a laptop (weight, screen, battery, CPU, ports), a mattress (firmness,
material, ventilation, sleeper weight), a coffee machine (type, pressure, grinder, ease of cleaning),
a SaaS subscription (limits, integrations, per-seat pricing, data export).

If you don't know the category well, do a **quick reconnaissance** (1–2 searches like "what to look
for when buying X", "how to choose X guide") so you know what is worth asking about. This is not yet
product research — it is research into criteria.

## 1.3. Ask — Socratically, in groups, not as an interrogation

Ask questions **grouped** in one or two turns, not point by point. Propose sensible defaults so the
user can just confirm or correct. Cover these dimensions (skip the ones you already know from the
project or the first message):

- **What exactly we are buying** — category, type, variant. Narrow it down if broad ("laptop" → for
  what: office work, gaming, video editing?).
- **Use case and context** — who uses it, for what, how often, under what conditions. This matters
  most — the criteria weights depend on it.
- **Budget** — a range. Ask whether it is **hard** (not a penny more) or **soft** (can be exceeded if
  worth it). It changes the strategy.
- **Must-haves** — disqualifying features without which a product drops out automatically.
- **Important criteria + priorities/weights** — what matters most? Ask for a ranking or a split of
  importance. This is the foundation of the ranking.
- **Deal-breakers / things to avoid** — brands, features, past experiences.
- **Brand preferences** — favourite / excluded / indifferent.
- **Horizon and condition** — for how long, new or used/refurbished acceptable, how much warranty and
  service matter.
- **Market** — confirm Poland/PLN (default), unless the user wants abroad.
- **Presentation** — how many positions in the ranking (default 3–5 with justification + mentions),
  what the user expects.

If the user wants to move fast ("I can't be bothered to answer everything, assume something
sensible") — **don't push**. Take reasonable defaults, but **mark them explicitly** in the spec as
assumptions to confirm. Autonomy beats interrogation.

## 1.4. Assemble the spec

Present a concise, structured spec. Use this template:

```markdown
## 📋 Shopping research spec

**What we're looking for:** [category + type + variant]
**Use case:** [who, for what, how often]
**Budget:** [range] — [hard / soft]
**Market:** [Poland/PLN | other]

**Must-haves (without them it drops out):**
- [must-have 1]
- [must-have 2]

**Evaluation criteria (by importance):**
| Criterion | Weight | Why it matters |
|-----------|--------|----------------|
| [e.g. battery] | high | [from the use case] |
| [e.g. weight] | medium | [...] |
| [e.g. noise] | low | [...] |

**Deal-breakers / avoid:** [...]
**Brand preferences:** [favourite / excluded / none]
**Horizon / condition:** [new | used OK], [warranty: important?]

**How I'll present it:** a ranking of [N] positions from most to least recommended,
a comparison table by criteria, pros/cons/prices and shop links for every position, a winner with
justification, conditional alternatives, explicitly rejected candidates, risks to verify before buying.

**Assumed by default (correct me if wrong):** [list, if any]
```

## 1.5. ⛔ Acceptance gate — wait for an explicit "start"

After presenting the spec, **stop and ask directly for consent to start the research**. Don't
search, don't launch subagents.

- **Treat any feedback as a revision of the spec, not as consent.** The user says "I meant X more
  than Y" → update the spec, present it again, ask for consent again.
- **Move only on an unambiguous go-ahead** — e.g. "start", "go", "zaczynaj", "leć", "rób research",
  "ok, szukaj". Refining criteria, a question or a comment **is not** consent.
- If the answer is ambiguous ("sounds good") — ask: "Shall I start the research with this spec?".

This is a deliberate, hard gate. The user explicitly wants to control the scope before you start
expensive research.

---

# PHASE 2 — Research (funnel: divergence → convergence)

Only after acceptance. Research is a funnel: wide first (many candidates), then ever narrower
(screening → deep dives → ranking). Stages may not be skipped and the funnel may not narrow too early.

> **Subagent model:** run all subagents (longlist and deep dives) on **Sonnet** (`Agent` with
> `model: "sonnet"`, `subagent_type: "Explore"` for pure candidate finding or `"general-purpose"` for
> full analyses with web access). The main model (you) does the orchestration, screening, scoring,
> red-team and synthesis — all of the evaluative reasoning. The legwork goes to the cheaper,
> parallel model.
>
> **Shared research protocol:** before you start, load the **`web-search`** skill (`Skill` with
> `skill: "web-search:web-search"`, from the `web-search` plugin this plugin depends on) — engine
> choice (Exa / `WebSearch` / browser automation / `curl`), the three grades of negative verdicts,
> the catalogue probe, budgeting, the blocked-channel table. In the brief of **every** research
> subagent include the instruction to load that skill **plus three rules written out in full**:
> (1) you never conclude that something does not exist — you return `UNRESOLVED` + a lead; (2) load
> tools with the query `select:mcp__exa__web_search_exa,mcp__exa__web_fetch_exa,WebSearch,WebFetch,Bash`;
> (3) **start searching with Exa**, because it reaches the long tail of Polish shops where
> `WebSearch` silently swaps the code for a neighbouring one. A subagent does not inherit your
> context and may skip invoking the skill — a rule that is in neither the brief **nor** the skill
> does not exist.

## Stage A — Longlist (divergence, breadth gate)

Goal: gather a **wide** set of candidates from **several independent angles** before you judge
anything. At this stage **ranking and recommending are forbidden** — you only collect names + where
they came from.

Launch **3–5 subagents in parallel** (Sonnet), each searching from a **different angle** — different
angles catch different products that a single search would miss:
1. **Editorial rankings/tests** — "best X 2026 ranking", comparisons, tests (PL + EN).
2. **Shop bestsellers/offer** — what is actually available and popular in Polish shops in this price
   bracket.
3. **Communities and forums** — Reddit, Wykop, **Pepper (pepper.pl — recommendations + candid
   opinions in comments, valuable even after the deal expired)**, topical groups, user opinions
   ("what do you recommend instead of X", "X vs Y").
4. **Brands/manufacturers** — who matters in this category, which current models they have in this
   segment.
5. **Use case/niche** — products for the specific scenario in the spec (e.g. "quiet", "light", "for
   beginners").

Each subagent returns a list: **product name + variant + approximate PL price + rating signal (stars
+ number of reviews, if visible — or the strength of the community signal) + 1 sentence + source**.
You **merge and deduplicate** the results. Collect ratings already here, so the quality signal flows
through the whole funnel (instead of surfacing only after a complaint) — no "minimum rating"
threshold at this stage; it just has to be **visible at screening**.

**Breadth gate:** before moving on, the longlist must have **≥ 12 real, distinct candidates** from
**at least 3 different angles**. If you have fewer — add an angle or a subagent. The number is not
arbitrary: without a wide longlist the ranking is a lottery of first hits. (Exception: a genuinely
narrow category where fewer options exist on the Polish market — then collect all there are and
**note in the report** that the field was narrow by nature.)

## Stage B — Screening (down to a shortlist)

Apply the spec's **hard requirements and budget** to drop candidates that fail automatically. Get
down to a **shortlist of 5–8** candidates who go on to deep dives.

**⚠️ Price guard (critical — this is where a good product most often disappears silently):** cut
hard requirements (missing must-have, wrong size, discontinued) boldly. But **do NOT cut a candidate
for budget on a price that is uncertain, inconsistent between angles, or looks like a catalogue
price (MSRP).** Deep price research lives only in Stage C — so the "in budget / out" decision cannot
be made here on bad data. Rule: **"let it through to C" is reversible and cheap, "cut" is
irreversible and expensive → when the price is uncertain, let it through by default** (mark it
"price to verify", let Stage C establish the real obtainable price: codes, channels, deals). Cut for
budget **only** when even the lowest credible price exceeds it (then → "Considered but rejected" with
that reason). Also: **respect the budget type from the spec** — with a **soft** budget a small
overrun is a **conditional** candidate, not a dropout. And never cut a **well-rated / strongly
recommended** candidate on price alone before checking its obtainable price — that is exactly the
error that ends in recommending junk instead of a good product that was within reach.

**Record the rejection reason for every dropped candidate** (e.g. "over budget +40%", "missing
must-have: weight < 1.3 kg", "discontinued"). These reasons go into the report ("Considered but
rejected") — they show breadth and protect against silently skipping something good.

**Collapse suspected rebadges.** In cheap categories (Chinese electronics, accessories) many
"different" products are the same OEM under different brands. If several longlist items look like
the same design (same photos/spec), pick **one representative** (preferably the cheapest with easy
returns) instead of wasting a deep-dive slot on a duplicate — and confirm/refute the relation in the
dossier.

If fewer than 5 candidates remain after screening — loosen the least important soft criterion or go
back to Stage A for more. If more than 8 — narrow, prioritising the most promising by the
highest-weighted criteria.

## Stage C — Parallel deep dives (one subagent per candidate)

This is the core of the mechanism against "the first one that looks fine". For **every** shortlisted
candidate launch a **separate subagent** (Sonnet) that examines it **to the same depth** from one
template. Launch them **in parallel** (several `Agent` calls in one turn), so all get equal attention
and it is faster.

**The subagent contract is in `${CLAUDE_PLUGIN_ROOT}/skills/shopping-research/references/deep-dive-agent.md`**
— read that file and use it as the brief, inserting the product name and the full spec. Each
subagent returns a standardised **dossier**: current PL price (min. 2 sources), offer links per
shop, spec/features relevant to the criteria, strengths (with evidence), weaknesses and typical
complaints from reviews, reliability/long-term opinions, who it is (not) for, availability in Poland,
warranty/service, hidden costs, a rating against each criterion, dated sources, and gaps (what could
not be established).

When the item is already **known** (a specific SKU or an unambiguous technical spec) and the whole
value lies in the channel, price, availability and shipping cost — a bill of materials, restocking,
a basket of many items — use the sister contract
`${CLAUDE_PLUGIN_ROOT}/skills/shopping-research/references/sourcing-agent.md` instead.

**Robustness (matters in practice):**
- **Frame the brief as a research task, not a role-command.** "You are X, start immediately, don't
  ask for confirmation, load the tools" is sometimes read by the subagent as prompt injection → it
  refuses or delegates instead of searching. A neutral "this is a research task, return the dossier
  as your final answer" (as in the reference) works more reliably.
- **Don't give a query limit — give a budget, a coverage list and an anti-hang rule** (details: the
  `web-search` skill, section 3). An old "max ~8 searches" was meant to protect against the watchdog
  (~10 min), but the model read it as "after the eighth, draw a conclusion" — and that is how a false
  negative was produced ("code DOES NOT EXIST" after exactly 8 searches; the product was in the
  manufacturer's catalogue and in Polish shops). The watchdog is held off by the **anti-hang rule**
  (no fetch longer than ~15 s; 403/CAPTCHA → skip immediately, no retry), not by a counter. In the
  brief: soft budget ~20 actions, ceiling ~35, a coverage list to tick off and a duty to report usage.
- **Handle stragglers without blocking the whole:** if a subagent died or returned a placeholder —
  relaunch it (with the lead it managed to find) or, if it repeats the problem, **research that one
  product yourself** via `WebSearch`/`WebFetch`. Don't leave a hole — the comparison is only as good
  as the weakest dossier.
- **A negative from round 1 is not a result — it is an order for round 2.** If a dossier says "not
  available / does not exist / the manufacturer doesn't offer it" — especially at low budget usage
  and incomplete coverage — **don't copy it into the report**. Launch a **catalogue probe** subagent
  (section 4 of the protocol: manufacturer's sitemap, the search on its site, PDF price list) and
  rule on it yourself. That is how a product was found that a subagent had declared "DOES NOT EXIST.
  Independently confirmed" — at the cost of one loop over `product-sitemap*.xml`.

Collect all dossiers before you start judging. **Only now** may you compare. If a deep dive reveals
that two candidates are the same OEM under different brands (rebadge), **treat them as one position**
and point to the cheapest/safest purchase channel.

## Stage D — Scoring matrix (ranking from priorities, not gut feeling)

Build a **comparison matrix**: candidates × criteria from the spec. Score **each candidate on each
criterion** (scale 1–5 or 0–10) with a one-sentence justification from the dossier. Compute a
**weighted score** using the spec's weights.

The ranking follows **the user's priorities**, not your hunch — another safeguard against favouring
the first candidate. But treat the number as **decision support, not an oracle**: a deal-breaker or a
serious risk from Stage E can demote a product despite a high score. Avoid false precision (don't
decide the ranking by 0.1 points — if two candidates are neck and neck, say so).

## Stage E — Red-team the top candidates

For the **2–3 highest-scored**, actively look for reasons **NOT** to buy them. This reversal of
perspective catches problems invisible in enthusiastic reviews:
- Typical failures, serial defects, problems after longer use (search "X problemy", "X awaria",
  "X po roku", "X reklamacja", "X problems", "X after a year").
- Hidden/running costs (consumables, accessories, subscriptions, expensive service).
- Is there an obvious better alternative at a similar price that we missed? (if so — add it, going
  back to analysis if needed).
- Does the "winner" really win, or only because it had better SEO / more sponsored reviews?

**Before concluding "quality is a lottery, buy the cheapest returnable one" — first check whether the
well-rated / strongly recommended option is NOT actually within reach** (via a discount code, a deal,
another channel or a small overrun of a soft budget). Very often it is — and then **it** wins, not the
budget rebadge. Only **when the best-rated option is genuinely out of reach within the criteria**,
and the whole reachable shelf is cheap, heavily rebadged products with high quality variance — shift
the weight of the assessment: **ease of return/complaint and channel reliability become more important
than small differences in marketing specs** (because you can't predict whether you'll get a faulty
unit). Then: (a) prefer a seller with hassle-free returns, (b) list 2–3 make-or-break things to
**test within the return window**, (c) consider "pay up for the next tier" instead of two failed
cheap purchases. **Don't recommend a poorly rated product just because it is cheap and returnable if a
well-rated one is within reach of the obtainable price** — that is exactly the trap this skill has
already fallen into once.

If the red-team overturns the ranking — update it. Better to reorder now than to recommend a faulty
product.

## Stage F — Presenting the results

**⛔ "Fire-and-forget" completeness gate (before you show anything):** run the **diligent-buyer
test** — *if a determined buyer spent 10 minutes on Pepper.pl, Amazon.pl and Ceneo, would they find
something clearly better, cheaper or better rated that is missing from my ranking?* If there is even
a shadow of "yes" — **go back** to the longlist / screening / price research and close the gap
**before** presenting the report. The point of this skill is that the user **doesn't have to** do
this themselves; if they did and found something better, the skill has failed. This is the
mandatory, reinforced version of the red-team question about the "missed better alternative".

Present the result using the template below. Ranking **from most to least recommended**. Be
specific, honest about flaws, and always give prices and sources.

**Every recommended product has a link to an offer you can click and buy** — including the
alternatives in "When to choose differently". The report ends in a purchase, so a shop name without
a URL ("x-kom", "Amazon.pl") makes the user search for the product a second time, and the shop will
often show them a different colour or capacity than the one researched. The link goes to the
**product page in the researched variant** (full URL, e.g. `amazon.pl/dp/<ASIN>`, an Allegro offer
with its number), not to the home page or search results. **Several shops** when they differ in
something that changes the decision (cheapest with a code vs without, faster delivery, easier
returns, official distributor with a Polish warranty); one when the others are simply more expensive.
Shop links live in "Where to buy", reviews and tests in "Sources"; mixed in one field they get lost.

```markdown
# 🛒 Shopping research: [category]

**What we looked for:** [1–2 sentences summarising the spec: use case, budget, key criteria]
**Examined:** [N] candidates → shortlist [M] → the ranking below. *(Polish market, prices as of [date])*

## 🏆 Ranking

### 1. [Product name] — [best real price] at [[shop](offer URL)] ⭐ BEST CHOICE
**Who it's for:** [one-sentence verdict — who this is the best option for]
**➕ Pros:** [specific, by criteria]
**➖ Cons:** [honestly — every product has some]
**Key features:** [relevant to the criteria]
**🛒 Where to buy:**
- [[Shop](full URL of the product page in this variant)] — [price] [+ code / shipping / availability, if they change anything]
- [[Another shop](URL)] — [price] · [how it differs: e.g. no code, but next-day delivery / easier returns]
**Price:** observed range [...] · **Shop rating:** [stars/count] · **Weighted score:** [...] · **Hidden costs:** [...] · **Warranty:** [...]
**Sources:** [links to the reviews/tests the pros and cons rest on]

### 2. [Name] — [price] 🥈 [e.g. BEST VALUE]
[as above]

### 3. [Name] — [price]
[as above]

## 📊 Comparison table
| Criterion (weight) | Product 1 | Product 2 | Product 3 |
|--------------------|-----------|-----------|-----------|
| [criterion] | [score/note] | ... | ... |
| **Price** | ... | ... | ... |
| **Weighted score** | ... | ... | ... |

## 🎯 Verdict
**Why #1 and not #2:** [specific justification based on the user's criteria]
**When to choose differently:**
- If [lower budget / you mainly care about X] → **[[alternative](offer URL)]** — [price]
- If [another scenario] → **[[alternative](offer URL)]** — [price]

## ❌ Considered but rejected
- **[Product]** — [reason: over budget / missing must-have / discontinued / poor reliability]

## ⚠️ Verify before buying
- [Risks, data gaps, things to check — e.g. "confirm the current price, promotions come and go", "check availability of variant X"]

## ✅ What I checked so nothing better slipped through
- [Short "fire-and-forget" evidence: which price channels (Amazon/Allegro/Ceneo/manufacturer), whether I looked for codes/promotions/deals (Pepper), whether I checked ratings — so the user knows they won't find better themselves]
- **Negative verdicts** (if the report contains any): [exactly which grade — "I didn't find it" / "none of the checked shops has it in stock: [list, date]" / "not in the manufacturer's catalogue: [link to sitemap/price list + page title]"]

## 🔗 Sources
[List of key sources with dates]
```

---

## Saving the result

If the project keeps shopping research notes (its `CLAUDE.md` says where), **create a note** there
once the spec is accepted and **append the final report** when the research is done — it builds a
history of purchase decisions to come back to. When the research reveals a **durable preference**
(consistently excludes a brand, prioritises silence/weight, buys only with door-to-door warranty),
record it in the project's memory the way its `CLAUDE.md` describes. Without such places, the report
stays in the conversation.

## Guiding principles (reminder)

- **Honesty over enthusiasm.** Every product has flaws — if you don't see them, you searched too
  shallowly. You don't sell, you advise.
- **Always prices, offer links and sources, always current — and actively hunt the best real
  obtainable price** (codes, channels, deals); don't stop at the first/catalogue one. Cross-check in
  ≥ 2 sources, flag promotions and fluctuations, mark data that may be stale. **Before cutting a
  candidate for budget — check whether you can buy it cheaper (code/channel/deal).**
- **Breadth before judgement.** The longlist and the parallel deep dives exist so the ranking isn't a
  lottery of first hits. Don't shorten the funnel.
- **A blocking gap → ask (in Phase 1).** If while building the spec you hit something only the user
  knows that really changes the direction of the research — ask before you start. In Phase 2 you act
  autonomously within the accepted spec.
- **"I didn't find it" ≠ "it doesn't exist".** Don't present an absence to the user as a fact until
  you have touched the primary source (catalogue / sitemap / manufacturer's price list). "I didn't
  find it" is reversible and cheap — the user keeps looking; "it doesn't exist" is irreversible and
  expensive — it closes the topic and makes them buy a worse variant. The same asymmetry as the price
  guard in Stage B. Protocol: the `web-search` skill.
- **When something doesn't work — change the engine, not the wording.** Exa (semantic) catches what
  `WebSearch` misses; the browser gets in where everything else gets a 403; `curl` reads catalogues
  and PDFs that `WebFetch` can't. A third rewording of the same query in the same search engine is
  wasted budget.
