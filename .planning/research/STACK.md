# Provider Billing/Usage APIs — Technology Research

**Project:** model-pricing (AI spend dashboard)
**Researched:** 2026-05-25
**Mode:** Ecosystem (provider API integration)
**Overall confidence:** HIGH for Anthropic / OpenAI / OpenRouter, MEDIUM for Kilo.ai (no dedicated billing API exposed)

---

## Executive Summary

All four providers can be integrated into the existing FastAPI + httpx + asyncpg stack — **no new runtimes or libraries are required**. The integration pattern follows the existing `services/openrouter.py` shape: an async httpx client with `tenacity` retries, a Pydantic schema layer, and a periodic CronJob that writes append-only snapshots to Postgres.

**Critical asymmetry:** Three of the four providers (Anthropic, OpenAI, OpenRouter) expose a real *historical aggregated usage/cost API* (admin-key auth, time-bucketed queries, group_by by model). **Kilo.ai does not** — it exposes per-request usage in the chat completions response and shows aggregates only on the dashboard. Spend tracking for Kilo will require **inline accounting** (we log token counts + cost from each completion response) rather than a backfill query.

For coding benchmarks: there is no single "benchmarks API." The best programmatic sources are static YAML/JSON files in public GitHub repos (Aider polyglot leaderboard) plus the HuggingFace `livecodebench/leaderboard` Space. These should be fetched on a weekly CronJob, not in real-time.

---

## Recommended Stack (Additions Only)

All additions slot into the existing FastAPI + httpx stack. **No new core dependencies needed.**

| Component | What | Why It Fits |
|---|---|---|
| `httpx.AsyncClient` (already in stack) | Provider API calls | Async, mature, already used for OpenRouter |
| `tenacity` (already in stack) | Retry with backoff | Already used for OpenRouter; reuse pattern for new providers |
| `pydantic` v2 (already in stack) | Schema parsing per provider | One Pydantic model per provider response, normalize to a shared `UsageSnapshot` model |
| `SQLAlchemy` (already in stack) | New tables: `provider_usage_snapshot`, `provider_account` | Append-only, same pattern as existing price history |
| `Alembic` (already in stack) | DB migration for new tables | — |
| `apscheduler` or **k8s CronJob** (already used) | Periodic backfill of provider data | Existing `refresh-pricing` CronJob is the pattern; spawn 4 new CronJobs (or 1 unified) |
| **`PyYAML`** (already in stack) | Parse Aider polyglot leaderboard | Already a dep — used for `kilo_plans.yaml` |
| **No new HTTP libs** | — | httpx covers all four providers' APIs |

### Optional additions to consider

| Library | Version | Purpose | Verdict |
|---|---|---|---|
| `aiocache` | 0.12+ | Decorator-style caching | **Skip** — existing Redis cache wrapper already covers this |
| `polars` | 1.x | Aggregating large usage windows in-memory | **Skip for v1** — Postgres aggregation is sufficient at personal-spend volume |
| `tiktoken` / `anthropic` SDK token counter | — | Local token re-estimation if API delay | **Skip** — provider APIs return authoritative counts; no need to recompute |

---

## Per-Provider API Details

### 1. Anthropic (Claude) — Admin API

**Confidence:** HIGH (verified against official Anthropic platform docs).

**Endpoints:**

- Usage (tokens): `GET https://api.anthropic.com/v1/organizations/usage_report/messages`
- Cost (USD): `GET https://api.anthropic.com/v1/organizations/cost_report`

**Auth:**

- Header: `x-api-key: $ANTHROPIC_ADMIN_KEY` (admin keys start with `sk-ant-admin...`)
- Header: `anthropic-version: 2023-06-01`
- **CRITICAL:** The Admin API is **unavailable for individual accounts**. The personal account must be promoted to an organization (Console → Settings → Organization) before admin keys can be created. Only org members with the `admin` role can provision admin keys.

**Time granularity:**

| `bucket_width` | Default limit | Max limit |
|---|---|---|
| `1m` (minute) | 60 buckets | 1440 buckets |
| `1h` (hour) | 24 buckets | 168 buckets |
| `1d` (day) | 7 buckets | 31 buckets |

