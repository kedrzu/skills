# Dependency Review: Signals of an Abandoned Package

The monthly full review of every direct dependency, for what the npm `deprecated` flag misses — it
only catches authors who bothered to set it.

## Signals

- An archived repository: `gh api repos/<owner>/<repo> --jq .archived`, the repo from
  `bun info <pkg> repository.url`.
- A README that says moved, renamed, unmaintained or looking for maintainers.
- Years without a release alongside unanswered security issues.

Age alone is no verdict — `lodash.merge` is finished, not dead.

## Families

Review large families as one unit — `@aws-sdk/*`, `@smithy/*`, `@types/*`, `@sentry/*`,
`@pulumi/*`, `@tiptap/*`, `@storybook/*`, the Vue/Nuxt core. The question there is whether the
family moved to a new generation, as the AWS SDK did from v2 to v3, not whether each member is alive.

## Output

Each finding goes into `docs/dependency-health.md` in the entry format its lead paragraph defines,
with decision `pending`, and into the run report's **Needs your decision**. Never migrate.
