# Functional Specification: AI Model Pricing Dashboard

## Overview

The AI Model Pricing Dashboard tracks and compares Large Language Model (LLM) token costs. It reads the OpenRouter model catalog (models from OpenAI, Anthropic, Google, and many other vendors) and the Kilo AI Gateway catalog, normalizes prices to one metric (USD per 1M tokens), ranks models for coding workloads, and compares the effective cost of the same model across five purchasing channels.

## Core Features

### 1. Real-Time Pricing Aggregation

- **Catalog**: The OpenRouter `/models` catalog, plus Kilo's gateway catalog at `/kilo/models`
- **Automatic refresh**: The `refresh-pricing` CronJob fetches OpenRouter `/models` (public, no cost). Its cadence is `OPENROUTER_REFRESH_SECONDS`, every 5 minutes in the shipped k8s config, and the CronJob schedule must match it
- **Redis caching**: The models cache TTL is `3 × OPENROUTER_REFRESH_SECONDS`, so it never expires between refresh runs (2700s with the local default of 900s; 900s in prod, where the interval is 300s). Concurrent cache misses share one refresh. The cache falls back to in-process memory if Redis is unreachable
- **History tracking**: Hourly pricing snapshots in Postgres, pruned after `SNAPSHOT_RETENTION_DAYS` (default 90), drive the trend views
- **Speed data**: Each model carries OpenRouter's advertised default-route p50 throughput (`throughput_tps`) and latency (`latency_ms`), with the provider the sample came from

### 2. Intelligent Model Ranking

- **Blended cost metric**: `0.30 × input $/Mtok + 0.70 × output $/Mtok` (weights configurable)
- **Capability filtering**:
  - Minimum context window: 1M tokens
  - Tool calling support required
  - Cost bounds: input ≤ $10/Mtok, output ≤ $40/Mtok
  - Excludes free models and lightweight variants matching `RANK_EXCLUDE_PATTERNS` (`flash-lite`, `flash-8b`, `learnlm`)
- **Dynamic top-N ranking**: Computed per request from current pricing

### 3. Channel Comparison

Compare the same model across five purchasing channels:

- **OpenRouter PAYG**: Pass-through price plus the credit-purchase fee (`OPENROUTER_PAYG_FEE_PCT`, default 5.5%)
- **OpenRouter BYOK**: Bring-your-own-key at list price (+0%). OpenRouter charges no fee on the first $25,000/month of list-price BYOK inference (`OPENROUTER_BYOK_FREE_ALLOWANCE_USD`, default 25000)
- **OpenRouter BYOK, past the allowance**: List price plus the BYOK fee (`OPENROUTER_BYOK_FEE_PCT`, default 5.0%), charged to OpenRouter credits. The app never infers whether the allowance is exhausted; both rows are estimates and the upstream provider bills the inference itself. Sources: https://openrouter.ai/docs/guides/overview/auth/byok and https://openrouter.ai/pricing
- **Kilo Pass**: Kilo subscription credits with the tier's streak or annual bonus applied as an effective discount (tiers `starter`, `pro`, `expert`)
- **Kilo BYOK**: True passthrough, no markup

### 4. Kilo AI Gateway Integration

- **Tier definitions**: `api/app/data/kilo_plans.yaml` (monthly price, paid credits, per-tier `max_bonus_pct`, annual bonus)
- **Kept in sync automatically**: the weekly `kilo-diff` job detects changes to kilo.ai/pricing and updates the yaml (see Scheduled Jobs)
- **Streak bonuses**: Month 1 gets the welcome bonus. Month n ≥ 2 gets `min(step_pct × n, cap)`, where `cap` is the plan's own `max_bonus_pct` and never exceeds the global `cap_pct` (40% by month 8 today)
- **Annual prepayment**: Flat annual bonus per month
- **Live model availability**: Kilo's gateway catalog. If the gateway is unreachable the endpoints answer **503**, not an empty list
- **Projection calculator**: Effective credits for a tier, streak and billing mode

### 5. Account Balance & Usage

