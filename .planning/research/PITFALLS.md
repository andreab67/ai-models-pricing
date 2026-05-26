# Domain Pitfalls — Multi-Provider AI Spend Dashboard

**Domain:** Multi-provider AI billing/usage aggregation (Anthropic + OpenAI + OpenRouter + Kilo.ai)
**Researched:** 2026-05-25
**Overall confidence:** HIGH for Anthropic / OpenAI / OpenRouter (Context7-equivalent official docs read directly), MEDIUM-LOW for Kilo.ai (no public spend API found — see Pitfall 1)

---

## Critical Pitfalls

Mistakes that cause rewrites, silently wrong dashboards, or data loss.

### Pitfall 1: Assuming Kilo.ai has a programmatic spend API at all

**What goes wrong:** The plan treats Kilo.ai as a peer of Anthropic/OpenAI/OpenRouter for billing-API pulls. Direct reads of the Kilo Gateway API reference and the "Usage & Billing" / "Teams Analytics" docs show only chat-completion endpoints (`/chat/completions`, `/api/fim/completions`, `/models`, `/providers`). Per-request response bodies include `cost_microdollars`, but **no documented `GET /usage`, `GET /spend`, or `GET /balance` endpoint exists**. Account balance is described as visible "in the Kilo dashboard" — i.e., web UI only.

**Why it happens:** Kilo.ai is much younger than the three other providers; its public docs are completion-centric, and analytics is a dashboard feature, not an API feature. The 402-with-add-credits response pattern further suggests balance is server-side state without a read endpoint.

**Consequences:**
- Phase that depends on "Pull actual spend from Kilo.ai platform API" can't ship as specified.
- If unaddressed until that phase starts, it forces a mid-phase pivot (forward log + accumulate own counters from per-request `cost_microdollars`, vs. fetching authoritative totals).
- Alternatively pushes the team into HTML scraping of `kilo.ai/dashboard`, which compounds Pitfall 9 (schema drift).

**Prevention:**
1. Before committing to the phase plan, **email Kilo support** (or open a ticket) explicitly asking: "Is there a programmatic endpoint to retrieve historical account spend / balance / usage aggregates?" Get it in writing.
2. Design Kilo integration around two fallback tiers, picked at phase-kickoff based on the answer:
   - Tier A (preferred): If/when an official endpoint exists, use it.
   - Tier B (realistic): **Self-accumulate.** Wrap every Kilo call via the Gateway so each response carries `cost_microdollars`, persist that to `provider_usage_event` rows, and treat Kilo "spend" as the sum-of-events we observed — never as authoritative truth.
   - Tier C (last resort): Authenticated HTML/JSON scrape of the dashboard, behind a feature flag, with the pitfall acknowledged in code.
3. Mark Kilo numbers in the UI with a "self-reported (no official API)" badge so the user trusts but verifies. Anti-pattern: silent equivalence with the other three providers.

**Detection:** If you can't link to a Kilo doc page showing the response schema of a usage endpoint, you don't have an integration — you have a wrapper around chat completions and a database table.

**Phase target:** **Phase 1 (research / scoping), not the Kilo implementation phase.** This is the single highest-risk assumption in PROJECT.md and should be invalidated or confirmed before any Kilo code is written.

---

### Pitfall 2: Treating Anthropic Enterprise Analytics numbers as live data

**What goes wrong:** Anthropic has **two** usage/cost surfaces with very different freshness contracts:

| Surface | Lag | Revision window |
|---------|-----|-----------------|
| **Admin Usage & Cost API** (`/v1/organizations/usage_report/messages`, `/v1/organizations/cost_report`) | ~5 minutes typical | Not advertised as "revisable" — appropriate for live dashboards |
| **Enterprise Analytics API** | Cost/usage refreshes every **4 hours**, up to **24 hours**. Values can be **revised for up to 30 days** as late events reconcile. Engagement endpoints lag **3 days**. Anthropic explicitly recommends querying dates **≥ 30 days in the past for invoicing-grade accuracy**. | 30 days |

If the engineer copy-pastes a snippet from a blog or wires up the Enterprise endpoint thinking "newer is better," the dashboard will show numbers that move under the user's feet days after the fact.

