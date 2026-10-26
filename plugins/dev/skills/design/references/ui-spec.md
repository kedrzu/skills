# UI specs

The user designs the UI, with a separate design agent — whichever one they use. Your job is a brief good
enough that they never have to re-explain the context to that agent.

**They say when.** There is no readiness test and no step you propose. This file is *how* to write it.

Why they ask shapes how you write it: seeing concrete screens is how they find out whether they actually
understand the design and whether it matches what they intended. A spec that hedges, or leaves the hard
states unnamed, wastes the exercise.

## One file per user path

`docs/design/<slug>/ui/<path>.md` — one path (`patient-reports-a-side-effect`), all its screens and
states. Per-path rather than per-screen, because what a user already knows when they arrive on a screen
is half the design problem.

**Generate it from the current state when asked; don't maintain it alongside.** Regeneration instead of
synchronisation — a parallel document always drifts. If they want it again after things moved, write it
again.

Self-contained: assume the design agent has never seen the design folder.

## What goes in it

- **Purpose** — what this path is for, and where the user is arriving from.
- **The user's task** — what they are trying to get done, in their terms.
- **Screens, in order** — and what happens on each.
- **What's on each screen** — data ordered by how much it matters. Say which single question the screen
  is answering; everything else is secondary.
- **States** — empty, loading, error, partial. Only the ones real for this path, and what the user should
  understand in each.
- **Failures that must be visible** — the cases the user has to be able to see and act on: a document
  whose date couldn't be read, an expired approval, a withdrawn consent.
- **Technical constraints** — what the design can't assume: what the backend can supply, real latencies,
  what arrives asynchronously.
- **Questions this design should settle** — the ones where the decision genuinely belongs to the visual
  work rather than to the model.

**No visual direction.** No layout, no components, no tone — that is their call and the design agent's
craft, and pre-empting it wastes both. Hi-fi directly; no lo-fi wireframe stage.

## While they're designing

If you want to change an assumption underneath a path they are currently designing, **say so**: "this
would invalidate the mockup you're working on — hold off?" Then they decide. Don't freeze the assumption
instead; everything here can change at any moment, and a freeze would leave you having to break one
instruction or the other.

## When the mockup comes back

Review it for **coverage and consequences**, not for whether it looks good.

- **Covered** — which decisions and requirements it satisfies.
- **Not covered** — what the path needs that it doesn't show.
- **New implications** — what it forces on the model, the API, or the data. This is the valuable part: a
  page count on screen means the API must supply one; grouping by date means the display date needs an
  unambiguous definition.
- **States not designed** — which of the above have no representation.

New implications become decisions in the design folder. They don't become another document.
