# Concerns & Technical Debt

**Analysis Date:** 2026-05-25

---

## Security

**`/metrics` endpoint is unauthenticated and publicly routed**
- File: `api/app/main.py` (line 94), `k8s/base/ingress.yaml`
- The `/metrics` Prometheus endpoint is exposed under the same public Ingress as the API at `models.andrea-house.com/api`. There is no auth middleware guarding it. It leaks operational telemetry (request rates, latencies, status counts) to anyone who can reach the service.
- Fix: Add an `X-Internal-Only` annotation or move `/metrics` to an internal-only port (e.g., 9000) not backed by the Ingress, or gate with a Traefik middleware that requires a token.

**`/docs` (Swagger UI) is enabled in production**
- File: `api/app/main.py` (line 76)
- `docs_url="/docs"` is set unconditionally. In the Docker image/k8s deployment this is reachable at `models.andrea-house.com/api/docs`. Swagger UI lists all routes and their parameters, which is useful for attackers enumerating the API surface.
- Fix: Guard behind `if _settings.environment != "prod"` or remove `docs_url` from the `FastAPI()` constructor when deploying to prod.

**Secrets example file contains placeholder SMTP username in plaintext**
- File: `k8s/base/secret.example.yaml` (line 10)
- `SMTP_USERNAME: pricing-bot` is a real username hint (not `CHANGE_ME`). While not a secret itself, it narrows the attack surface for credential-stuffing against `smtp.andrea-house.com`.
- Fix: Replace with `CHANGE_ME` consistent with the other fields.

**No rate limiting on any API endpoint**
- Files: `api/app/main.py`, `api/app/routes/models_api.py`, `api/app/routes/compare.py`
- All public routes (`/models`, `/models/top`, `/compare/{id}`, `/kilo/projection`) are unthrottled. `/models?refresh=true` in particular triggers an outbound HTTP call to OpenRouter on every hit.
- Fix: Add a FastAPI rate-limit dependency (e.g., `slowapi`) or an nginx/Traefik middleware. At minimum gate `?refresh=true` behind an internal flag or remove it from public exposure.

**Redis has no authentication**
- File: `k8s/base/redis-deployment.yaml`, `k8s/base/configmap.yaml` (`REDIS_URL: redis://redis:6379/0`)
- Redis runs without a password inside the cluster. Any pod in `model-pricing` namespace can read/write the cache, including the kilo diff hash key `kilo:pricing:last_hash`. If another compromised workload lands in the same namespace it can silently reset the hash, suppressing Kilo change alerts.
- Fix: Enable Redis `requirepass` and pass the password via a Secret; update `REDIS_URL` accordingly.

---

## Reliability

**`kilo_diff` hash state lives only in Redis — no durable fallback**
- File: `api/app/jobs/kilo_diff.py` (line 47)
- The Kilo pricing page change detection stores `kilo:pricing:last_hash` in Redis with a 30-day TTL. Redis is an in-memory deployment (no persistence configured). If the Redis pod restarts or is evicted, the hash is lost. The next CronJob run treats `last_hash is None` as a first-run and skips alerting, potentially missing a genuine change that happened while Redis was down.
- Fix: Persist the last hash to the `kilo_plan_snapshot` Postgres table (which already exists but is never written to — see Missing Features), or enable Redis AOF persistence.

**`KiloPlanSnapshot` table is never populated**
- File: `api/app/models.py` (lines 58-74), `api/alembic/versions/20260525_0001_initial.py`
- The ORM model and migration for `kilo_plan_snapshot` exist, but no code path writes to it. The `kilo_diff` job only writes to Redis. If the intent was to use this table for durable hash storage or audit trail, it is dead weight.
- Fix: Either write the hash and tier data here during `kilo_diff` runs (removing the Redis-only dependency), or drop the table and its migration entry to avoid confusion.

