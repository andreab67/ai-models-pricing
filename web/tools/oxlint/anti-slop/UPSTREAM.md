# anti-slop provenance

The Oxlint JS plugin vendored under this directory is owned and configured by this
repository. Update both `oxlint` and `@oxlint/plugins` together; the plugin imports
the plugin runtime from `@oxlint/plugins`.

## Source identity

- Upstream repository: <https://github.com/dmmulroy/anti-slop>.
- Upstream commit: `c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b` (resolved by the
  installer bundle at
  `hermes-vps/skills/install-anti-slop/UPSTREAM.md`).
- Source directory in upstream bundle:
  `skills/install-anti-slop/assets/anti-slop/`.
- Bundled by: `node hermes-vps/skills/install-anti-slop/scripts/install.mjs`
  (no `--force`; no prior copy existed at this destination).
- Reviewed/installed: 2026-10-10.

## Installed entry points

- Generic plugin: `web/tools/oxlint/anti-slop/index.ts`.
- Effect plugin (opt-in; not enabled in this repo): `web/tools/oxlint/anti-slop/effect/index.ts`.
- Generic rules: 17 implementations under `web/tools/oxlint/anti-slop/rules/`,
  backed by `external_javascript` helpers in `web/tools/oxlint/anti-slop/shared/`.
- Vendored `react-hooks/exhaustive-deps`-style padding rule from
  `eslint-stylistic/eslint-stylistic` at commit
  `435c3ea0fd26a5fef9042c4b36b6e165fbbf8d08`
  (provenance in `web/tools/oxlint/anti-slop/vendor/eslint-stylistic/UPSTREAM.md`,
  `LICENSE` retained verbatim).

## Dependencies

- `oxlint` devDependency pinned to `1.87.0`.
- `@oxlint/plugins` devDependency pinned to `1.87.0` (matches `oxlint`).
- Both installed via npm alongside the existing `web/package.json`; no range
  introduced, no other dependency ranges rewritten.

## Configuration

- Generic config: `web/oxlint.config.ts`.
- `ignorePatterns` keeps every existing application target out of lint scope
  (`.next/**`, `node_modules/**`, AI tooling directories, the vendored plugin
  tree) and does not blanket-ignore dot-directories.
- `jsPlugins`: `./tools/oxlint/anti-slop/index.ts` (generic). Effect plugin not
  registered — this repository has no `effect` dependency in any package manifest.
- `rules`: every generic anti-slop rule at `"error"`, plus the native companion
  `oxc/no-accumulating-spread` at `"error"`. No rules disabled.

## Intentional deviations from the skill's recommended layout

- The skill's default recommends adding Oxlint alongside ESLint. This
  repository explicitly migrated fully from ESLint to Oxlint (user
  authorization): `eslint ^9` and `eslint-config-next ^16.4.0` were removed,
  `web/eslint.config.mjs` was deleted, and the `lint` script in
  `web/package.json` now runs `oxlint .`. Core-web-vitals rules bundled with
  `eslint-config-next` are no longer enforced.
- `web/eslint.config.mjs` is removed; `web/oxlint.config.ts` is its replacement.

## Verification

- `npm run typecheck` (`tsc --noEmit`) in `web/`: passes.
- `npm run lint` (`oxlint .`) in `web/`:
  - `--fix` applied: 80 `require-readable-spacing` whitespace violations
    auto-fixed across two passes; second pass stable (no new findings).
  - Final state: 0 anti-slop errors. One informational warning from a
    non-anti-slop default rule (`eslint/no-unused-vars` for a pre-existing
    `usedColor` binding in `src/components/AccountBalances.tsx` — that
    variable existed before the migration and is outside the anti-slop scope).
  - One Node ESM-typeparse hint for `oxlint.config.ts` (performance only;
    adding `"type": "module"` to `package.json` was avoided because it would
    change module resolution for the rest of the project).
- `node_modules` lockfile updated via `npm install` and `npm uninstall`; no
  unrelated changes to `package-lock.json` dependency ranges.

## Application-level fixes applied to satisfy the strict rules

These were application-domain changes, not lint-policy changes; each is the
smallest change that satisfies the rule without weakening severity or
laundering types:

- `no-runtime-typeof`: enabled the rule's built-in `allowInTypeGuards: true`
  option in `web/oxlint.config.ts` and refactored the runtime type checks in
  `web/src/lib/api.ts` to live inside TypeScript user-defined type guards
  (`isString<T>`, `isErrorMessageCarrier<T>`, `isApiErrorBody`) so the
  consumer code branches on the parsed domain value (`is Error`,
  `is { message?, statusText? }`) rather than on a runtime representation.
- `no-unknown-parameters`: replaced the two `unknown` parameters in
  `web/src/lib/api.ts` (`isNotExposed`, `errMsg`) with a named domain type
  (`ThrownValue`) plus, for `isNotExposed`, a type predicate return
  (`error is ApiError`) that lets callers narrow the SWR error in place.
- `no-known-value-widening`: replaced the `Record<string, string>` annotation
  on `CHANNEL_LABEL` in `web/src/components/ModelDetailModal.tsx` with
  `satisfies Record<Channel, string>`, keeping inference of the literal key
  set while validating the contract.
- `require-safety-comment-for-type-assertion`: added `SAFETY:` comments before
  every type assertion that remains (`fetcher<T>`, the two internal object
  reads inside the new type predicates, the `document.activeElement` narrowing
  in `ModelDetailModal`, and a new explicit one inside the `isApiErrorBody`
  body). The page-size button group no longer needs an `as` cast — TS infers
  the literal array type directly.

## Updating

Follow `hermes-vps/skills/install-anti-slop/references/update.md` rather than
re-running the installer into an existing copy. Preserve the four intentional
deviations above unless the repository re-adopts ESLint or another linter.