**Why it happens:** Both APIs use admin keys (`sk-ant-admin...`). The naming "Enterprise Analytics" sounds like an upgrade. The lag/revision properties are buried in FAQ paragraphs, not in the endpoint reference.

**Consequences:**
- Yesterday's spend changes when the dashboard reloads tomorrow → user trust collapses ("the number changed, is this thing broken?").
- "Total spend" rectangles drift downward as Anthropic backs out double-counted events.
- Reconciliation against the monthly invoice succeeds only if you query stale-enough dates.

**Prevention:**
- **Use the Admin Usage & Cost API** for this project. Endpoints: `GET /v1/organizations/usage_report/messages` and `GET /v1/organizations/cost_report`.
- Treat data <30 days old as "preliminary" and tag it visibly. Treat data >30 days old as "settled."
- For the dashboard "live" view, accept the 5-minute lag — that's the floor, no provider beats it.
- Document explicitly which Anthropic endpoint we chose and why. Add it to a code comment near the HTTP client.

**Detection:** If yesterday's total changes by >1% on a 24h reload, you're querying Enterprise Analytics, not Admin Usage.

**Phase target:** Anthropic-spend-pull phase. Document during phase kickoff, before writing the HTTP client.

---

### Pitfall 3: Storing per-day spend in non-UTC buckets

**What goes wrong:** CLAUDE.md says "Default timezone is MDT (America/Denver) unless explicitly specified." Every provider's billing/usage API uses **UTC day boundaries** with no exceptions:
- Anthropic `bucket_width=1d` → UTC midnight buckets.
- OpenAI usage/cost API → daily buckets, UTC alignment.
- OpenRouter user activity → "last 30 (completed) UTC days," explicitly UTC.
- Kilo.ai "Daily spending limits reset at midnight UTC."

If the FastAPI side stores `captured_at` in MDT (or worse, mixes MDT and UTC depending on which job ran) and the dashboard groups by `date_trunc('day', captured_at)`, two things break:
1. Anthropic reports $100 for 2026-05-25 (UTC). The dashboard's "May 25" row (MDT-based) holds only the data from 06:00 UTC May 25 through 06:00 UTC May 26, so the totals never match.
2. Daily digest emails for "yesterday" land on the wrong UTC bucket, and the numbers won't reconcile against the provider's own dashboards.

**Why it happens:** Default-timezone rules in CLAUDE.md exist for *display* (user-facing times, trading hours). They are wrong as the *storage* convention for cross-provider billing data.

**Consequences:**
- Per-day totals will be off by a fraction of a day every day, with the error shifting based on DST.
- Reconciliation against any provider dashboard becomes impossible.
- "Top model yesterday" picks the wrong winner near the day boundary.

**Prevention:**
- **Store everything in UTC** in Postgres (`timestamptz` columns, UTC values). This is already mostly the case in the existing code (Alembic migration uses `timestamptz`) — formalize it as a convention.
- Define one canonical "day" in the codebase: UTC. Add a constant `SPEND_DAY_TZ = "UTC"` and a comment explaining why CLAUDE.md's MDT default does NOT apply to billing aggregation.
- At the **presentation layer only** (Next.js dashboard, email digest), convert UTC → MDT for display, with the timezone shown in the UI.
- Per-provider time ranges sent in API requests must always be UTC ISO-8601 with `Z` suffix or explicit `+00:00`.

**Detection:** Add a one-time reconciliation test that pulls a fixed past day from each provider and asserts the sum-of-day from our DB equals the provider's reported total (within $0.01 tolerance). If it drifts by ~25-95% of expected, you have a TZ bucketing bug.

**Phase target:** First spend-pull phase (whichever provider goes first). Encode as a shared utility before the second integration is written.

---

### Pitfall 4: Putting 4 long-lived admin/management keys in a single k8s Secret with no rotation plan

**What goes wrong:** The existing `secret.example.yaml` shows the pattern: flat key/value pairs in one `Secret`. The plan adds at least four new high-blast-radius credentials:

- `ANTHROPIC_ADMIN_KEY` (`sk-ant-admin...`) — reads organization-wide usage and cost.
- `OPENAI_ADMIN_KEY` — admin-key required for `/v1/organization/costs`.
- `OPENROUTER_MANAGEMENT_KEY` — required for `analytics/get-user-activity`.
- `KILO_API_KEY` — bearer token with whatever scope Kilo gives (possibly full account).

