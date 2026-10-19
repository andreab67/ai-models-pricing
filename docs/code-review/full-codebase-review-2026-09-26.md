# Full codebase review — 2026-09-26

**Status:** fixes complete on the review branch; merge proposed, not merged. Pipeline verification was waived by the repository owner (this GitHub repository has no CI that runs; `.gitlab-ci.yml` only runs on a GitLab mirror).

| | |
|---|---|
| Repository | `andreab67/ai-models-pricing` (GitHub) |
| Target / base | `main` @ `acb676b743316ff71f44b11ca0be3030065c5ddf` |
| Review branch | `code-review/full-codebase-review-20260926-134704` |
| Isolation | Clean tree; review branch created from `origin/main` in place (no worktree needed) |
| Scope | `api/` (FastAPI, Alembic, jobs), `web/` (Next.js 15), `k8s/` (Kustomize), `docker-compose.yml`, `.gitlab-ci.yml`, `README.md`, `FUNCTIONAL.md`, `SBOM.md` |

## Coverage

All 93 tracked files at the base were in scope. Excluded from line review: binary screenshots (`docs/*.jpg`), `web/public/*`, `web/package-lock.json` (reviewed via `npm ls` / `npm audit`), and the generated `web/tsconfig.tsbuildinfo` (now untracked). The initial review was done by the controller; two independent Opus challenge passes then reviewed the fix branch, and one Sonnet agent aligned the docs with the code.

## Baseline validation (at `acb676b`)

| Check | Result |
|---|---|
| `pytest -q` (api) | 9 passed |
| `ruff check .` | clean |
| `mypy app` | 2 errors (missing yaml/bs4 stubs) |
| `alembic upgrade head --sql` | ok |
| `npm run lint` (`next lint`, deprecated) | clean |
| `npm run typecheck` | clean |
| `npm run build` | ok |
| `npm audit` | 1 critical, 5 high |

## Findings and disposition

Severity: H = high, M = medium, L = low. All confirmed findings are fixed unless marked otherwise.

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | H | Real Redis password committed in `k8s/base/secret.example.yaml` | Fixed (placeholder). **Owner action: rotate it.** It is still in git history; purging history needs a force-push and was not done. |
| 2 | H | All API paths public via the `/api/:path*` rewrite: account spend, `/metrics`, `/docs`, `?refresh=true` | Fixed: allowlisting runtime proxy route; account data only with `EXPOSE_ACCOUNT_DATA=true` |
| 3 | H | Prometheus labels use the raw URL path (unbounded series) | Fixed: route-template labels, `__unmatched__` for 404s |
| 4 | H | OpenAI per-model costs always `unknown` (no `group_by=line_item`) | Fixed: group by line item, parse model, paginate |
| 4b | H | Anthropic spend always $0: code read `costs` (field is `results`); amounts are cents strings | Fixed: `results`, ÷100, `limit=31`, follow `next_page` |
| 5 | M | Cache TTL equals refresh interval, so the key expires and requests stampede | Fixed: TTL = 3× interval; single-flight shared refresh task |
| 6 | M | Anthropic cost report truncated to about 7 buckets | Fixed (see 4b) |
| 7 | M | Snapshot table unbounded, duplicate index, ~350 single-row inserts every 5 min | Fixed: batched insert, `SNAPSHOT_RETENTION_DAYS` pruning (default 90), migration `0002` drops the duplicate index |
| 8 | M | Metrics per-worker with `--workers 2` | Fixed: 1 worker per pod; multiprocess collector only when `PROMETHEUS_MULTIPROC_DIR` is set |
| 9 | M | Redis without timeouts; `/readyz` reported the in-memory fallback as Redis | Fixed: 2 s timeouts, reconnect backoff, honest Redis probe; readiness gated on Postgres |
| 10 | M | Failures cached for 2–15 min | Fixed: failures cached 30 s |
| 11 | M | Invalid tier → 500; invalid streak → 422 swallowed by the UI | Fixed: `Literal` tier (422), clamped input, modal shows errors |
| 12 | M | Non-reproducible deploys; web `IfNotPresent` on `:latest`; CI never pushed | Fixed: `Always`, CI pushes SHA tags when credentials are set, documented `kustomize edit set image …:$SHA` |
| 13 | M | CI didn't run tests/lint; `npm install --frozen-lockfile`; Trivy scanned base images with exit 0 and a misfiled SARIF report; dind without TLS settings; `next lint` deprecated | Fixed |
| 14 | M | `API_BASE_URL` at runtime had no effect (rewrites frozen at build) | Fixed by the runtime proxy route |
| 15 | M | Documentation contradicted the code in many places | Fixed (README, FUNCTIONAL, SBOM, About) |
| L1 | L | History chart collapsed points onto three x positions | Fixed: numeric time axis (shared `PriceHistoryChart`) |
| L2 | L | Daily report projected the one-off month-1 bonus and hard-coded `starter`; template said ≥64k context | Fixed: configured tier at steady-state streak; criteria from settings |
| L3 | L | `web/.gitignore` pattern wrong; `tsbuildinfo` tracked | Fixed |
| L4 | L | Image UIDs didn't match `runAsUser: 1000`; web root FS writable | Fixed: UID 1000 in both images; web read-only root filesystem with emptyDirs |
| L5 | L | API Dockerfile built an empty project wheel | Fixed: dependency wheels only |
| L6 | L | One malformed model aborted the whole refresh | Fixed (OpenRouter and Kilo) |
| L7 | L | `fmtUsd` rendered negatives as `$-5.0000` | Fixed |
| L8 | L | Compose ignored `api/.env` | Fixed (optional `env_file`) |
| L9 | L | Placeholder ingress host in prod | Fixed (overlay patch) |
| L10 | L | No-op PDBs; deprecated `commonLabels` | Fixed (PDBs removed; `labels` with identical selectors) |
| L11 | L | `ses-creds` mounted where unused | Fixed |
| L12 | L | `kilo_diff` never alerts when Redis is down | Fixed: baseline hash stored in Postgres (`kilo_plan_snapshot`) |
| L13 | L | Risky/no-op npm overrides (minimatch ^9 invalidated the tree) | Fixed; `npm audit fix` applied |
| L14 | L | Dead code (`KiloPlanSnapshot` unused, `DailyTopFive`, unused hooks, `baseline_pct`); per-plan `max_bonus_pct` ignored | Fixed; `KiloPlanSnapshot` now backs `kilo_diff` |
| R1–R11, N1–N2 | L–M | Issues the independent reviewer found in the fixes (reconnect client leak, serialized retries on a cold cache, untracked close task, retried 404s, misleading caption, CI artifact size, version drift, tier case sensitivity, hour-skip gaps, SBOM wording, retry cap, unretrieved task exception) | Fixed, except R8 (kept fail-fast on an unknown tier, now case-insensitive) and R10 (= finding 1, owner action) |