- **OpenRouter**: Credit balance (limit, spent, remaining) via `/credits`
- **Kilo**: Key validation and available model count (the gateway has no spend or balance endpoint), plus the configured plan from `KILO_TIER`
- **OpenRouter usage**: From the beta `/analytics/query` endpoint, which includes the current UTC day. It needs a management key, so only `OPENROUTER_ADMIN_KEY` is used (a regular key gets HTTP 403); without it the status is `unconfigured` and no request is made
  - **Windows**: `period=today` (default), `7d` or `30d`, in `America/Denver` local time. The start is local midnight of the first day converted to UTC per date (DST-correct); the end is "now", so the current day is always partial. The window is sent as an explicit `time_range` (`YYYY-MM-DDTHH:MM:SSZ`); OpenRouter silently ignores top-level `start`/`end` fields. Without a time range OpenRouter returns its default of the last 7 days
  - **Grouping**: `group_by=model` (default), `api_key` or `app`; each row's `caller` is that key or app label (`null` when OpenRouter reports none)
  - **Three amounts, never mixed**: `credits_usd` is billed to OpenRouter credits (it includes BYOK fees); `byok_usd` is upstream BYOK inference billed by the provider, not by OpenRouter; `total_usd` / `totals.combined_usd` is their sum ("combined usage"). `byok_fees` is not requested: it changes the result set, and it is already inside `credits_usage`
  - **Honest gaps**: A malformed row is skipped and counted. A missing, non-numeric or non-finite value becomes `null`, never 0, and totals sum only the values present. `status` is `incomplete` (with `warnings`) when a row was skipped, a billing value was missing, credits + BYOK differs from the total by more than 1e-6, or results were truncated (or OpenRouter did not say). Failures give `status: error` with an `error` message; a missing key gives `unconfigured`
  - **Not the same as your provider bill**: `credits_usd` is what OpenRouter metered against your OpenRouter credits. `byok_usd` is OpenRouter's record of the upstream cost of BYOK requests: the provider bills that amount on its own invoice, and provider credits may cover it, so it is neither an OpenRouter charge nor a provider credit balance. The `/compare` channel rates are list-price estimates, separate from both. For example, a Claude Max 5x plan includes a $100/month Claude API credit on one linked Anthropic Console organization (it expires monthly and does not cover Claude Code). It can cover Anthropic API usage billed to that organization, such as an Anthropic BYOK key from it, but never OpenAI embeddings. Source: https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers
- **Caching**: `/accounts/usage` is cached 2 minutes. `/accounts/activity` is cached per `period` and `group_by` under `accounts:activity:v2:<period>:<group_by>`: 5 minutes for `today`, 15 minutes for `7d` and `30d`. An entry in the old shape, or from a previous local day, is ignored. Either endpoint is cached only 30 seconds when an upstream call failed; `unconfigured` is never cached
- **Visibility**: The web proxy forwards `/accounts/*` only when `EXPOSE_ACCOUNT_DATA=true`. Otherwise the account panel and "your usage" figures are hidden

### 6. Historical Trend Analysis

- **Price history**: Hourly snapshots per model (`/models/{id}/history`, 1–365 days)
- **Trend views**: Input/output cost over time on a time axis, in the model modal and the Pricing Trends pages

### 7. Speed Benchmark Page

- **`/speed`**: Live results from the separate model-speed service (fastest free model across Kilo and OpenRouter: latest probe results, leaderboard, fallback chain and recent runs), fetched directly by the browser and refreshed every 60 seconds

### 8. Dark/Light Mode

- **System preference detection** with a manual toggle
- **Design tokens**: CSS variables keep charts and tables consistent across themes

## API Endpoints

### Health & Observability

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `GET /healthz` | GET | `{"status": "ok"}` | Kubernetes liveness probe |
| `GET /readyz` | GET | `{"db": true, "redis": true, "ready": true}` | Kubernetes readiness probe. Both checks run concurrently under a 2s budget. **503 only when Postgres is down**. A Redis outage returns 200 with `redis: false`, because the cache falls back to process memory |
| `GET /metrics` | GET | Prometheus text format | Request count and latency by method, route template and status. Not forwarded by the public web proxy |