Each of these can read everything; some can also write (Anthropic admin keys can rotate API keys; OpenAI admin keys can create/delete projects). CONCERNS.md already flags:
- Redis has no auth → any compromised pod in the namespace can read cache.
- `/metrics` and `/docs` are publicly exposed.
- No retention policy → secrets live forever in etcd by default.

Mix those weaknesses with admin-class credentials and you've widened the blast radius from "pricing snapshots" to "full provider account control."

**Why it happens:** It's the path of least resistance — one Secret, one env-var, one ConfigMap reference. The existing code already does it for the OpenRouter (read-scope) key, so it's the obvious template.

**Consequences:**
- Compromise of any pod in `model-pricing` namespace = compromise of all four provider accounts.
- No rotation cadence means a leaked key (CI logs, accidental commit, container exfil) stays valid for months.
- Admin keys also gate the user's *personal* AI spending — a hostile actor with the OpenAI admin key can spin up new projects and rack up bills.

**Prevention:**
1. **One Secret per provider** (not one Secret with four keys). Lets you reset/rotate one without churning the others, and lets RBAC scope which pods/jobs can read which.
2. Only the worker / CronJob that actually pulls spend needs the admin keys. The dashboard API does **not** — it reads from Postgres. Split the deployment: a `spend-fetcher` Deployment (or set of CronJobs) with the admin Secrets mounted, and the existing API Deployment with no provider admin secrets at all.
3. **Document rotation cadence** (90 days max, per common SaaS-key guidance). Even without an external secrets manager, a calendar reminder + runbook beats nothing.
4. **Restrict scope at the provider** wherever possible: OpenRouter management keys can be scoped; Anthropic admin keys are org-wide (no scoping available) — treat them as nuclear.
5. Address the `/metrics` and `/docs` public exposure (already in CONCERNS.md) before adding admin keys to the same pod environment.
6. If the home cluster has Vault, External Secrets Operator, or sealed-secrets, use it. Plain k8s Secrets in etcd is the floor, not the goal.

**Detection:** Run `kubectl describe secret -n model-pricing` and count how many distinct provider credentials live in one resource. >1 = consolidate later. Audit which Deployments mount which Secrets; the API pods should not have admin keys mounted at all.

**Phase target:** Phase that adds the *first* provider admin key. Establishing the per-provider-Secret pattern early is much cheaper than splitting them later when four jobs already reference them.

---

### Pitfall 5: Treating cached-token billing as "free" — or worse, double-counting it

**What goes wrong:** Anthropic's Usage API reports four distinct token classes:
- uncached input
- cached input (read)
- cache creation (write)
- output

Anthropic bills cache reads at **0.1×** input price (90% discount) but cache writes at **1.25× or 2×** input price. OpenAI bills cache reads at **0.25–0.5×** with no write premium. OpenRouter passes upstream cache fields through but the schema differs by underlying model. Kilo records `cache_write_tokens` and `cache_hit_tokens` separately.

Two failure modes are equally likely:
1. **Under-attribution:** Computing cost as `tokens × base_price` ignoring cache class → dashboard says $X, invoice says $0.4X. User thinks the app over-counts and stops trusting it.
2. **Double-count / wrong sign:** Anthropic returns negative `cache_discount` on writes and positive on reads. A naive `total += discount` flips sign somewhere → "savings" line goes negative on cache-heavy days.

**Why it happens:** The existing OpenRouter integration in this repo (`services/openrouter.py`) tracks *list prices* not per-request costs — i.e., it has never had to deal with cache class differentiation. The transition from "what does this model cost per Mtok" to "what did I actually spend" is exactly where caching math bites.

**Consequences:**
- Numbers don't match provider dashboards → user trust evaporates.
- "Kilo savings vs Sonnet 4.6" calculation (already in the repo) is meaningless once cache pricing is in play, because a heavy-cache workload through Sonnet directly is cheaper than the calculator implies.