Cost endpoint only supports `1d`.

**Key request params:**

- `starting_at`, `ending_at` (ISO8601 UTC)
- `bucket_width` (1m / 1h / 1d)
- `group_by[]` = `model`, `workspace_id`, `api_key_id`, `service_tier`, `context_window`, `inference_geo`
- `models[]`, `workspace_ids[]`, `api_key_ids[]`, `service_tiers[]` (filters)
- Pagination: `limit`, `page` (cursor from `next_page`), `has_more` flag

**Response shape (usage):** Token counts broken into `uncached_input`, `cached_input`, `cache_creation`, `output`. Server tools (web search) are tracked separately.

**Response shape (cost):** All costs in **USD**, returned as decimal strings in **cents** (lowest units). Group by `workspace_id` or `description` — grouping by `description` returns parsed `model` and `inference_geo` fields.

**Data freshness:** Usage and cost data appears within **~5 minutes** of API request completion (occasionally longer).

**Rate limits / polling:** "Supports polling once per minute for sustained use." Burst polling acceptable for paginated backfills.

**Gotchas (HIGH confidence):**

1. **Priority Tier costs are NOT in the cost endpoint** — must be derived from usage endpoint by filtering `service_tier=priority`. For a personal coding workflow this is unlikely to matter, but document the limitation.
2. **Cost endpoint is in beta** — expect schema changes; build defensively (use Pydantic `extra="allow"`).
3. **Workbench usage has `api_key_id=null`** — costs from the web Console can't be attributed to a key.
4. **Default workspace has `workspace_id=null`** — not the string `"default"`.
5. **Code Execution costs only appear in cost endpoint** (grouped under description `Code Execution Usage`), never in the usage endpoint.
6. **Claude Platform on AWS:** programmatic usage/cost endpoints are unavailable; AWS users must read the Console UI. Not relevant for direct-Anthropic accounts.
7. **Per-user (Claude Code seat) breakdown:** requires the separate **Claude Code Analytics API**, not the Usage/Cost API. For our use case (personal API consumption), the standard endpoints suffice.