### Models

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /models` | GET | `refresh=false` | `[ModelPricing]` | Full model catalog (cached) |
| `GET /models?refresh=true` | GET | `refresh=true` | `[ModelPricing]` | Bypass the cache. In-cluster only: the web proxy strips `refresh` |
| `GET /models/top` | GET | `n=10` (1–50) | `[RankedModel]` | Top-N models by blended cost |
| `GET /models/{model_id}` | GET | — | `ModelPricing` | Single model details (404 if unknown) |
| `GET /models/{model_id}/history` | GET | `days=30` (1–365) | `[ModelPricing]` | Historical pricing snapshots |

**Response Schema: ModelPricing**
```json
{
  "id": "anthropic/claude-sonnet-4.6",
  "name": "Anthropic: Claude Sonnet 4.6",
  "provider": "anthropic",
  "prompt_usd_per_mtok": 3.0,
  "completion_usd_per_mtok": 15.0,
  "request_usd": 0.0,
  "image_usd": 0.0,
  "context_length": 1000000,
  "max_completion_tokens": 64000,
  "supports_tools": true,
  "supports_vision": true,
  "throughput_tps": 62.0,
  "latency_ms": 1450.0,
  "speed_provider": "Anthropic",
  "captured_at": "2026-09-26T08:30:00Z"
}
```

**Response Schema: RankedModel**
```json
{
  "model": { ...ModelPricing... },
  "score": 88.0,
  "blended_usd_per_mtok": 12.0,
  "rank": 1
}
```

### Comparison

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /compare/{model_id}` | GET | `kilo_tier`, `kilo_streak_months`, `kilo_annual=false` (all optional) | `ModelComparison` | Compare pricing across 5 channels |

`kilo_tier` defaults to the configured `KILO_TIER`, and must be `starter`, `pro` or `expert` if given (anything else returns **422**). `kilo_streak_months` defaults to the steady-state streak, the month the bonus reaches its cap in `kilo_plans.yaml` (month 8 today). It must be 1–120 if given. The month-1 welcome bonus is one-off, so it is only used when asked for explicitly. The dashboard and All Models modals send neither value. Returns 404 if `model_id` is not in the catalog.

**Response Schema: ModelComparison** (base price 3.0/15.0, `pro`, month 8)
```json
{
  "model": { ...ModelPricing... },
  "channels": [
    {
      "channel": "openrouter_payg",
      "prompt_usd_per_mtok": 3.165,
      "completion_usd_per_mtok": 15.825,
      "notes": "+5.5% credit purchase fee"
    },
    {
      "channel": "openrouter_byok",
      "prompt_usd_per_mtok": 3.0,
      "completion_usd_per_mtok": 15.0,
      "notes": "No OpenRouter fee within the first $25,000/mo of list-price BYOK inference; 5% of list price after (charged to OpenRouter credits). Estimate; inference is billed by the upstream provider."
    },
    {
      "channel": "openrouter_byok_over_allowance",
      "prompt_usd_per_mtok": 3.15,
      "completion_usd_per_mtok": 15.75,
      "notes": "Past the $25,000/mo BYOK allowance: +5% of list price (charged to OpenRouter credits). Estimate; inference is billed by the upstream provider."
    },
    {
      "channel": "kilo_pass",
      "prompt_usd_per_mtok": 2.1429,
      "completion_usd_per_mtok": 10.7143,
      "notes": "tier=pro, month 8, 28.6% effective discount"
    },
    {
      "channel": "kilo_byok",
      "prompt_usd_per_mtok": 3.0,
      "completion_usd_per_mtok": 15.0,
      "notes": "true passthrough"
    }
  ]
}
```

A 40% bonus means $1 paid buys $1.40 of credits, so the effective discount is `1 - 1/1.4 = 28.6%`.