**Alembic migration runs as an init-container on every pod startup**
- File: `k8s/base/api-deployment.yaml` (lines 27-36)
- `alembic upgrade head` runs as an init-container in every API pod. With `replicas: 3` in prod, three pods race to run migrations simultaneously on rollout. Alembic does not use advisory locks by default with asyncpg. Concurrent migration runs against Postgres can cause duplicate-key errors or schema corruption on complex migrations.
- Fix: Run migrations as a standalone Job (not init-container) with `completions: 1`, gated before the Deployment rollout. Use Argo/Kustomize job ordering or a manual pre-deploy step.

**`get_model()` does a full list scan on every call**
- File: `api/app/services/openrouter.py` (lines 159-164)
- `get_model(model_id)` calls `list_models()` and iterates the entire model list with a linear scan. With a few hundred models this is cheap now, but it is O(n) per call and runs on every `GET /models/{id}` and `GET /compare/{id}` request.
- Fix: Return a dict from `list_models()` (keyed by `id`) or build a lookup dict once per cache fill.

**Cache fallback in-memory dict is never evicted across replicas**
- File: `api/app/services/cache.py` (lines 20-89)
- The in-memory fallback dict (`self._mem`) correctly expires entries by TTL, but it exists per-process. With 2-3 replicas, a Redis outage leaves each pod with an independently-stale cache. An `OpenRouter` refresh on one pod does not propagate to others. The comment in the code acknowledges this but there is no alerting when Redis falls back beyond the `redis_unavailable` warning log.
- Impact: During Redis outages, different replicas can serve different pricing data for up to 15 minutes (cache TTL).

**No retry logic for Postgres writes in `_persist()`**
- File: `api/app/services/openrouter.py` (lines 122-147)
- `fetch_raw()` uses tenacity with 3 retries for the OpenRouter HTTP call. `_persist()` has no retry at all. A transient Postgres connection error causes the snapshot to be silently dropped for that 15-minute tick.
- Fix: Wrap `_persist()` in a tenacity retry, or at minimum catch and log the specific exception so it surfaces in metrics.

---

## Scalability

**`model_pricing_snapshot` will grow unboundedly — no retention policy**
- File: `api/app/models.py`, `api/alembic/versions/20260525_0001_initial.py`
- The table is append-only with a snapshot every 15 minutes. At ~500 models per tick, that is ~720,000 rows/day. No `DELETE` job, no partitioning, and no archival strategy exists. The 10Gi Postgres PVC will fill in weeks to months at scale.
- Fix: Add a retention CronJob (`DELETE FROM model_pricing_snapshot WHERE captured_at < now() - interval '90 days'`), or partition by `captured_at` using `pg_partman`.

**Postgres is a single-node StatefulSet with no replica**
- File: `k8s/base/postgres-statefulset.yaml`
- `replicas: 1` with a single `ReadWriteOnce` PVC. Postgres is the sole durable store for pricing history. A node failure or PVC corruption means data loss. There is no streaming replica or backup job defined anywhere in the repo.
- Fix: Add a Postgres streaming replica (or use a managed PG service). At minimum add a pg_dump CronJob to object storage.

**Kilo Pass tier prices are hardcoded in a YAML file**
- File: `api/app/data/kilo_plans.yaml`
- Tier prices (`monthly_usd`, `paid_credits_usd`) are static values baked into the container image. Any Kilo pricing change requires a manual YAML edit, image rebuild, and redeploy. The `kilo_diff` job detects the change but the fix workflow is entirely manual and undocumented beyond the email alert.
- Impact: The app will silently serve stale pricing math until someone acts on the alert.

---

## Maintainability

**Kilo bonus growth formula has an acknowledged inconsistency in comments**
- File: `api/app/services/kilo.py` (lines 43-49)
- A comment in `monthly_bonus_pct()` says "Their 'starts at 5%' marketing line implies m2=5% which contradicts a 40% cap at m8; we honor the cap-month since that's the load-bearing one." The formula `step_pct * streak_months` yields 10% at m2 (not 5%) when `step_pct=0.05` and `streak_months=2`. This is different from both what Kilo markets and what `baseline_pct: 0.05` in the YAML implies. If Kilo ever publishes a stricter schedule, the discrepancy will silently produce wrong numbers.
- Fix: Add a unit test that pins the expected bonus at m1, m2, m3, and m8 against the published schedule.