**Source:** [Anthropic Usage & Cost API docs](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api), [Cookbook](https://platform.claude.com/cookbook/observability-usage-cost-api)

---

### 2. OpenAI — Admin Usage & Costs API

**Confidence:** HIGH (verified against official OpenAI developer docs).

**Endpoints:**

- Completions usage: `GET https://api.openai.com/v1/organization/usage/completions`
- Costs: `GET https://api.openai.com/v1/organization/costs`
- (Also: `/usage/embeddings`, `/usage/images`, `/usage/audio_speeches`, `/usage/audio_transcriptions`, `/usage/moderations`, `/usage/vector_stores` — same shape)

**Auth:**

- Header: `Authorization: Bearer $OPENAI_ADMIN_KEY`
- Admin keys are **distinct** from regular API keys. Provision at https://platform.openai.com/settings/organization/admin-keys
- Personal account: an org wrapper exists automatically — no manual org setup needed (unlike Anthropic).

**Time granularity:**

| Endpoint | `bucket_width` options |
|---|---|
| `/usage/completions` | `1m`, `1h`, `1d` |
| `/organization/costs` | **`1d` only** |

`limit` parameter: 1–180 buckets, default 7.

**Key request params:**

- `start_time`, `end_time` — **Unix seconds** (NOT ISO strings; different from Anthropic)
- `bucket_width` (default `1d`)
- `group_by[]` = `model`, `project_id`, `user_id`, `api_key_id`, `line_item` (cost only), `batch` (usage only); combos allowed e.g. `["model", "project_id"]`
- Filters: `project_ids[]`, `user_ids[]`, `api_key_ids[]`, `models[]`, `batch` (boolean)
- Pagination: `page` cursor, `has_more`, `next_page`

**Response shape (usage completions):**

```json
{
  "object": "page",
  "data": [{
    "object": "bucket",
    "start_time": 1736616660,
    "end_time": 1736640000,
    "results": [{
      "object": "organization.usage.completions.result",
      "input_tokens": 141201,
      "output_tokens": 9756,
      "input_cached_tokens": 0,
      "input_audio_tokens": 0,
      "output_audio_tokens": 0,
      "num_model_requests": 470,
      "project_id": null,
      "user_id": null,
      "api_key_id": null,
      "model": null,
      "batch": null
    }]
  }],
  "has_more": false,
  "next_page": null
}
```

**Response shape (costs):**

```json
{
  "results": [{
    "object": "organization.costs.result",
    "amount": { "value": 0.130804, "currency": "usd" },
    "line_item": null,
    "project_id": null,
    "organization_id": "org-xxx"
  }]
}
```

Note `amount.value` is **dollars as a float** (not cents like Anthropic).

**Gotchas (HIGH confidence):**

1. **Time is Unix seconds, not ISO** — easy mistake when copying Anthropic code. Wrap both in a normalizer.
2. **Costs endpoint daily only** — for hourly cost dashboards, multiply token counts from `/usage/completions` by static model pricing as a fallback. Token×price ≠ exact billed cost (volume discounts, audio surcharges, regional uplift) but close enough for trend visualization.
3. **`line_item`** in cost responses contains strings like `"Tokens - GPT-4o input"` — parse to extract model + token type.
4. **Cost values can lag usage by hours** — the cost ledger is reconciled after billing. Usage is real-time; cost is reconciled.
5. **Audio/image/embedding usage are separate endpoints** — for a coding-only dashboard, only `/usage/completions` is needed initially. The cost endpoint, however, returns everything in one call.
6. **Regional data-residency endpoints** carry a 10% uplift not always visible in token-derived estimates.

**Source:** [OpenAI Cookbook — Usage API](https://developers.openai.com/cookbook/examples/completions_usage_api), [Admin Costs API reference](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)

---

### 3. OpenRouter — Inline Usage + Credits

**Confidence:** HIGH (verified against OpenRouter docs).

OpenRouter takes a fundamentally different shape: it does **not** offer a date-range aggregated cost endpoint. Instead it offers (a) **inline usage on every chat-completion response** and (b) a **per-generation lookup** endpoint and (c) a **credit balance** endpoint.

**Endpoints:**

| Endpoint | Method | Purpose |
|---|---|---|
| `https://openrouter.ai/api/v1/credits` | GET | Total credits purchased and used |
| `https://openrouter.ai/api/v1/key` | GET | Per-key limits, `usage`, `usage_daily`, `usage_weekly`, `usage_monthly`, `byok_usage` |
| `https://openrouter.ai/api/v1/generation?id=<gen_id>` | GET | Full metadata for a specific completion |
| `https://openrouter.ai/api/v1/chat/completions` | POST | Returns cost & token usage inline in response body |

**Auth:** `Authorization: Bearer <key>`. The credits endpoint requires a "Management key" per docs — for personal accounts this is the same key.

**Auto-included usage on every completion** (verified MEDIUM confidence — see deprecation note):

Per OpenRouter docs, the deprecated parameters `usage: { include: true }` and `stream_options: { include_usage: true }` are no longer required — full usage is **always** returned. The `usage` object includes:
- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `cached_tokens`, `cache_write_tokens`
- `cost` — total amount charged to your account (USD)
- `cost_details.upstream_inference_cost` — actual cost charged by upstream provider
- `is_byok` flag

**`/api/v1/generation` response fields:**

- IDs/timing: `id`, `request_id`, `session_id`, `created_at`, `generation_time`, `latency`, `moderation_latency`
- Model: `model`, `provider_name`, `router`, `api_type`, `service_tier`
- Tokens: `tokens_prompt`, `tokens_completion`, `native_tokens_prompt`, `native_tokens_completion`, `native_tokens_cached`, `native_tokens_reasoning`
- Cost: `total_cost`, `upstream_inference_cost`, `cache_discount`
- Metadata: `origin`, `is_byok`, `streamed`, `finish_reason`

**`/api/v1/key` response fields:**

- `label`, `limit`, `limit_reset`, `limit_remaining`
- `usage` (all-time), `usage_daily`, `usage_weekly`, `usage_monthly` (UTC periods)
- `byok_usage`, `is_free_tier`

**Time granularity:**

- Real-time per generation: full detail
- Daily/weekly/monthly: only **aggregate totals** via `/key` endpoint (not breakdown by model)
- **No native by-model historical aggregation endpoint exists.**

**Integration strategy for OpenRouter:**

Two paths:

1. **For the existing dashboard's own OpenRouter usage:** poll `/api/v1/key` daily to capture the daily/weekly/monthly totals. Cheap, but no model breakdown.
2. **For full model-level history:** scrape the Activity page (CSV export available in the UI) or — better — **start logging every completion response's `usage` block into our DB at request time** (inline accounting). This requires intercepting all our agentic traffic through OpenRouter, which we already do for development. For backfill of historical data, the Activity CSV is the only path.

**Gotchas:**

1. **No date-range aggregation API** — biggest gap vs Anthropic/OpenAI. We must accept either inline logging going forward, or daily polling of `/key`.
2. **5.5% purchase fee** ($0.80 minimum) on credit purchases — `total_credits` from `/credits` is post-fee; the fee itself is not exposed.
3. **`limit_remaining: null`** means unlimited — handle null specially.
4. **Free models have a separate rate limit** (varies by purchase history) and won't be in the cost data.
5. **Negative balance returns HTTP 402** — handle this in error paths.
6. **Streaming responses:** usage object is in the **final SSE chunk before `[DONE]`** — must read the whole stream to get cost (not just consume the deltas).
7. **`/api/v1/generation` has a small propagation delay** — wait ~1s after a completion before querying or you'll get 404.

**Source:** [OpenRouter Credits docs](https://openrouter.ai/docs/api/api-reference/credits/get-credits), [Generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-generation), [Usage Accounting](https://openrouter.ai/docs/guides/administration/usage-accounting)

---

### 4. Kilo.ai — No Dedicated Billing API (verified)

**Confidence:** MEDIUM-HIGH. Verified by reading the published Kilo Gateway docs across multiple pages. No usage-history endpoint is documented. Confidence is not HIGH because we cannot rule out an undocumented internal endpoint used by the dashboard at `app.kilo.ai`.

**What Kilo exposes:**

- Base URL: `https://api.kilo.ai/api/gateway`
- Endpoints: `POST /chat/completions`, `POST /api/fim/completions`, `GET /models`, `GET /providers`
- **No documented `/usage`, `/billing`, `/balance`, `/activity` endpoint exists.**

**Auth:**

- `Authorization: Bearer <KILO_API_KEY>` — JWT tied to a Kilo account
- Optional: `X-KiloCode-OrganizationId`, `X-KiloCode-TaskId`
- Org tokens: 15-minute expiry, enforce org policies

**What we CAN extract (inline only):**

Per-request `usage` object returned in the chat completion response body (non-streaming) or final SSE chunk (streaming):

- `model`, `provider` (backend serving the request)
- `input_tokens`, `output_tokens`
- `cache_write_tokens`, `cache_hit_tokens`
- **`cost_microdollars`** — Cost in microdollars (1 USD = 1,000,000)
- `time_to_first_token` (streaming only)
- `is_byok` boolean

**Balance check:**

- Only via the dashboard at https://app.kilo.ai/credits
- HTTP 402 with link is returned when balance hits zero
- **No `GET /balance` or `GET /credits` endpoint** is publicly documented

**Time granularity:** Per-request only. No historical query.

**Integration strategy for Kilo (the hard one):**

Since there's no backfill API, our **only** options are:

1. **Inline accounting** — log every Kilo completion response's `usage` block to our DB at request time. This requires all Kilo traffic to flow through our recording layer. For a personal coding workflow this is feasible (we control the Kilo Code extension config), but we lose history before the integration ships.
2. **Browser-session scraping** — reverse-engineer the dashboard's XHR calls. **Fragile, not recommended.**
3. **Manual CSV export** if Kilo provides one in the dashboard (unconfirmed — needs runtime check by the user against their actual Kilo account).

**Gotchas:**

1. **No backfill possible** without scraping. Document this gap clearly.
2. **BYOK requests show `cost_microdollars = 0`** on Kilo's side (you pay the upstream provider directly). To track BYOK spend, we need to integrate with the underlying provider (Anthropic/OpenAI) and correlate.
3. **Cost is in microdollars (integer)** — different unit from every other provider. Convert on ingest.
4. **Anonymous free-model requests** (200/hr per IP) are not tied to a key.
5. **The "Kilo Pass" tiered plan** (existing `kilo_plans.yaml`) is a *prepaid subscription* model. Spend tracking for Pass users is fundamentally different from PAYG and may need separate handling.

**Action item:** Before committing to the integration, **manually verify in the Kilo dashboard** (`app.kilo.ai`) whether (a) a CSV/JSON usage export exists in the UI and (b) the XHR calls behind the dashboard. If a stable endpoint exists, it's likely usable even if undocumented; if not, inline accounting is the only path.

**Source:** [Kilo Gateway overview](https://kilo.ai/docs/gateway), [API reference](https://kilo.ai/docs/gateway/api-reference), [Usage & Billing](https://kilo.ai/docs/gateway/usage-and-billing), [Authentication](https://kilo.ai/docs/gateway/authentication)

---

## Coding Benchmarks — Public Data Sources

**Confidence:** HIGH for Aider polyglot (raw YAML file in GitHub). MEDIUM for LiveCodeBench / SWE-bench (web/HF Space, not a stable API).

There is **no unified coding-benchmarks API.** The best programmatic sources, ranked by reliability:

### Aider Polyglot Leaderboard (recommended primary source)

- **Raw URL:** `https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml`
- **Format:** YAML, one entry per (model, edit_format) combination
- **Fields per entry:** `model`, `edit_format`, `pass_rate_1`, `pass_rate_2`, `percent_cases_well_formed`, `seconds_per_case`, `total_cost`, `test_cases` (225), `commit_hash`, `date`, `versions`, `command`
- **Coverage:** 40+ models, regularly updated, last update tracked by Paul Gauthier
- **Why this:** Includes both **pass rate AND cost** per model — perfect for our "cost vs capability" dashboard premise. Already YAML which our stack handles natively.

### LiveCodeBench

- **HuggingFace Space:** https://huggingface.co/spaces/livecodebench/leaderboard
- **HF Dataset:** https://huggingface.co/datasets/livecodebench/code_generation
- **No stable JSON API** — must either (a) scrape the HF Space HTML, (b) use HF datasets library to load the source dataset and compute scores ourselves (heavy), or (c) accept manual updates
- **Recommendation:** **Defer** to phase 2. Not worth the scraping effort initially.

### SWE-bench

- **Official site:** https://www.swebench.com/
- **Leaderboard:** HTML tables on swebench.com; no documented JSON endpoint
- **Aggregator with API-ish access:** llm-stats.com hosts JSON-backed leaderboards but is a third-party (stability unknown)
- **Recommendation:** **Defer** or use the aggregator [llm-stats.com/benchmarks/swe-bench-verified](https://llm-stats.com/benchmarks/swe-bench-verified) with explicit "third-party, may break" caveat.

### HumanEval

- Saturated (most frontier models score 90%+); **low signal-to-noise for differentiation**.
- Numbers are reported in model cards, no single source of truth.
- **Recommendation:** Skip. The benchmark is no longer useful for ranking 2026-era coding models.

### Recommended approach for benchmarks panel

1. **Phase 1:** Weekly k8s CronJob fetches `polyglot_leaderboard.yml` via httpx, parses with PyYAML, persists to a new `coding_benchmark` table keyed on (model, edit_format, benchmark='aider_polyglot'). Display pass_rate_2 + total_cost.
2. **Phase 2:** Add LiveCodeBench via HF Space scrape **or** manual JSON file we maintain.
3. **Phase 2:** Add SWE-bench Verified from llm-stats (third-party) with confidence flag in UI.

---

## Alternatives Considered

| Decision | Recommended | Alternative | Why Not |
|---|---|---|---|
| HTTP client | httpx (existing) | aiohttp | Already standardized on httpx in services/openrouter.py; switching is churn for no win |
| Anthropic key type | Admin API key | Standard API key | Standard keys cannot read org-wide usage; admin key is the only option |
| OpenAI key type | Admin API key | Project key | Project keys can't query org costs; admin key is required |
| Kilo strategy | Inline accounting | Backfill API | No backfill API exists |
| Benchmark source | Aider GitHub raw YAML | Scraping HF Space | YAML is stable, schema-versioned, and already in our YAML toolchain |
| Polling cadence | k8s CronJob (existing pattern) | apscheduler in-process | CronJobs are visible, restartable, and already used for `refresh-pricing`/`daily-report`/`kilo-diff` |
| Storage | Append-only `provider_usage_snapshot` table | Overwrite-latest | Matches existing price-history shape; supports historical querying |
| Cost normalization | All stored in USD as `Decimal` cents | Provider-native units | Avoids microdollar/cents/dollars conversion at query time |

---

## Installation

**No new pip packages required.** All dependencies are already in `api/pyproject.toml`:

- `httpx 0.27.2` — provider HTTP calls
- `tenacity 9.0.0` — retry/backoff
- `pydantic 2.9.2` — response schemas
- `SQLAlchemy 2.0.36` + `asyncpg 0.30.0` + `Alembic 1.13.3` — new tables + migration
- `PyYAML 6.0.2` — Aider leaderboard parsing
- `redis 5.2.0` — cache provider responses (15-min TTL matches existing pattern)

**Environment variables to add** (delivered via existing `model-pricing-secrets`):

```bash
ANTHROPIC_ADMIN_KEY=sk-ant-admin-...
OPENAI_ADMIN_KEY=sk-admin-...
OPENROUTER_API_KEY=sk-or-v1-...     # may already exist
KILO_API_KEY=...
```

**New k8s CronJobs:**

```
refresh-anthropic-spend   (every 1h, calls cost_report + usage_report)
refresh-openai-spend      (every 1h, calls /organization/costs + /usage/completions)
refresh-openrouter-spend  (every 6h, polls /key endpoint snapshots)
refresh-benchmarks        (weekly, fetches polyglot_leaderboard.yml)
```

Kilo spend is captured inline at request time (no cron) — requires a request-logging service or BYOK-correlation if relevant.

---

## Sources

**Anthropic:**
- [Usage and Cost API docs](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api)
- [Admin API overview](https://platform.claude.com/docs/en/manage-claude/admin-api)
- [Cookbook: Usage & cost Admin API](https://platform.claude.com/cookbook/observability-usage-cost-api)

**OpenAI:**
- [Cookbook: Completions Usage API](https://developers.openai.com/cookbook/examples/completions_usage_api)
- [Costs API reference](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)
- [Admin keys settings](https://platform.openai.com/settings/organization/admin-keys)

**OpenRouter:**
- [Credits API](https://openrouter.ai/docs/api/api-reference/credits/get-credits)
- [Generation metadata API](https://openrouter.ai/docs/api/api-reference/generations/get-generation)
- [Usage Accounting](https://openrouter.ai/docs/guides/administration/usage-accounting)
- [API rate limits](https://openrouter.ai/docs/api/reference/limits)

**Kilo.ai:**
- [Gateway overview](https://kilo.ai/docs/gateway)
- [API reference](https://kilo.ai/docs/gateway/api-reference)
- [Usage & Billing](https://kilo.ai/docs/gateway/usage-and-billing)
- [Authentication](https://kilo.ai/docs/gateway/authentication)

**Benchmarks:**
- [Aider polyglot leaderboard](https://aider.chat/docs/leaderboards/)
- [Aider polyglot data file (GitHub)](https://github.com/Aider-AI/aider/blob/main/aider/website/_data/polyglot_leaderboard.yml)
- [LiveCodeBench leaderboard](https://huggingface.co/spaces/livecodebench/leaderboard)
- [SWE-bench official](https://www.swebench.com/)
- [llm-stats.com benchmarks aggregator](https://llm-stats.com/benchmarks/aider-polyglot) (third-party)