### Kilo AI Gateway

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /kilo/plans` | GET | — | `[KiloPlan]` | Kilo Pass tiers from `kilo_plans.yaml` |
| `GET /kilo/models` | GET | — | `[ModelPricing]` | Models on the Kilo gateway. **503** if the gateway is unreachable; `[]` only if no key is configured or Kilo returns an empty catalog |
| `GET /kilo/models/{model_id}` | GET | — | `ModelPricing` | Single Kilo model. 404 if Kilo does not carry it, **503** if the gateway could not be reached |
| `GET /kilo/projection` | GET | `tier=pro&streak_months=8&annual=false` | `KiloProjection` | Effective credits for a tier and streak |

`tier` must be `starter`, `pro` or `expert`; any other value returns **422**.

**Response Schema: KiloPlan**
```json
{
  "tier": "pro",
  "monthly_usd": 49.0,
  "paid_credits_usd": 49.0,
  "max_bonus_pct": 0.40,
  "annual_usd": 588.0,
  "annual_bonus_pct": 0.50
}
```

**Response Schema: KiloProjection**
```json
{
  "tier": "pro",
  "streak_months": 8,
  "paid_credits_usd": 49.0,
  "bonus_pct": 0.40,
  "bonus_credits_usd": 19.6,
  "total_effective_credits_usd": 68.6
}
```

### Account Activity

These are reachable through the web proxy only when `EXPOSE_ACCOUNT_DATA=true`.

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `GET /accounts/usage` | GET | `AccountsUsage` | OpenRouter credit balance and Kilo key/plan status |
| `GET /accounts/activity?period=today\|7d\|30d&group_by=model\|api_key\|app` | GET | `ActivityResponse` | OpenRouter usage for an `America/Denver` window ending now (default `today`, partial), split into credits, BYOK and combined. Invalid values return 422 |

**Response Schema: AccountsUsage**
```json
{
  "openrouter": {
    "provider": "openrouter",
    "configured": true,
    "plan": null,
    "limit_usd": 500.0,
    "spent_usd": 123.45,
    "remaining_usd": 376.55,
    "period_start": null,
    "model_count": null,
    "error": null
  },
  "kilo": {
    "provider": "kilo",
    "configured": true,
    "plan": "Starter $19/mo",
    "limit_usd": 19.0,
    "spent_usd": null,
    "remaining_usd": null,
    "period_start": null,
    "model_count": 42,
    "error": null
  },
  "fetched_at": "2026-09-26T08:30:00Z"
}
```

**Response Schema: ActivityResponse**
```json
{
  "period": {
    "key": "today",
    "timezone": "America/Denver",
    "start": "2026-10-14T06:00:00Z",
    "end": "2026-10-14T20:00:00Z",
    "start_date": "2026-10-14",
    "end_date": "2026-10-14",
    "partial": true
  },
  "group_by": "api_key",
  "status": "complete",
  "items": [
    {
      "model_id": "anthropic/claude-opus-5.5-20260921",
      "caller": null,
      "requests": 16,
      "prompt_tokens": 188976,
      "completion_tokens": 17598,
      "reasoning_tokens": 8277,
      "credits_usd": 0.042,
      "byok_usd": 0.672047,
      "total_usd": 0.714047
    }
  ],
  "totals": { "credits_usd": 0.042, "byok_usd": 0.672047, "combined_usd": 0.714047 },
  "truncated": false,
  "warnings": [],
  "error": null,
  "fetched_at": "2026-10-14T20:00:01Z"
}
```

`status` is `complete`, `incomplete`, `unconfigured` or `error`. Item fields and totals are `null` when OpenRouter did not supply them.

## Frontend Features

### Pages

1. **Dashboard (`/`)**: The account panel (when exposed) and the Top 10 coding models
2. **Model detail modal**: Context, max output, speed and latency, tool/vision support, your 30-day usage (when exposed), the five-channel comparison table and bar chart, and a 30-day price history on a time axis. The Kilo Pass row uses `KILO_TIER` at the steady-state streak. Load errors are shown in the dialog
3. **All Models (`/trends`)**: The full catalog table, opening the same modal
4. **Pricing Trends (`/pricing-trends`)**: Price trends over time for the top coding models
5. **Speed (`/speed`)**: Live model-speed benchmark (see Core Features 7)
6. **About**: Feature overview, architecture, and integration notes

### Web proxy

The browser calls `/api/*` on the web origin. A Next.js route handler reads `API_BASE_URL` at runtime and forwards only an allowlist of read-only endpoints (`models`, `compare`, `kilo`, `healthz`). It strips `refresh`, rejects dot segments, and forwards `/accounts/usage` and `/accounts/activity` only when `EXPOSE_ACCOUNT_DATA=true`. `/metrics`, `/docs` and the OpenAPI schema are never forwarded. Successful public responses carry `cache-control: public, max-age=60`; account data and errors are `no-store`.

### Refresh behavior

- **SWR polling**: Catalog, ranking, comparison and projection queries refresh every 5 minutes; account activity every 15 minutes; the speed page every 60 seconds. No refetch on window focus
- **Account errors**: A 404 from `/accounts/*` means "not exposed" and is not retried; other errors retry with backoff capped at 5 minutes
- **Inputs**: The Kilo streak input is clamped to 1–120 and query values are URL-encoded

## Data Models

**ModelPricing**
- `id`, `name`, `provider`
- `prompt_usd_per_mtok`, `completion_usd_per_mtok`: USD per 1M tokens
- `request_usd` / `image_usd`: Per-request / per-image surcharge, if any
- `context_length`, `max_completion_tokens`
- `supports_tools`, `supports_vision`
- `throughput_tps`, `latency_ms`, `speed_provider`: OpenRouter's advertised default-route speed (nullable)
- `captured_at`: Timestamp of the pricing capture

**RankedModel**
- `model`: ModelPricing
- `score`: 0–100, higher is better (`100 - blended_usd_per_mtok`, floored at 0)
- `blended_usd_per_mtok`: Weighted cost metric
- `rank`: 1 = lowest blended cost

**ModelComparison**
- `model`: ModelPricing
- `channels`: Five entries, each with `channel` (`openrouter_payg`, `openrouter_byok`, `openrouter_byok_over_allowance`, `kilo_pass`, `kilo_byok`), `prompt_usd_per_mtok`, `completion_usd_per_mtok` and `notes`

## Scheduled Jobs (CronJobs)

### refresh-pricing
- **Schedule**: Every 5 minutes (`*/5 * * * *`), matching `OPENROUTER_REFRESH_SECONDS=300` in the shipped config
- **Action**: Fetch OpenRouter `/models`, normalize (a malformed record is skipped, not fatal), update the Redis cache, write one batched hourly snapshot to Postgres, and prune snapshots older than `SNAPSHOT_RETENTION_DAYS`
- **Failure handling**: The fetch retries up to 3 times with exponential backoff. A failed run exits non-zero and the Job retries (`backoffLimit: 4`)

### daily-report
- **Schedule**: Daily at 08:00 America/Denver (`spec.timeZone`)
- **Action**: Email the top 5 coding models and projected monthly savings. Savings use the configured `KILO_TIER` at the steady-state streak (the month the bonus reaches its cap), not the one-off month-1 welcome bonus. The email states the actual ranking criteria from settings
- **Customization**: Baseline model and monthly token volume are constants in `daily_report.py` (see Extensibility)

### kilo-diff
- **Schedule**: Weekly, Mondays at 07:00 America/Denver
- **Action**: Hash the visible text of kilo.ai/pricing and compare it with the last hash stored in Postgres (`kilo_plan_snapshot`, not Redis). On a change:
  1. Extract the per-tier figures with an LLM (`KILO_EXTRACTION_MODEL`)
  2. Sanity-check them against the current yaml (`KILO_SANITY_MAX_DELTA_PCT`)
  3. If they pass and actually differ, commit the updated `kilo_plans.yaml` to `main` through the GitLab API; CI then builds and deploys it, and an FYI email is sent
  4. If extraction fails or looks implausible, email a manual-review alert instead
- **Baseline**: The new hash is recorded only after the change was handled. If the GitLab commit fails, or the manual-review alert cannot be delivered (SMTP not configured), the job exits non-zero and keeps the old baseline, so the change is retried on the next run. The first run after deploy records a baseline and cannot detect a change

## Environment Configuration

### Required

- `DATABASE_URL`: PostgreSQL connection using the `postgresql+psycopg` (psycopg 3) driver
- `REDIS_URL`: Redis endpoint with optional password. Optional in practice: an unreachable or invalid URL falls back to in-process memory

### Optional (for features)

- `OPENROUTER_API_KEY`: For `/credits` and the kilo-diff extraction call
- `OPENROUTER_ADMIN_KEY`: Management key for `/analytics/query`; required for `/accounts/activity` (a regular key gets HTTP 403)
- `KILO_API_KEY`: Kilo gateway credentials
- `KILO_BASE_URL`: Kilo gateway host (default `https://api.kilo.ai/api/gateway`); an env override for riding out a gateway outage
- `KILO_TIER`: Active Kilo tier, `starter` / `pro` / `expert` (case-insensitive, default `starter`). Any other value fails at startup
- `KILO_EXTRACTION_MODEL`, `KILO_SANITY_MAX_DELTA_PCT`: kilo-diff extraction model and plausibility bound. The model default is the OpenRouter slug `anthropic/claude-haiku-5.5` (the native Anthropic id `claude-haiku-5-5` is not valid there). The request sends no sampling parameters, because Haiku 5.5 rejects non-default `temperature`; an empty reply (thinking can use the whole token budget) fails the extraction with the `finish_reason` and triggers the manual-review email instead of a commit
- `GITLAB_TOKEN`, `GITLAB_API_URL`, `GITLAB_PROJECT_ID`, `GITLAB_PROJECT_PATH`: kilo-diff auto-commit target
- `SMTP_*`: Email for the daily report and kilo-diff alerts

