# Functional Specification: AI Model Pricing Dashboard

## Overview

The AI Model Pricing Dashboard is a production-grade system for real-time tracking, comparison, and optimization of Large Language Model (LLM) costs across multiple providers. It aggregates pricing data from OpenRouter, OpenAI, Anthropic, and Kilo AI Gateway, normalizing costs to a common metric (USD per 1M tokens) for instant comparison and data-driven model selection.

## Core Features

### 1. Real-Time Pricing Aggregation

- **Multi-provider catalog**: Unified view of 100+ models across OpenRouter, OpenAI, Anthropic, and Kilo
- **Automatic refresh**: Pricing updates via the `refresh-pricing` CronJob at zero cost (OpenRouter `/models` is public); cadence is `OPENROUTER_REFRESH_SECONDS` (every 5 minutes in the shipped k8s config), and the CronJob schedule must match it
- **Redis caching**: the models cache TTL is `3 × OPENROUTER_REFRESH_SECONDS` so it never expires between refresh runs (2700s with the local default of 900s; 900s in prod, since the refresh interval there is 300s); falls back to in-process memory if Redis is unreachable
- **History tracking**: Postgres persistence of hourly pricing snapshots (pruned after `SNAPSHOT_RETENTION_DAYS`, default 90) enabling trend analysis

### 2. Intelligent Model Ranking

- **Blended cost metric**: `0.30 × input $/Mtok + 0.70 × output $/Mtok` (customizable weights for different workloads)
- **Capability filtering**:
  - Minimum context window: 1M tokens (prevents undersized models)
  - Tool calling support required
  - Cost boundaries: input ≤ $10/Mtok, output ≤ $40/Mtok
  - Excludes free/placeholder models
- **Dynamic top-N ranking**: Real-time computation based on current pricing
- **Customizable thresholds**: All ranking parameters configurable via environment variables

### 3. Channel Comparison

Compare the same model across four distinct purchasing channels:

- **OpenRouter PAYG**: Pay-as-you-go pricing, plus the credit-purchase fee
- **OpenRouter BYOK**: Bring-your-own-key (user API key) pricing, plus the BYOK fee
- **Kilo Pass**: Kilo AI Gateway subscription with tier-based pricing (starter, pro, expert)
- **Kilo BYOK**: Kilo subscription with customer-supplied model credentials (true passthrough, no markup)

### 4. Kilo AI Gateway Integration

- **Tier management**: Static tier definitions (starter, pro, expert) with pricing rules
- **Streak bonuses**: Volume-based discounts calculated from consecutive months at tier
- **Annual prepayment**: Optional annual payment option with discount calculation
- **Live model availability**: Query Kilo's model catalog in real-time
- **Projection calculator**: Compute effective credits and cost breakdowns for given usage patterns

### 5. Account Balance & Spend Tracking

- **OpenRouter integration**: Credit balance (limit/spent/remaining) via `/credits`
- **OpenAI integration**: Last-30-day spend via the Admin Costs API (no balance endpoint; validates the key)
- **Anthropic integration**: Last-30-day spend via the Admin cost report (no balance endpoint; validates the key)
- **Kilo integration**: Key validation and available model count (no spend/balance endpoint)
- **OpenRouter activity**: Per-model usage tracking (last 30 days) with request counts and token volumes
- **OpenAI activity**: Per-model cost breakdown (last 30 days) via the cost report's `group_by=line_item`
- **Caching**: `/accounts/usage` is cached ~2 minutes (30s on upstream error); `/accounts/activity` and `/accounts/openai-activity` are cached ~15 minutes

### 6. Historical Trend Analysis

- **30-day price history**: Store and retrieve historical pricing snapshots
- **Trend visualization**: Display input/output cost trends over time
- **Anomaly detection**: Visual inspection of unusual pricing changes
- **Data persistence**: All historical records in Postgres for regulatory/audit compliance

### 7. Dark/Light Mode

- **System preference detection**: Automatically detect OS dark mode setting
- **User override**: Manual toggle preserved in browser session
- **Design token system**: Tailwind CSS variables ensure consistent rendering across themes

## API Endpoints

### Health & Observability

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `GET /healthz` | GET | `{"status": "ok"}` | Kubernetes liveness probe |
| `GET /readyz` | GET | `{"db": true, "redis": true, "ready": true}` | Kubernetes readiness probe — 503 if Postgres is unreachable; Redis is reported honestly but does not gate readiness (the cache falls back to in-process memory) |
| `GET /metrics` | GET | Prometheus text format | Prometheus metrics (request count, latency by method/route/status) |

