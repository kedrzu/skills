# Subagent contract — deep dive into one product

This file is the brief template for the Stage C subagent (deep dives). The main agent reads this
file, inserts **one product** and **the spec**, and launches a subagent on Sonnet (`Agent`,
`model: "sonnet"`, `subagent_type: "general-purpose"`). One subagent = one product. Launch them all
in parallel.

The point: every shortlisted candidate is examined to **the same depth** using **the same template**,
so the comparison is like for like and the last candidate gets as much attention as the first. It is
a structural safeguard against favouring the first product found.

---

## Prompt template for the subagent

> This is a **research task**: research one product for a shopping comparison. Examine **one**
> product thoroughly and return a structured dossier. Take a sceptical (not a sales) stance —
> especially look for **flaws, risks and hidden costs**. You don't compare with others and you don't
> recommend — you describe facts and opinions with sources.
>
> **Product:** [full name + variant]
> **Market:** Poland, prices in PLN (unless the spec says otherwise).
> **Purchase context (the user's spec):** [paste the use case, budget, must-haves, weighted criteria, deal-breakers]
>
> **How to work:**
> - **Do the research yourself and return the dossier as your final answer.** Don't delegate it, don't
>   start background subtasks, don't reply "I'll take care of it" — hand in the finished dossier in
>   this answer.
> - **Tools:** load them via `ToolSearch` with the query
>   `select:mcp__exa__web_search_exa,mcp__exa__web_fetch_exa,WebSearch,WebFetch,Bash`. **Start
>   searching with Exa** — it is semantic (you describe the ideal page in a full sentence; `objective`
>   is required) and reaches niche Polish shops and specific variant codes where `WebSearch` silently
>   swaps the code for a neighbouring one. `Bash` is **essential**, not optional: `WebFetch`
>   summarises and loses XML content, and returns binary garbage on PDFs — catalogues, sitemaps and
>   price lists you take via `curl` + `grep` / `pdftotext` (or `curl -s https://r.jina.ai/<pdf-url>`).
>   Search from many angles: editorial reviews (PL + EN), tests, user opinions, forums/Reddit,
>   **Pepper (pepper.pl — comments/recommendations, also on expired deals)**, shop pages,
>   complaints/problems.
> - **You must load the `web-search` skill** (`Skill` with `skill: "web-search:web-search"`) — the
>   web research protocol, binding in full. Three rules that apply even if loading fails: (1) **you
>   never conclude that something does not exist** — see below; (2) in `WebSearch` a code/SKU always
>   goes in quotes, and a shop via `site:`, not as a word in the query; (3) 403/CAPTCHA → skip the
>   host immediately, no retry.
> - **Budget and coverage instead of a query counter.** Soft ~20 actions, ceiling ~35 — but the
>   stopping criterion is **coverage**, not a number: ≥ 2 independent price channels, ≥ 1 source of
>   user opinions, ≥ 1 deliberate query about flaws, the manufacturer's page. What you didn't tick
>   off → "Gaps", not a conclusion. **Anti-hang rule:** no fetch longer than ~15 s, a blocking host
>   without retry — that is what protects the session from the watchdog (~10 min), not saving
>   queries. Mark undetermined fields "n/a".
> - **You may not conclude that a product/variant/code does not exist.** If you can't find it —
>   return **`UNRESOLVED`** + a lead: what exactly you searched for, which **neighbouring codes** you
>   saw, the manufacturer's domain, the product URL pattern you noticed. The main agent settles it
>   with a catalogue probe. A shop saying "this variant is not available" is information about **one
>   shop**, never about the manufacturer — if you quote it, name the shop.
> - **Hunt the best real obtainable price** (don't stop at the first/catalogue one): compare the main
>   channels (Allegro / Ceneo / Amazon.pl / the manufacturer's shop — prices often differ a lot
>   between them), **check active discount codes and current promotions** (including Pepper/pepper.pl
>   as an aggregator of codes and deals; the historical low as the reference for "is this a good
>   price now"). Return **two numbers: the observed range** and **the best real price obtainable
>   today** (channel, any code, date). Count cost **symmetrically** — up (shipping, duty/VAT on
>   import) **and down** (codes, promotions). Note: the manufacturer's "regular price" is often
>   **artificially inflated** — don't use it as the reference. **Amazon often doesn't render for
>   `WebFetch`** — then take price/ratings from search snippets, Ceneo/comparators or a reseller and
>   **mark it as not verified directly**.
> - **Collect the shop rating**: stars + number of reviews (Amazon/Allegro/Ceneo) and forum/Trustpilot
>   sentiment. Distinguish **complaints about hardware quality** from **complaints about
>   service/shipping/returns** — they are different risks (the product can be good and the shop poor,
>   and vice versa).
> - Look for flaws deliberately: queries like "[product] problemy", "[product] awaria",
>   "[product] po roku", "[product] wady", "[product] reklamacja", "[product] problems".
> - **Check whether it's a rebadge**: many products in cheap categories are the same OEM sold under
>   different brands (same photos, identical spec, same failure pattern). If so — note it and point to
>   where the same design is cheaper. That saves real money.
> - Separate facts (spec, price) from opinions (reviews) and give a source for every significant claim.
> - Be honest about uncertainty: if something couldn't be established, write it under "Gaps".
>
> **Return exactly this structure (Markdown):**
>
> ```markdown
> ## [Product name + variant]
>
> - **PL price:** observed range [range] · **best real obtainable price:** [amount] at [channel] (+ code [which], checked: [date]); [min. 2 sources; mark if not verified directly]
> - **Offers (where to buy):** one line per channel with a price — `[shop](full URL of the product page in this variant) — [price] — [code / shipping / stock, date]`. The URL is the offer page (e.g. `amazon.pl/dp/<ASIN>`), not the shop's home page or a search result: it goes straight into the report, so the user can click and buy exactly this variant.
> - **Budget and coverage:** [N actions] · ticked off: [price channels / opinions / flaws / manufacturer's page] · **missing:** [list] · verdicts: [none | UNRESOLVED: (lead)]
> - **Shop rating:** [stars + number of reviews, source] — [complaints mainly about hardware or about service/shipping?]
> - **Availability in Poland:** [easy to get or not / variants]
> - **Key features/spec** (relevant to the user's criteria): [list]
>
> **➕ Strengths** (with evidence/sources):
> - [strength] — [source]
>
> **➖ Weaknesses and typical complaints** (from reviews/forums — be specific):
> - [flaw / frequent complaint] — [source]
>
> **🔧 Reliability / long-term opinions:**
> - [failure rate, durability, "after a while" opinions, serial defects if any]
>
> **💸 Hidden / running costs:**
> - [consumables, accessories, subscriptions, expensive service — or "none significant"]
>
> **🛡️ Warranty / service:** [length, terms, service quality if known]
>
> **🎯 Ideal for / NOT for:**
> - Ideal for: [...]
> - Not recommended if: [...]
>
> **📐 Rating against the user's criteria** (one sentence per criterion from the spec):
> | Criterion | How it does | Note |
> |-----------|-------------|------|
> | [criterion 1] | [e.g. very well / poorly] | [why, with source] |
>
> **🔗 Sources:** [links with access date]
>
> **❓ Gaps / what couldn't be established:** [honestly]
> ```
>
> Return only this dossier — the main agent will put it side by side with the others.

---

## Notes for the main agent when assembling the brief

- Insert the **full, specific name + variant** (e.g. "Bosch Serie 6 WGG2440 EU 9 kg", not just
  "Bosch"). An ambiguous name = the subagent researches a different product.
- Paste the **real spec** (weighted criteria), so the "Rating against criteria" section hits the
  mark — without it the subagent rates by its own lights.
- Launch **all shortlist subagents in one turn** (in parallel), not one after another — equal
  attention + faster.
- **Frame the brief as a research task, not a role-command.** Avoid "You are X, start immediately,
  don't ask for confirmation" — that tone is sometimes read by the subagent as prompt injection and
  ends in a refusal or delegation instead of research. A neutral "this is a research task, return the
  dossier as your final answer" works more reliably.
- **Handle stragglers.** A subagent may die (the watchdog kills long, hanging sessions at ~10 min) or
  return a placeholder instead of a dossier. Then: relaunch it (with any lead it found) or — if it
  repeats the problem — **research that one product yourself**, with the main model, via
  `WebSearch`/`WebFetch`. Don't leave a hole: the comparison is only as good as the weakest dossier.
- **Collapse rebadges.** If dossiers reveal that two models are the same OEM platform under different
  brands, don't rate them separately as two products — treat them as one position and point to the
  cheapest/safest purchase channel (and flaws reported for one brand apply to the other).
- Once you have the dossiers: **don't trust them blindly** — if one is shallow or has many "Gaps" in
  important places, fill in yourself or relaunch the subagent with a narrower instruction.
- **Read the "Budget and coverage" field as a premature-conclusion detector.** A dossier with a
  negative verdict at low usage and incomplete coverage is **not a result but a signal** that the
  subagent stopped too early (a real case: "DOES NOT EXIST" after 8 searches and 3 fetches — the
  product was in the manufacturer's catalogue and in Polish shops).
- **For every `UNRESOLVED`, launch round 2 — a catalogue-probe subagent.** Brief: one narrow goal
  ("does code X exist in [manufacturer]'s catalogue"), the same tools, the procedure from section 4 of
  the protocol (robots.txt → `sitemap_index.xml` → sub-sitemaps → grep for the code **family**
  pattern → URL probe calibrated with a dummy → the manufacturer's on-site search → PDF price list).
  The session is short, so the watchdog stays calm — and this round is the one that decides.