**Prevention:**
- **Don't compute cost. Read it.** All four providers return cost figures alongside token counts (Anthropic `cost_report`, OpenAI `costs`, OpenRouter `total_cost`, Kilo `cost_microdollars`). Persist the *reported* cost; persist token classes separately for analysis. Compute cost only as a fallback when the API doesn't return one (rare).
- Store all costs in a single canonical unit. Recommendation: **microdollars (int64)** — matches Kilo's native unit and avoids float drift across millions of rows. Convert at the presentation boundary.
- For Anthropic, group/break out by `cache_creation` vs `cache_read` so the UI can show cache efficiency.
- Add a per-provider reconciliation test: for one known historical day, the sum of per-event reported costs must equal the provider's `cost_report` aggregate (within $0.01 or 1 microdollar per row).

**Detection:** Pick the most recent fully-settled day. If your stored daily total differs from the provider's own dashboard by >2%, you have a cache-class bug. Pre-cache-pricing-era this used to be rare; in 2026 it's the most common multi-provider reconciliation bug.

**Phase target:** Cost-storage-schema phase, before any provider integration is built. Decide units and "what counts as cost" once.

---

### Pitfall 6: Per-process / per-pod cache invalidation and counter drift

**What goes wrong:** CONCERNS.md already documents the in-memory cache fallback drifting across replicas during a Redis outage. The spend pipeline adds a new failure mode: **cursor / watermark state.** Each provider's API is paginated and incremental, so the fetcher must remember "where did I last pull through?" If that watermark lives only in memory or only in Redis (which has no persistence here), a restart re-pulls overlapping windows. With Anthropic's revisable Enterprise data or OpenAI's late-arriving events, the re-pull can produce *different* values for the same date — and naive upsert logic produces silently inconsistent totals.

**Why it happens:** Cursor state feels like cache, so the lazy choice is "throw it in Redis." But cache invalidation rules (TTL eviction, in-memory fallback per pod) are catastrophically wrong for monotonic-watermark semantics.

**Consequences:**
- After a pod restart, daily totals "shift" without an obvious cause.
- Two pods racing on the same CronJob (Anthropic permits, but with rate-limit cost) can each pull the same window and produce duplicate rows if dedup is loose.
- A wedged CronJob (CONCERNS.md notes no `KubeJobFailed` alerting exists) means watermarks stop advancing and the dashboard silently freezes.

**Prevention:**
- Persist fetcher watermarks in **Postgres**, not Redis. Add a small `provider_sync_state` table: `(provider, cursor_kind, cursor_value, last_run_at, last_success_at, last_error)`.
- Make ingest **idempotent by natural key**: e.g., `(provider, model, time_bucket_start, api_key_id_hash)` as a unique constraint, with `INSERT ... ON CONFLICT DO UPDATE` so revisions overwrite cleanly.
- Use a Job (not CronJob with concurrent runs) or set `concurrencyPolicy: Forbid` on the spend-fetch CronJobs to prevent overlap.
- Add a `kube_job_status_failed` PrometheusRule (CONCERNS.md already flags this gap) so wedged fetchers are noisy.

**Detection:** Run the fetcher twice in a row against the same window. The row count should be stable; total spend should not change by more than the provider's published revision window.

**Phase target:** First spend-pull phase. Schema and idempotency contract must exist before the second provider integration is grafted on.

---

## Moderate Pitfalls

### Pitfall 7: Reusing `tenacity` retry config without per-provider tuning

**What goes wrong:** The existing OpenRouter client uses tenacity with 3 retries. Copy-pasting that pattern to the new provider clients ignores:
- Each provider's **429 response includes a `Retry-After` header** (Anthropic explicitly documents this; OpenAI and OpenRouter follow the same convention). Generic exponential backoff that ignores `Retry-After` either retries too soon (more 429s) or too late (wasted budget).
- **Admin endpoints have different rate limits than inference endpoints.** Anthropic Admin Usage API allows ~1 poll per minute sustained. Hammering it with the inference-key budget will trip a different 429 bucket.
- **Burst vs steady.** A first-time backfill of 90 days of data is bursty; the daily incremental is steady. Same retry policy is wrong for both.

