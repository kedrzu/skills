# Batch Strategy: Package Categorization

## Safe Packages (batch 5–15 together)

Group by ecosystem. These rarely cause issues.

### Cloud SDKs and infrastructure

- `@aws-sdk/*`, `@smithy/*`
- `@pulumi/*` — watch for duplicate trees when a submodule declares its own (SKILL.md, Phase 4)

### Type Packages

- `@types/*` (node, bun, etc.)

### Testing & Dev Tools

- `vitest`, `@vitest/*`
- `playwright`, `@playwright/*`
- `prettier`, `eslint` and plugins

### Build Tools

- `nx`
- `rollup`, `@rollup/*`
- `esbuild`

### Utility Libraries

- `lodash`, `date-fns`, `zod`, `nanoid`, `uuid`
- `effect`, `@effect/*`
- Crypto/encoding libs

### Backend Utilities

- `drizzle-orm`, `drizzle-kit` (batch together, but verify carefully)
- `hono`, `@hono/*`
- `ioredis`, `postgres`

### Monitoring & Logging

- `@sentry/*`
- `pino`, `pino-pretty`

### Payment & External APIs

- `stripe`

## Risky Packages (update one-by-one)

These frequently cause breakage or require migration.

### Vue Ecosystem

- `vue`, `vue-router` — often held by a root `overrides` entry; edit it too
- `@vueuse/*`
- `pinia`

### Nuxt Ecosystem

- `nuxt`, `@nuxt/*`
- `nitropack`
- `h3`, `@unhead/*` (transitive, but pinned in workspaces when a project needs them; coupled to
  Nuxt — check the notebook's General Rules)

### UI Component Libraries

- `@headlessui/*`, `@floating-ui/*`
- `tailwindcss`, `@tailwindcss/*`
- `postcss`, `autoprefixer`

### Vite

- `vite`, `@vitejs/*`

### TypeScript

- `typescript` — major version bumps are risky

### Packages that live in a git submodule of this repository

Their manifests land in a separate repository: commit and push there first, then record the pointer —
both through `git-workflow` **checkpoint**. A submodule workspace is shared, so its ranges follow
`library-mode.md`.

## Decision Tree

```
Is the package in docs/package_update.md?
├─ In General Rules? → Follow the rule (e.g., only update together with its coupled package)
├─ In Known Issues as known-broken? → Skip (check if newer version exists that might fix it)
└─ Not listed → continue below

Is it declared in a shared workspace (submodule or published)?
└─ Yes → library-mode.md decides whether its range moves at all; then continue below

Is the package in the "Risky" list above?
├─ Yes → Update alone, verify, commit separately
└─ No
   └─ Is it a major version bump?
      ├─ Yes → Check changelog for breaking changes
      │  ├─ Breaking changes → Treat as risky
      │  └─ No breaking changes → Add to safe batch
      └─ No → Add to safe batch
```