### Web

- `API_BASE_URL`: Backend URL for the web proxy, read at runtime (default `http://localhost:8000`)
- `EXPOSE_ACCOUNT_DATA`: `true` to forward `/accounts/*` through the public proxy. Set it only when the site is behind authentication

### Tuning

- `RANK_INPUT_WEIGHT` / `RANK_OUTPUT_WEIGHT`: Blended-cost weights (default 0.30 / 0.70)
- `RANK_MIN_CONTEXT_TOKENS`: Minimum context window (default 1,000,000)
- `RANK_MAX_INPUT_PRICE` / `RANK_MAX_OUTPUT_PRICE`: Cost bounds in USD/Mtok (default 10.0 / 40.0)
- `RANK_TOP_N`: Default size of `/models/top` (default 10)
- `RANK_EXCLUDE_PATTERNS`: Model-id substrings excluded from the ranking
- `OPENROUTER_REFRESH_SECONDS`: Expected interval between refresh runs (default 900; the models cache TTL is 3× this)
- `SNAPSHOT_RETENTION_DAYS`: Snapshot retention before pruning (default 90; 0 disables pruning)
- `CACHE_TTL_SECONDS`: Default cache duration for other keys (default 900)
- `OPENROUTER_PAYG_FEE_PCT` / `OPENROUTER_BYOK_FEE_PCT`: Channel markups (default 0.055 / 0.05); the BYOK fee applies only past the free allowance
- `OPENROUTER_BYOK_FREE_ALLOWANCE_USD`: Monthly list-price BYOK inference with no OpenRouter fee (default 25000)