**`DailyTopFive` schema is defined but never used**
- File: `api/app/schemas.py` (lines 72-76)
- `DailyTopFive` is a Pydantic model that has no corresponding route, serialization, or usage in any job. It appears to have been intended for a `/daily-report` endpoint or structured job output. Dead code.
- Fix: Either wire it into `daily_report.py` as the serialized output, or delete it.

**`vscode/extension` is unbuilt and has no CI job**
- Files: `vscode/extension/src/extension.ts`, `vscode/extension/package.json`, `.gitlab-ci.yml`
- The VS Code extension TypeScript source exists but there is no `npm run build` step, no `vsce package` step, and no CI job. The extension cannot be installed without a manual local build. The `vscode/README.md` provides no build instructions.
- Fix: Add a `build:vscode` CI job (or at least a `Makefile` target) that runs `npm ci && npm run compile && vsce package`.

**`deploy:prod` CI job uses deprecated `kubectl set image --record`**
- File: `.gitlab-ci.yml` (lines 175-176)
- `kubectl set image ... --record` is deprecated since Kubernetes 1.19 and removed in 1.28+. It also hard-codes image updates to the Deployment, bypassing the kustomization overlay image pinning at `k8s/overlays/prod/kustomization.yaml`. The two update mechanisms can diverge.
- Fix: Replace the `--record` flag with `kubectl annotate` for rollout tracking; update the kustomization image tag programmatically with `kustomize edit set image` before `kubectl apply`.

**Inline `style` props in multiple frontend components violate the project convention**
- Files: `web/src/components/ModelTable.tsx` (lines 64, 74, 108), `web/src/components/ModelDetailModal.tsx` (lines 112, 150, 153), `web/src/app/trends/page.tsx` (line 39), `web/src/components/KiloPassCalculator.tsx` (lines 36, 52, 103)
- The CLAUDE.md convention states "No inline styles. All styling must use centralized stylesheets / design tokens." Multiple components use `style={{ borderColor: "rgb(var(--border))" }}` and similar inline patterns instead of Tailwind utility classes or CSS variables.
- Fix: Move recurring `rgb(var(--border))` usages to a Tailwind arbitrary value class (e.g., `border-[rgb(var(--border))]`) or add CSS variables to `globals.css` with a corresponding Tailwind config entry.

**`publish` stage missing from CI pipeline**
- File: `.gitlab-ci.yml` — `stages` declares `publish` (line 15) but no job targets it.
- The stage is declared but empty. Images are pushed in the `build` stage with `--destination` flags directly. The gap between intent (push after scan) and reality (push during build, before scan) means a vulnerable image could be published to Harbor before Trivy runs.
- Fix: Move Harbor push out of the Kaniko `--destination` flags into a separate `publish` job that runs after `scan` passes, using `crane copy` or `skopeo copy` to promote the already-built image.

---

## Observability

**CronJob failures have no alerting path beyond email**
- Files: `k8s/base/cronjob-refresh-pricing.yaml`, `k8s/base/cronjob-daily-report.yaml`, `k8s/base/cronjob-kilo-diff.yaml`
- All three CronJobs have `failedJobsHistoryLimit: 5` but no Prometheus alert rule watches for failed jobs (no `KubeJobFailed` or `kube_job_status_failed` alert is configured in this repo). A silent CronJob failure means pricing data stops refreshing with no notification until the next email report is missed.
- Fix: Add a `PrometheusRule` resource that fires on `kube_job_status_failed > 0` for jobs in the `model-pricing` namespace.

**`/metrics` endpoint has a silent fallback that can mask multi-process collection errors**
- File: `api/app/main.py` (lines 97-101)
- `MultiProcessCollector` is wrapped in a `try/except (ValueError, KeyError)` that silently falls back to `generate_latest()` without the multi-process registry. If `prometheus_multiprocess_mode` is not set correctly in the environment (it is not set anywhere in the ConfigMap), metrics from secondary uvicorn workers are silently dropped. No log event is emitted on fallback.
- Fix: Log a warning on the except branch, and verify `PROMETHEUS_MULTIPROCESS_MODE` and `prometheus_multiprocess_dir` are set in the pod environment.

