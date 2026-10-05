# Conflict check

The question is not "does anything else use this word" — everything does — but **would a customer
or a court confuse us with them**. That depends on the space, so read the space from `BRIEF.md`
before searching.

## Severity

| Severity | Means | Example |
|-|-|-|
| `blocking` | Same or near-identical name, same or adjacent space, actively used. Drop the name. | "Streaks" for a habit app when Streaks is a top habit tracker. |
| `notable` | Same name in an unrelated space with real visibility, a sound-alike in the same space, a distinctive root shared with several small products in the same space, or a registered trademark in the relevant classes. The user should see it and decide. | "Loom" for a weaving shop; "Notch a Day" next to three tiny habit trackers called "Notch". |
| `noise` | Dead projects, tiny unrelated businesses, ordinary dictionary use. Record only if it could come up later. | A 2014 abandoned GitHub repo. |

Spelling variants count as the same name: "Lumen", "Lumin", "Loomen" collide when spoken aloud.

## Where to look

Pick what fits the space; the point is coverage of where a customer of *this* product would look,
not visiting every site.

- **The open web**, exact name plus the category ("Keepon" habit app). Exa first; quote the name.
- **App stores** for anything with an app. The App Store has a keyless JSON search that needs no
  browser: `curl 'https://itunes.apple.com/search?entity=software&limit=25&term=<name>'` (add
  `&country=pl` for a local store); `userRatingCount` tells a live app from an abandoned one.
  Google Play has no such API — web search with `site:play.google.com`, or browser automation.
- **Product Hunt** for software and startups.
- **GitHub and package registries** (npm, PyPI) for developer tools.
- **Trademarks**: EUIPO / TMview (`https://www.tmdn.org/tmview/`) for the EU, USPTO trademark search
  for the US. Both are JS-heavy; use browser automation, and when it is missing say the trademark
  check was not done rather than calling the name clean.
- **Company registries** when the name is for a company (KRS/CEIDG in Poland, Companies House in the UK).
- **Social handles** only when the user cares about them.

## Recording

Every conflict gets `who`, `space`, `severity`, `url` and `checked_at`. When you found nothing,
write an empty `conflicts` list *and* say in the round's log entry where you looked — "no conflict"
without the list of places is not evidence.
