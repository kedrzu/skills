# Primary-source probe

The procedure that earns the right to say **"the manufacturer does not offer this"**
(grade N3 in `SKILL.md` § 2). Everything else — shops, aggregators, search-engine
summaries — can only support N1 or N2.

The idea is simple: stop asking intermediaries what the catalog contains and read the
catalog. Most sites publish it in machine-readable form without meaning to.

## When to run it

- a research subagent came back `UNRESOLVED`
- you are about to rule N2 or N3
- you are chasing a variant, size or version that resellers do not stock
- the search engine is visibly substituting your code for a neighbouring one
- the user brought a link to the manufacturer and you need the surrounding family

Budget: 1–3 minutes. Run it as its own short subagent turn with one narrow goal, rather
than extending an already long session.

## 1. `robots.txt` → sitemap

```bash
curl -s https://<domain>/robots.txt | grep -i sitemap
```

Almost every manufacturer or shop on WordPress, Shopify or PrestaShop advertises
`sitemap_index.xml` there.

## 2. Expand the index — do not guess the numbering

```bash
curl -s <sitemap_index_url> | grep -o '<loc>[^<]*</loc>'
```

One real case had 92 separate `product-sitemap*.xml` files. A `seq 1 N` loop also works,
but it guesses the range and silently misses maps outside it.

Use `Bash` + `curl` + `grep` here, never `WebFetch`: on XML, `WebFetch` summarises and
drops URLs — a sub-map can come back as a handful of image links with every product
missing.

## 3. Grep by code *pattern*, not by the full code

```bash
curl -s <sitemap_url> | grep -o '<loc>[^<]*</loc>' | grep -i 'PK-'
```

`PK-` instead of `PK-L-H53-550`. You get the whole family and **see which variants exist**
— a far stronger answer than yes/no for one code, and it usually reveals that the naming
scheme differs slightly from what you were given.

## 4. If the sitemap is empty, guess URLs — but calibrate the 404 first

Manufacturers use regular patterns: `/produkt/<CODE>/`, `/product/<code-lowercase>`,
`/Urun-Detay-End?id=<n>`.

**A 200 status on its own means nothing** — plenty of CMSes serve 200 along with a
"not found" page. So **always** fetch a deliberately nonexistent code in parallel and
compare **status + `<title>`**. Only the difference proves existence:

```
PK-L-H53-550 → <title>GTV ball-bearing slide, H53, L=550 mm, soft-close, 100 kg</title>
PK-L-H53-999 → <title>Page Not Found - GTV</title>        # calibration decoy
```

## 5. The site's own search

| Platform | Search URL |
|---|---|
| WordPress | `https://<domain>/?s=<code>` |
| Shopify | `https://<domain>/search?q=<code>` |
| PrestaShop | `https://<domain>/szukaj?controller=search&s=<code>` |

This finds what Google never indexed — and variant codes are exactly that category.

## 6. Catalog or price-list PDF

The strongest proof of existence you can get without picking up a phone. `WebFetch`
returns binary garbage for PDFs; two routes work:

```bash
curl -s "https://r.jina.ai/<pdf-url>" | grep -n -i "H53"          # Jina Reader, no key needed
curl -sL -o "$TMPDIR/cat.pdf" <pdf-url> && pdftotext -layout "$TMPDIR/cat.pdf" - | grep -n "H53"
```

Verified: a `GTV-Prowadnice.pdf` catalog through Jina yielded 40 KB of clean text with
the full code tables. Jina allows ~20 requests/min and bounces off Cloudflare-protected
hosts.

## Beyond product catalogs

The same move — *ask the source of truth, not an intermediary* — has an equivalent in
every domain. Pick the one that matches before ruling anything out:

| Question | Primary source |
|---|---|
| Does this package version exist? | the registry API (`registry.npmjs.org/<pkg>`, `pypi.org/pypi/<pkg>/json`), not a blog post |
| Does this API/parameter exist? | the official OpenAPI spec or reference docs, plus the changelog |
| Was this feature removed? | the changelog, release notes, or the commit/PR in the repository |
| Is this company/entity real? | the official register, not an aggregator listing |
| Does this paper/standard say that? | the PDF of the paper or standard itself |

## Recording the result

Write down, unambiguously: the family codes found, the link to the product page, the
**title of that page**, and the **title of the decoy page**. That record is what makes an
N3 verdict checkable by someone else — and without it, N3 is not available to you.