**No distributed tracing**
- No OpenTelemetry or similar instrumentation exists. With 2-3 API replicas, a slow request cannot be attributed to a specific pod without log correlation. Given the external HTTP dependency on OpenRouter, latency spikes are difficult to diagnose.

**`readyz` probe fires a write to Redis on every Kubernetes probe tick**
- File: `api/app/routes/health.py` (lines 22-42)
- `readyz` runs `cache.set("readyz:probe", 1, ttl=5)` followed by `cache.get`. Kubernetes calls this every 5 seconds (`periodSeconds: 5`). That is 12 Redis writes/minute per pod, 36/minute across 3 replicas — noise in Redis MONITOR output and a minor but unnecessary write amplification.
- Fix: Use Redis `PING` via `client.ping()` instead of a set/get roundtrip for the readiness probe.

---

## Open TODOs / FIXMEs

No `TODO`, `FIXME`, `HACK`, or `XXX` comments were found in source files. The two `# type: ignore` suppressions present are:
- `api/alembic/env.py:36` — `do_run_migrations` return type unannotated
- `api/app/main.py:46` — `MetricsMiddleware.dispatch` override signature

Neither blocks correctness but both suppress mypy checks on those functions.

---

## Missing Features / Known Gaps

**`KiloPlanSnapshot` write path is unimplemented**
- Files: `api/app/models.py`, `api/app/jobs/kilo_diff.py`
- See Reliability section above. The table exists in the schema but is never written to. The intended use case (change detection audit trail or durable last-hash storage) is not realized.

**Trends page only exposes top-10 models in its selector**
- File: `web/src/app/trends/page.tsx` (line 17)
- `useTopModels(10)` is used to populate the model selector on the Trends page. Users cannot view historical pricing for models that are not in the current top-10 (e.g., a model that was cheap last month but is now filtered out). The full `useModels()` list is available from the API.
- Fix: Replace `useTopModels(10)` with `useModels()` on the Trends page, or add a search/filter input.

**VS Code extension discount calculation differs from the backend**
- File: `vscode/extension/src/extension.ts` (line 86)
- The extension computes the Kilo discount as `proj.bonus_pct / (1 + proj.bonus_pct)`, which is the correct formula for converting a bonus multiplier to a discount fraction. However, `KiloProjection.bonus_pct` from the API returns the raw bonus percentage (e.g., 0.40 for 40%), not a multiplier. The correct formula would be `proj.bonus_pct / (1 + proj.bonus_pct)` only if `bonus_pct` represents the bonus as a fraction of the total — the server returns `bonus_pct = 0.40` meaning "you get 40% extra," so the effective discount is `0.40 / 1.40 ≈ 0.286`. The formula in the extension happens to produce the right result numerically, but the variable naming and comment are misleading, making this a latent bug if the API contract changes.
- Fix: Add a comment explaining the derivation and a unit test pinning the extension discount math against known inputs.

**No end-to-end or integration tests**
- Files: `api/tests/` — only two test files exist (`test_pricing_calculator.py`, `test_ranker.py`)
- There are no tests for: API routes, database persistence (`_persist()`), cache layer behavior, CronJob entrypoints, or the Kilo diff detection logic. The OpenRouter HTTP client has no test with a mock server (despite `respx` being in dev dependencies). A regression in `fetch_raw()` or `_normalize()` would not be caught by CI.
- Fix: Add `respx`-mocked tests for `fetch_raw()` and `refresh_pricing()`. Add at least one route test using FastAPI's `TestClient` or `httpx.AsyncClient`.

**`kilo_diff` job does not update `kilo_plans.yaml` automatically**
- File: `api/app/jobs/kilo_diff.py`
- The job detects pricing page changes and sends an email, but the actual `kilo_plans.yaml` update is a fully manual process. There is no runbook, link to the Kilo pricing page in the email body beyond a generic instruction, and no mechanism to update the YAML in-place or trigger a pipeline. Until a human acts, all Kilo cost comparisons will be computed against stale tier data.

---

*Concerns audit: 2026-05-25*