### Models

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /models` | GET | `refresh=false` | `[ModelPricing]` | Full model catalog (cached) |
| `GET /models?refresh=true` | GET | `refresh=true` | `[ModelPricing]` | Bypass cache, fetch fresh pricing |
| `GET /models/top` | GET | `n=10` (1–50) | `[RankedModel]` | Top-N models by blended cost |
| `GET /models/{model_id}` | GET | — | `ModelPricing` | Single model details |
| `GET /models/{model_id}/history` | GET | `days=30` (1–365) | `[ModelPricing]` | Historical pricing snapshots |

**Response Schema: ModelPricing**
```json
{
  "id": "anthropic/claude-3.5-sonnet",
  "name": "Claude 3.5 Sonnet",
  "provider": "anthropic",
  "prompt_usd_per_mtok": 3.0,
  "completion_usd_per_mtok": 15.0,
  "request_usd": 0.0,
  "image_usd": 0.0,
  "context_length": 200000,
  "max_completion_tokens": 4096,
  "supports_tools": true,
  "supports_vision": true,
  "captured_at": "2026-05-27T08:30:00Z"
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
| `GET /compare/{model_id}` | GET | `kilo_tier=pro&kilo_streak_months=8&kilo_annual=false` | `ModelComparison` | Compare pricing across 4 channels |

`kilo_tier` must be one of `starter`/`pro`/`expert`; an unknown tier returns **422**. 404 if `model_id` is not found.

**Response Schema: ModelComparison**
```json
{
  "model": { ...ModelPricing... },
  "channels": [
    {
      "channel": "openrouter_payg",
      "prompt_usd_per_mtok": 2.85,
      "completion_usd_per_mtok": 14.25,
      "notes": "+5.5% credit purchase fee"
    },
    {
      "channel": "openrouter_byok",
      "prompt_usd_per_mtok": 2.82,
      "completion_usd_per_mtok": 14.10,
      "notes": "+5.0% past 1M reqs/mo"
    },
    {
      "channel": "kilo_pass",
      "prompt_usd_per_mtok": 2.1,
      "completion_usd_per_mtok": 10.5,
      "notes": "tier=pro, month 8, 30.0% effective discount"
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

### Kilo AI Gateway

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /kilo/plans` | GET | — | `[KiloPlan]` | All Kilo subscription tiers (from `api/app/data/kilo_plans.yaml`) |
| `GET /kilo/models` | GET | — | `[ModelPricing]` | Models available on Kilo |
| `GET /kilo/models/{model_id}` | GET | — | `ModelPricing` | Single Kilo model |
| `GET /kilo/projection` | GET | `tier=pro&streak_months=8&annual=false` | `KiloProjection` | Cost projection and effective rates |

`tier` must be one of `starter`/`pro`/`expert`; an unknown tier returns **422**.

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

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `GET /accounts/usage` | GET | `AccountsUsage` | Status for OpenRouter, Kilo, OpenAI and Anthropic (balance where available, else 30-day spend) |
| `GET /accounts/activity` | GET | `ActivityResponse` | Per-model usage from OpenRouter (last 30 days) |
| `GET /accounts/openai-activity` | GET | `ActivityResponse` | Per-model costs from OpenAI (last 30 days) |

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
    "plan": "Pro $49/mo",
    "limit_usd": 49.0,
    "spent_usd": null,
    "remaining_usd": null,
    "period_start": null,
    "model_count": 42,
    "error": null
  },
  "openai": {
    "provider": "openai",
    "configured": true,
    "plan": null,
    "limit_usd": null,
    "spent_usd": 523.45,
    "remaining_usd": null,
    "period_start": "Aug 27",
    "model_count": null,
    "error": null
  },
  "anthropic": {
    "provider": "anthropic",
    "configured": true,
    "plan": null,
    "limit_usd": null,
    "spent_usd": 234.12,
    "remaining_usd": null,
    "period_start": "Aug 27",
    "model_count": null,
    "error": null
  },
  "fetched_at": "2026-09-26T08:30:00Z"
}
```

**Response Schema: ActivityResponse**
```json
{
  "items": [
    {
      "model_id": "anthropic/claude-3.5-sonnet",
      "requests": 1250,
      "prompt_tokens": 15000000,
      "completion_tokens": 5000000,
      "cost_usd": 450.25
    }
  ],
  "fetched_at": "2026-09-26T08:30:00Z"
}
```

## Frontend Features

### Dashboard Views

1. **Main Dashboard**
   - Top 10 coding models ranked by blended cost
   - Quick glance at last-30-day spend across providers
   - Live pricing for selected model
   - Model comparison side-by-side across channels

2. **Model Detail Modal**
   - Single model metadata (context, max tokens, tool/vision support)
   - Usage summary (last 30 days): spend, requests, token volumes
   - Channel comparison table with effective pricing
   - Bar chart comparing pricing across 4 channels
   - Line chart showing 30-day price trend

3. **About / Information Page**
   - Feature overview with visual cards
   - Technical architecture diagram
   - Demonstrated expertise summary
   - Customization and integration guidance

### Visualizations

- **Recharts integration**: Responsive, theme-aware charts
- **Bar charts**: Compare pricing across channels
- **Line charts**: Visualize price trends over 30 days
- **Tables**: Sortable, filterable model catalogs
- **Color coding**: Input (blue) vs output (green) cost visualization

### Real-Time Updates

- **SWR polling**: Model/pricing/account-usage queries refresh every 5 minutes; account activity every 15 minutes (no polling on window focus)
- **404 handling**: An `/accounts/*` 404 is treated as "not exposed by the web proxy" (`EXPOSE_ACCOUNT_DATA` is off) rather than an error
- **Dark mode**: Synchronized with system preference, user-overridable

## Data Models

### Core Models

**ModelPricing**
- `id`: Unique provider-prefixed ID (e.g., "anthropic/claude-3.5-sonnet")
- `name`: Human-readable name
- `provider`: Provider identifier
- `prompt_usd_per_mtok`: Input price per 1M tokens
- `completion_usd_per_mtok`: Output price per 1M tokens
- `request_usd` / `image_usd`: Per-request / per-image surcharge, if any
- `context_length`: Maximum input context in tokens
- `max_completion_tokens`: Maximum output tokens
- `supports_tools`: Boolean (function calling)
- `supports_vision`: Boolean (image input)
- `captured_at`: ISO timestamp of pricing capture

**RankedModel**
- `model`: ModelPricing object
- `score`: 0–100, higher is better (`100 - blended_usd_per_mtok`, floored at 0)
- `blended_usd_per_mtok`: Weighted cost metric
- `rank`: Integer ranking (1 = lowest blended cost)

**ModelComparison**
- `model`: ModelPricing object
- `channels`: Array of 4 ChannelPrice objects

**ChannelPrice**
- `channel`: One of `openrouter_payg`, `openrouter_byok`, `kilo_pass`, `kilo_byok`
- `prompt_usd_per_mtok`: Effective input rate
- `completion_usd_per_mtok`: Effective output rate
- `notes`: Explanation (streak bonus, tier info, etc.)

## Scheduled Jobs (CronJobs)

### refresh-pricing
- **Schedule**: Every 5 minutes (`*/5 * * * *`), matching `OPENROUTER_REFRESH_SECONDS=300` in the shipped config
- **Action**: Fetch `/models` from OpenRouter, normalize pricing, persist to Postgres, update Redis cache, prune snapshots older than `SNAPSHOT_RETENTION_DAYS`
- **Cost**: Free (OpenRouter endpoint is public)
- **Failure handling**: Retries the OpenRouter fetch up to 3 times with exponential backoff; a run that still fails logs the error and exits non-zero

### daily-report
- **Schedule**: Daily at 8:00 AM America/Denver (`spec.timeZone`)
- **Action**: Compute savings projections, send email summary to stakeholders
- **Customization**: Baseline model ID and monthly token assumptions are constants in `daily_report.py` (not env vars)

### kilo-diff
- **Schedule**: Weekly, Mondays at 07:00 America/Denver
- **Action**: Hash the live kilo.ai/pricing page and compare against the last hash stored in Postgres (`kilo_plan_snapshot` table, not Redis); alert by email on changes
- **Purpose**: Early detection of pricing or tier definition changes

## Environment Configuration

### Required

- `DATABASE_URL`: PostgreSQL connection using the `postgresql+psycopg` (psycopg 3) driver
- `REDIS_URL`: Redis endpoint with optional password (optional in practice — the cache falls back to in-process memory if Redis is unreachable)

### Optional (for features)

- `OPENAI_ADMIN_KEY` / `OPENAI_API_KEY`: OpenAI key for spend tracking / key validation
- `ANTHROPIC_ADMIN_KEY` / `ANTHROPIC_API_KEY`: Anthropic key for spend tracking / key validation
- `OPENROUTER_API_KEY`: OpenRouter key (for `/credits` and `/activity`)
- `KILO_API_KEY`: Kilo API credentials
- `KILO_TIER`: Active Kilo tier — `starter` / `pro` / `expert` (default `starter`)
- `SMTP_*`: Email configuration for daily reports

### Tuning

- `RANK_INPUT_WEIGHT` / `RANK_OUTPUT_WEIGHT`: Weights for the blended cost metric (default 0.30 / 0.70)
- `RANK_MIN_CONTEXT_TOKENS`: Minimum context window filter (default 1,000,000)
- `RANK_MAX_INPUT_PRICE` / `RANK_MAX_OUTPUT_PRICE`: Cost bounds in USD/Mtok (default 10.0 / 40.0)
- `RANK_TOP_N`: Default size of `/models/top` (default 10)
- `OPENROUTER_REFRESH_SECONDS`: Expected interval between `refresh-pricing` runs (default 900; the models cache TTL is 3x this)
- `SNAPSHOT_RETENTION_DAYS`: Hourly snapshot retention before pruning (default 90; 0 disables pruning)
- `CACHE_TTL_SECONDS`: Default Redis cache duration outside the models cache (default 900)

## Security & Compliance

- **No secrets in code**: All credentials injected via environment or Kubernetes secrets
- **HTTPS/TLS**: Traefik ingress terminates TLS from a secret you provide — no cert-manager wiring is included in this repo
- **CORS**: Restricted to the origins in `CORS_ORIGINS`
- **Admin key separation**: `OPENAI_ADMIN_KEY`/`ANTHROPIC_ADMIN_KEY` (cost reporting) are distinct from `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (key validation only)
- **Account data gating**: the web proxy (`route.ts`) forwards `/accounts/*` only when `EXPOSE_ACCOUNT_DATA=true`; `/metrics`, `/docs`, and `?refresh=` are never forwarded regardless
- **Request logging**: Structured JSON logs (structlog) plus Prometheus request/latency metrics; no per-user identity is captured
- **Data retention**: Configurable historical snapshot retention (default 90 days via `SNAPSHOT_RETENTION_DAYS`)