## Tests added

`api/tests/test_review_fixes.py` (19 tests): route-template metrics labels, tier validation, Kilo plan cap and steady-state streak, malformed-record isolation, cache TTL, OpenAI `line_item` grouping and pagination, Anthropic cents and pagination, Redis fallback, `kilo_diff` alert, baseline and no-change paths, single Redis client under concurrent reconnect, shared failing refresh, tier casing, version from `pyproject.toml`.

Additional manual verification:
- Persistence, gap-filling, pruning, the `kilo_diff` baseline and both migrations were checked against a real embedded PostgreSQL.
- The web proxy was checked against a stub API: allowlist, `refresh` stripped, dot-segment and encoded-slash bypass attempts rejected, and account routes opt-in only.
- The web standalone server was run on a read-only root filesystem.

## Final validation (at the last fix commit)

| Check | Result |
|---|---|
| `pytest -q` | 33 passed |
| `ruff check .` | clean |
| `mypy app` | clean (25 files) |
| `alembic upgrade head --sql` | 0001 → 0002 ok |
| `npm run lint` (`eslint .`) | clean |
| `npm run typecheck` | clean |
| `npm run build` | ok |
| `kustomize build k8s/overlays/prod` | ok; Deployment/Service selectors byte-identical to base |
| `npm audit` | 1 moderate (`next`), 1 high (`postcss` bundled in `next`); both need Next 16 |

## Convergence

| Pass | Result |
|---|---|
| 1 | Initial review: 15 numbered findings, 14 low, 6 in the review skill's own scripts (fixed separately in `claude-tooling`) |
| 2 | Fixes in 4 commits; independent Opus challenge found R1–R11 |
| 3 | R-fixes committed; second challenge found N1–N2 (low) and said nothing else was actionable |
| 4 | N-fixes committed; full validation green |
| 5 | Kilo Code Review on the PR: 4 warnings and 4 suggestions. All were verified and fixed: an invalid `REDIS_URL` escaping the fallback, sequential `/readyz` probes over the 1s kubelet timeout, `kilo_diff` recording a baseline when SMTP silently skipped the alert, and wrong numbers in the FUNCTIONAL.md comparison example. The suggestions (corrupt-value handling, scalar cost `amount`, brief public caching, BYOK example) rode along |

## Commits

1. `f7bb452` fix(api): metrics cardinality, provider costs, cache and Kilo correctness
2. `e64ce0d` fix(web): allowlisting runtime proxy, charts, input and error handling
3. `aa76af2` fix(infra): placeholder secret, scoped mounts, pinned-deploy guidance, CI
4. `9f3d1e2` docs: align README, FUNCTIONAL, SBOM and About page with the code
5. `70f00ca` fix: address independent review of the fix branch
6. `c1c60b6` fix: keep retrying transient account errors; mark shared refresh exceptions retrieved
7. this report

Rollback: revert the merge commit, or individual commits (each is self-contained). Migration `0002` has a working downgrade (`alembic downgrade 0001` recreates the index).

## Deploy notes and residual risk

- **Rotate the Redis password** from the old `secret.example.yaml`. It is in public history.
- **Behavior change:** the account-spend panel and "your usage" trends are hidden unless the web Deployment sets `EXPOSE_ACCOUNT_DATA=true`. Set it only behind authentication.
- `KILO_TIER` must be `starter`, `pro` or `expert` (case-insensitive). Any other value now fails at startup.
- `kilo_diff` records a fresh baseline in Postgres on its first run after deploy. That run cannot alert.
- **Next.js 16:** remaining `npm audit` items (next moderate, bundled postcss high) need Next 16. The private GitLab repository already runs Next 16.3.6.
- **Pipeline:** not verified (waived). The rewritten `.gitlab-ci.yml` has not run anywhere yet. Its dind-socket scan pattern and GitLab syntax were reviewed but not executed.
- Unverified doc numbers kept from the original README: response time and memory figures.

## Recommendation

Merge after rotating the Redis password and deciding on `EXPOSE_ACCOUNT_DATA` for the deployed site.