**Prevention:**
- Wrap each provider client in a tenacity decorator that **reads `Retry-After`** (`retry_if_exception_type` + custom `wait_callable`) — `max(retry_after, exponential_backoff)`.
- Add **full jitter** (not none), `sleep = random_between(0, min(cap, base * 2^attempt))`. Pure exponential synchronizes pods.
- Cap retries at 3 for sync paths, 5–7 for batch backfills.
- Surface the retry count as a Prometheus counter per provider so noisy providers are visible.

**Phase target:** First spend-pull phase; codify as a shared `provider_http` utility before the second integration.

---

### Pitfall 8: Trusting OpenRouter's `cost` field for BYOK requests

**What goes wrong:** OpenRouter has two cost modes:
- Normal (OpenRouter pays the upstream) → `total_cost` is what *you* owe OpenRouter.
- BYOK (you supply the upstream key) → OpenRouter charges 5% of normal price as a service fee. The `upstream_inference_cost` field on responses estimates what you owe the upstream provider, but **OpenRouter is not the billing source of truth** for that — Anthropic/OpenAI are.

If the user routes Anthropic calls through OpenRouter BYOK, the same dollar will appear twice if the dashboard naively sums Anthropic spend + OpenRouter spend.

**Prevention:**
- When ingesting OpenRouter activity, **store `total_cost` and `upstream_inference_cost` as separate columns**. Sum only `total_cost` for "what I owe OpenRouter." Don't double-count `upstream_inference_cost` — that's already covered by the Anthropic/OpenAI pull.
- Add a per-provider "definition" doc string at the top of each fetcher: "Anthropic = what Anthropic invoices. OpenRouter = what OpenRouter invoices. Sum is total spend, no double-counting."
- In the UI, if a row has nonzero `upstream_inference_cost`, render it as informational ("upstream pass-through, billed by [provider]") not as additional spend.

**Detection:** Sum-of-providers > what's on each invoice = double counting. Most often hits BYOK setups.

**Phase target:** OpenRouter spend-pull phase.

---

### Pitfall 9: Schema drift from any provider, especially mid-MVP

**What goes wrong:** Three of the four providers are actively reshaping their APIs:
- **OpenAI** moved from `/v1/usage` (legacy) → `/v1/organization/costs` + `/v1/organization/usage/...` (sub-endpoints per resource: completions, embeddings, vector_stores, code_interpreter_sessions, etc.). Some users report 404s during permission/key edge cases.
- **Anthropic** added Admin Usage & Cost API and *also* Enterprise Analytics API; expect more fields (`speed`, `inference_geo` already shipped as recent beta additions).
- **Kilo.ai** is young — schema is most likely to change with the least notice. The repo already has a SHA-256-based change detector for the Kilo *pricing page*, which is itself acknowledgment that Kilo's "API" surface is partly an HTML page.
- **OpenRouter** is stable but adds fields routinely (`reasoning_tokens` is recent).

A schema break shows up as: deserialization error → tenacity retries until exhausted → CronJob fails → no alert (CONCERNS.md) → user notices a stale dashboard days later.

**Prevention:**
- Parse with **strict-but-tolerant** Pydantic models: required fields fail loudly, unknown fields are accepted (`model_config = ConfigDict(extra="ignore")` or equivalent). Avoids breakage from added fields.
- **Persist the raw JSON response** alongside the parsed rows for at least 30 days. When schema drifts, you can rebuild parsed rows from raw rather than re-querying. A column `raw_response jsonb` on the ingest table is cheap insurance.
- Add a CI integration test per provider using `respx` (already a dev dep in this repo) with a snapshot of the current response. When the snapshot drifts in CI from a real-world fetch, fail loud.
- Pin and check provider SDK / API versions if available (Anthropic uses `anthropic-version: 2023-06-01` header — pin it).
- Apply the existing Kilo pricing-page change detection pattern to the *response schemas* themselves: hash the field set of a response, alert on change.

**Phase target:** All spend-pull phases. Encode raw-storage as part of the schema decision in Pitfall 5.

---

### Pitfall 10: Currency / unit mismatch (microdollars vs dollars vs cents)

**What goes wrong:** Each provider has a different favorite unit:
- **Anthropic** `cost_report`: "decimal strings in lowest units (cents)" per their docs.
- **OpenAI** `costs` endpoint: typically dollars as floats.
- **OpenRouter** `total_cost`: dollars (float, USD).
- **Kilo.ai**: microdollars (int, 1 USD = 1,000,000).

