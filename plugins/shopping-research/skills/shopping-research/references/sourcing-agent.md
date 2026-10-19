# Subagent contract — sourcing a known item (where to buy, for how much)

Sister contract to `deep-dive-agent.md`. That one answers **"which product to choose"**. This one
answers **"where to buy what has already been chosen, and what it really costs with delivery"**.

Use it when the item is **known** (a specific SKU or an unambiguous technical spec) and the whole
value of the research lies in the channel, price, availability and shipping cost. Typically: a
project's bill of materials, restocking, assembling a basket of many items.

The main agent reads this file, inserts **one group of items** and launches a subagent on Sonnet
(`Agent`, `model: "sonnet"`, `subagent_type: "general-purpose"`). Launch groups in parallel, but **in
waves of ~6** — keyless Exa has undocumented limits and a dozen parallel sessions can produce 429s.

**Group items by candidate shop, not by their function in the project.** The point of sourcing is
minimising the number of shipments, so a subagent that gets "all the screws and confirmat screws" at
once can find one shop for the lot. A subagent that gets a single screw won't see that.

---

## Prompt template for the subagent

> This is a **research task**: purchase sourcing for specific, already chosen items. You are not
> choosing a product and not recommending "better" alternatives — you are to find **where to buy
> exactly this** (or a full-fledged substitute, when the item is described generically), **for how
> much**, **at what delivery cost** and **whether it is in stock**. Return a structured table of
> sources. Sceptical stance: the price on the product list often differs from the one in the basket,
> and "available" is often "to order, 3 weeks".
>
> **Items to research:** [list: name/SKU + quantity + unit + technical notes from the BOM]
> **Market:** Poland, gross prices in PLN.
> **Deliver to:** [postal code + city] — the shipping cost **is part of the result**, not a footnote.
> **Project context:** [what it's for, what has to fit, what must not be substituted]
>
> **How to work:**
> - **Do the research yourself and return the table as your final answer.** Don't delegate further,
>   don't start background subtasks, don't reply "I'll take care of it" — hand in the finished result
>   in this answer.
> - **Tools:** load them via `ToolSearch` with the query
>   `select:mcp__exa__web_search_exa,mcp__exa__web_fetch_exa,WebSearch,WebFetch,Bash`.
>   **Start searching with Exa** — it is semantic (you describe the ideal page in a full sentence,
>   `objective` is required) and reaches the long tail of Polish shops and specific variant codes
>   where `WebSearch` silently swaps the code for a neighbouring one. `Bash` is **essential**, not
>   optional: `WebFetch` summarises and loses XML, and returns binary garbage on PDFs — price lists,
>   catalogues and sitemaps you take via `curl` + `grep` / `pdftotext` (or
>   `curl -s https://r.jina.ai/<pdf-url>`).
> - **You must load the `web-search` skill** (`Skill` with `skill: "web-search:web-search"`) — the web
>   research protocol, binding in full. Three rules that apply even if loading fails:
>   (1) **you never conclude that something does not exist** — see below; (2) in `WebSearch` a
>   code/SKU always goes in quotes, and a shop via `site:`, not as a word in the query; (3)
>   403/CAPTCHA → skip the host immediately, no retry.
> - **SKIP ALLEGRO.** Allegro returns 403/CAPTCHA to `WebFetch`, `curl`, Jina **and** Exa's crawler,
>   and the only way in (browser automation) is reserved for the main agent, because it is one shared
>   browser. Your job: collect **prices outside Allegro** and a **list of names/SKUs to check on
>   Allegro** in the "For the Allegro sweep" section. Don't guess Allegro prices from snippets.
> - **Budget and coverage instead of a query counter.** Soft ~20 actions, ceiling ~35 — but the
>   stopping criterion is **coverage**, not a number:
>   **≥ 3 independent shops with price and shipping cost**, **≥ 1 availability confirmation** (stock
>   level or lead time), **≥ 1 touch of the manufacturer's page** (that the SKU/spec matches).
>   What you didn't tick off → "Gaps", not a conclusion. **Anti-hang rule:** no fetch longer than
>   ~15 s, a blocking host without retry — that is what protects the session from the watchdog
>   (~10 min), not saving queries. Mark undetermined fields "n/a".
> - **You may not conclude that a product/variant/code does not exist.** If you can't find it — return
>   **`UNRESOLVED`** + a lead: what exactly you searched for, which **neighbouring codes** you saw, the
>   manufacturer's domain, the product URL pattern you noticed. The main agent settles it with a
>   catalogue probe. A shop saying "this variant is not available" is information about **one shop**,
>   never about the manufacturer — if you quote it, name the shop.
>
> **Sourcing-specific rules — this is where all the value lies:**
> - **Total cost, not shelf price.** For each shop give: gross unit price, price for the given
>   quantity, **shipping cost to the given address**, **free-shipping threshold**, and **the total to
>   pay**. A shop 8% cheaper with 35 PLN shipping on a single item usually loses — show it with a
>   number, not intuition.
> - **Size decides shipping.** Check whether the item fits a parcel locker. Anything longer than
>   ~60 cm (drawer runners, profiles, pipes, trims) goes by oversize courier and often costs 30–80 PLN
>   extra, and some shops refuse to ship it at all. Say so explicitly.
> - **Bulk packs.** For large quantities (screws, confirmat screws, dowels) check prices per
>   100/250/500/1000 pcs and **convert to a per-piece price**. A bulk pack can be cheaper than the
>   needed quantity bought individually. State how many packs are actually needed and how many spares
>   remain.
> - **Quantity thresholds and wholesale.** For an order worth hundreds of PLN in one item, check
>   whether the shop has a wholesale price list, a quantity discount or a B2B enquiry option. Note it,
>   even if it requires contact.
> - **Substitutes for generic items.** When the BOM describes an item by features ("steel angle
>   40×40×2, 2 holes", "screw 4×16 head Ø8"), give **a specific product with a link**, not a category —
>   with confirmation that the dimensions match. Where a feature is critical (countersunk vs pan head,
>   length, thread), say plainly whether the product found meets it or only "probably".
> - **Availability with a date.** "In stock" without a reading date is worthless. Give the stock
>   status and the date; where the shop shows a piece count — record the number, because with large
>   quantities that can be the blocker.
> - **Seller credibility** — briefly: an industry shop with an address and tax ID, or a random
>   marketplace. Don't elaborate; this is sourcing, not a review.
>
> **Return exactly this structure (Markdown):**
>
> ```markdown
> ## Sourcing: [group name]
>
> ### Sources (best first)
>
> | Item | Product (specific) | Shop | Link | Unit price | Qty | Total | Shipping | Free from | Size | Availability (date) |
> |---|---|---|---|---|---|---|---|---|---|---|
> | [BOM item] | [full name + SKU] | [shop] | [url] | [PLN] | [n] | [PLN] | [PLN] | [PLN] | [parcel locker / oversize courier] | [stock, YYYY-MM-DD] |
>
> ### Best basket for this group
> - **[Shop X]** — all/some items: [goods total] + [shipping] = **[total]**
> - Alternative: [Shop Y] — [total], makes sense only if [condition]
> - What this shop does NOT have: [list of items to buy elsewhere]
>
> ### For the Allegro sweep (the main agent checks it in the browser)
> - `[exact search phrase / SKU]` — price outside Allegro to beat: [PLN], expected variant: [description]
>
> ### Technical notes
> - [discrepancies with the BOM spec, fit risks, things to verify before ordering]
>
> ### Budget and coverage
> - [N actions] · ticked off: [shops with price and shipping / availability / manufacturer's page] · **missing:** [list]
> - verdicts: [none | UNRESOLVED: (lead)]
>
> ### Gaps
> - [what honestly couldn't be established]
> ```
>
> Return only this structure — the main agent will combine it with the other groups.

---

## Notes for the main agent

- **Insert the full item spec from the BOM, including notes.** The "notes" column of a bill of
  materials often holds a fit condition ("no longer — the box side is 16 mm", "countersunk head on the
  bearing side") without which the subagent buys something that doesn't fit. The subagent doesn't
  inherit your context.
- **Give the delivery postal code.** Without it the shipping cost is fiction, and that is half the
  result.
- **Don't send subagents to Allegro.** The browser is one shared instance; parallel sessions collide.
  You sweep Allegro yourself, **serially**, after collecting the "For the Allegro sweep" lists from
  all groups.
- **Consolidating the basket is your job, not theirs.** Each subagent optimises its group; only you
  see that items from three groups are in one shop and together pass the free-shipping threshold.
  Treat it as a **basket problem** (goods total + shipping total), not as 30 independent minimums.
- **Read "Budget and coverage" as a premature-conclusion detector.** A group with a negative verdict
  at low usage and incomplete coverage is a **signal** that the subagent stopped too early, not a
  result.
- **For every `UNRESOLVED`, launch round 2 — a catalogue-probe subagent** (section 4 of the protocol:
  robots.txt → sitemap_index → sub-sitemaps → grep for the code family pattern → URL probe calibrated
  with a dummy → manufacturer's search → PDF price list). N2/N3 verdicts are yours alone, after the
  probe.
- **Handle stragglers.** A subagent may die on the watchdog (~10 min) or return a placeholder. Then:
  relaunch it with the lead, and after a second failure research that group yourself. A shopping list
  with a hole is not a list.