## Performance Characteristics

- **Response times**: 
  - Cached endpoints: <100ms
  - History queries: <500ms (Postgres index on model_id, date)
  - Comparison computation: <250ms (in-memory calculation)
- **Memory**: ~300MB per API pod, ~200MB per web pod
- **Scaling**: Ships with 1 replica per service; horizontal scaling adds replicas with no session affinity required
- **Cold start**: Fresh Docker container boots in ~2 seconds

## Extensibility

### Adding a New Provider

1. Create `app/services/new_provider.py` following the OpenRouter pattern
2. Implement `list_models()`, `get_model()`, `get_history()` coroutines
3. Register in `app/services/__init__.py`
4. Update `api/app/main.py` to include new provider routes
5. Add environment variables for credentials
6. Update SBOM.md with any new dependencies

### Customizing Ranking

Set via environment (or edit the defaults in `app/config.py`):
```python
RANK_INPUT_WEIGHT = 0.30          # Adjust for your workload
RANK_OUTPUT_WEIGHT = 0.70         # (must sum to 1.0)
RANK_MIN_CONTEXT_TOKENS = 1_000_000
RANK_MAX_INPUT_PRICE = 10.0
RANK_MAX_OUTPUT_PRICE = 40.0
RANK_TOP_N = 10
```

Tool-calling support is always required for the coding ranking (not
configurable). Then restart the service; ranking recomputes on next
`/models/top` request.

### Custom Reports

Edit the constants in `app/jobs/daily_report.py` (these are not env vars):
```python
BASELINE_MODEL_ID = "anthropic/claude-sonnet-4.6"
BASELINE_INPUT_MTOK = 5   # millions of input tokens/month
BASELINE_OUTPUT_MTOK = 5  # millions of output tokens/month
```

Add custom calculations (ROI, volume discounts, team allocations) in the report builder.