Mixing these in floats → 1-cent rounding errors per row × 720k rows/day = $7,200/day of phantom error. Mixing units in a single arithmetic expression → 100× or 1,000,000× off-by-X bugs that look "right" at small scale and explode at month-end.

**Prevention:**
- Pick **one canonical unit** for storage. **Microdollars (`bigint`)** matches Kilo natively and avoids float entirely. Convert at ingest, never store floats.
- Pydantic schemas should convert at the boundary: each provider's parser is responsible for its own unit conversion to microdollars. Document the conversion factor next to the model class.
- All currency is **USD only** for this project (per PROJECT.md scope). If a provider ever returns non-USD (e.g., EUR pricing tier), reject the row and alert — don't silently downcast.
- Add unit tests for each parser: feed a sample with `cost = $1.234567` and assert stored `cost_microdollars == 1234567`.

**Phase target:** Schema/storage phase, before first integration.

---

### Pitfall 11: Provider outages cascade into dashboard outages

**What goes wrong:** Anthropic has documented overload events; OpenAI has periodic billing-API 5xx waves; OpenRouter sits on top of all upstreams. If the dashboard tries to fetch live during a render, an upstream blip → spinning skeleton → user thinks the dashboard is broken.

**Why it happens:** Easy to wire the API client to fetch on render. Existing repo has good separation (CronJob populates Postgres, API reads from Postgres) — preserve that for the new providers.

**Prevention:**
- **Strict ingest/serve split.** CronJobs / Jobs pull from providers and write to Postgres. The HTTP API only reads Postgres (and Redis for cached views). Never call provider APIs synchronously from a user-facing route.
- Show a "last successful sync at: T" badge per provider in the UI. If T is >2× the expected interval, show "data may be stale" rather than failing.
- For the rare on-demand fetch (e.g., "refresh now" button), put it behind admin auth (not a query string toggle — CONCERNS.md flags `?refresh=true` is unthrottled).

**Phase target:** Dashboard UI phase.

---

## Minor Pitfalls

### Pitfall 12: Forgetting that Anthropic Workbench usage has `null` API key id

Per Anthropic docs: "API usage from the Workbench is not associated with an API key, so `api_key_id` will be `null` even when grouping by that dimension." If the dashboard groups by key and silently drops `null`, Workbench usage disappears. **Fix:** Always render a "Workbench / unknown-key" bucket and sum nulls into it.

### Pitfall 13: Treating per-day data as immutable

Even the Admin Usage & Cost API can show small revisions in the first few hours as events finish settling. Late-bound retries, batch jobs (50% discount tier), and Workbench calls can land minutes after the request started. Idempotent upserts (Pitfall 6) handle this — naive INSERT-ignore loses revisions.

### Pitfall 14: Daily digest email "yesterday" definition

The existing daily digest email runs on a CronJob. If it computes "yesterday" using container-local time (which in a k8s pod defaults to UTC, but if anyone sets `TZ=America/Denver` it shifts) the "yesterday" boundary will not match the provider's UTC-day reports. **Fix:** Hard-code UTC in the CronJob's date math; convert to user-facing TZ only in the email body text.

### Pitfall 15: Confusing OpenAI Admin API key with regular API key

OpenAI's `/v1/organization/costs` requires `OPENAI_ADMIN_KEY`, NOT the regular `OPENAI_API_KEY`. Several community posts about "404 on costs endpoint" are admin-key permission errors in disguise. **Fix:** Separate env vars (`OPENAI_API_KEY` for inference if ever added, `OPENAI_ADMIN_KEY` for billing). Validate at startup with a cheap test call so misconfig fails on boot, not at 3am when the CronJob runs.

### Pitfall 16: Migration races (already flagged in CONCERNS.md, but worse now)