## Security

- **No secrets in code**: Credentials come from the environment or Kubernetes secrets; `secret.example.yaml` holds placeholders only
- **Public surface**: Only the web Service is exposed, through the Traefik Gateway HTTPRoute. The API is ClusterIP, and the web proxy forwards an allowlist (see Web proxy)
- **Account data**: Hidden unless `EXPOSE_ACCOUNT_DATA=true`
- **Metrics**: Labelled by route template, so arbitrary URLs cannot create unbounded Prometheus series
- **Containers**: Non-root (UID 1000), capabilities dropped, read-only root filesystems with emptyDir mounts where the process writes
- **Request logging**: Structured JSON logs (structlog) and Prometheus request/latency metrics; no per-user identity is captured
- **Data retention**: Snapshot retention via `SNAPSHOT_RETENTION_DAYS` (default 90 days)

## Performance Characteristics

- **Cached endpoints** are served from Redis (or process memory) without an upstream call
- **History queries** use the `(model_id, captured_at)` unique index
- **Comparison and projection** are in-memory calculations
- **Scaling**: One uvicorn worker per API pod; scale with replicas. No session affinity is needed

## Extensibility

### Adding a New Provider

1. Create `app/services/new_provider.py` following the OpenRouter pattern
2. Implement `list_models()`, `get_model()` and, if you persist snapshots, `get_history()`
3. Add a router in `app/routes/` and include it in `app/main.py`
4. Add settings for credentials in `app/config.py`
5. If browsers should reach it, add its path to the web proxy allowlist in `web/src/app/api/[...path]/route.ts`

### Customizing Ranking

Set via environment (or edit the defaults in `app/config.py`):
```
RANK_INPUT_WEIGHT=0.30          # adjust for your workload
RANK_OUTPUT_WEIGHT=0.70         # should sum to 1.0
RANK_MIN_CONTEXT_TOKENS=1000000
RANK_MAX_INPUT_PRICE=10.0
RANK_MAX_OUTPUT_PRICE=40.0
RANK_TOP_N=10
```

Tool-calling support is always required for the coding ranking. Restart the service to apply; the ranking is recomputed on the next `/models/top` request.

### Custom Reports

Edit the constants in `app/jobs/daily_report.py` (they are not env vars):
```python
BASELINE_MODEL_ID = "anthropic/claude-sonnet-4.6"
BASELINE_INPUT_MTOK = 5   # millions of input tokens per month
BASELINE_OUTPUT_MTOK = 5  # millions of output tokens per month
```