CONCERNS.md notes Alembic migrations run as init-containers on every pod with replicas: 3. Adding new tables for spend ingest expands the schema and increases the surface for races. Fix the existing issue (run migrations as a standalone Job) before adding the new tables — don't compound the debt.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| **Phase 0 — Kilo.ai API feasibility** | Pitfall 1 (no programmatic API) | Email Kilo support first, structure the rest of the plan around the answer |
| **Phase 1 — Spend storage schema** | Pitfalls 5, 10, 6 | Microdollars + reported costs + raw JSON + idempotent upserts; decide once |
| **Phase 2 — First provider integration (suggest Anthropic — most documented)** | Pitfalls 2, 3, 7, 9 | Admin API not Enterprise; UTC everywhere; `Retry-After`-aware retries; raw JSON snapshot |
| **Phase 3 — Second / third providers (OpenAI, OpenRouter)** | Pitfalls 8, 15 | Separate admin keys; document BYOK double-count rules; reconcile per provider |
| **Phase 4 — Kilo integration** | Pitfalls 1, 9 | Tier-B self-accumulate; "self-reported" UI badge; raw JSON storage |
| **Phase 5 — Dashboard UI** | Pitfalls 3, 11 | Ingest/serve split; "last sync" badges; TZ conversion at the boundary only |
| **Phase 6 — Email digest / alerts** | Pitfalls 14, CONCERNS observability gaps | UTC for math, MDT for display; add `KubeJobFailed` alert rule |
| **Cross-cutting — Secrets / k8s** | Pitfall 4 | One Secret per provider; spend-fetcher Deployment separate from API; fix `/metrics` and `/docs` exposure first |

---

## Sources

### Authoritative (direct fetch of provider docs)

- [Anthropic Usage and Cost API](https://platform.claude.com/docs/en/api/usage-cost-api) — confirmed admin-key, ~5min lag, UTC buckets, microdollar/cent units (HIGH confidence).
- [OpenRouter Get User Activity](https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity) — confirmed management-key, 30 UTC days, `total_cost` + `upstream_inference_cost` fields (HIGH).
- [Kilo Gateway API Reference](https://kilo.ai/docs/gateway/api-reference) — confirmed *no* documented spend/usage endpoint exists (MEDIUM — "absence of evidence" requires email confirmation; covered in Pitfall 1).
- [Kilo Usage & Billing](https://kilo.ai/docs/gateway/usage-and-billing) — confirmed microdollar precision, dashboard-only balance (MEDIUM).
- [OpenAI Costs endpoint](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs) — confirmed admin-key, daily granularity (HIGH).
- [OpenAI Usage API cookbook](https://developers.openai.com/cookbook/examples/completions_usage_api) — confirmed bucket widths, pagination, group_by behavior (HIGH).

### Supporting (industry / community)

- [Anthropic Enterprise Analytics vs Admin API comparison (Finout)](https://www.finout.io/blog/anthropics-enterprise-analytics) — source for the 4h–24h Enterprise lag and 30-day revision window (MEDIUM, verified against Anthropic docs).
- [OpenAI Usage API announcement](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058) — context for the v1/usage → /v1/organization/costs migration (MEDIUM).
- [OpenRouter BYOK billing](https://openrouter.zendesk.com/hc/en-us/articles/43219817892123) — source for the 5% BYOK fee and double-count pitfall (MEDIUM).
- [Anthropic Rate Limits docs](https://docs.anthropic.com/en/api/rate-limits) — `Retry-After` header convention and 429 dimensions (HIGH).
- [Prompt caching billing comparison](https://help.apiyi.com/en/openai-vs-claude-prompt-caching-pricing-comparison-en.html) — Anthropic 90% / OpenAI 75% cache-read discounts (MEDIUM).
- [Kubernetes secrets best practices](https://oneuptime.com/blog/post/2026-02-20-kubernetes-secrets-management/view) — rotation cadences, external secret stores (MEDIUM).
- [LLM retry strategy guide](https://callsphere.ai/blog/retry-strategies-llm-api-calls-exponential-backoff-jitter-tenacity) — jitter + `Retry-After` patterns (MEDIUM).

### From the repo itself

- `c:\Users\andreab\model-pricing\.planning\codebase\CONCERNS.md` — existing technical debt that compounds with the new ingest pipeline (Redis no-auth, public /metrics, no CronJob failure alerts, in-memory cache drift, migration races).
- `c:\Users\andreab\model-pricing\.planning\PROJECT.md` — explicit assumption that Kilo.ai's API needs confirmation; this research turns that "needs confirmed" into "must be confirmed before phase start."
