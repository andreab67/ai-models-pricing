# Functional Specification: AI Model Pricing Dashboard

## Overview

The AI Model Pricing Dashboard is a production-grade system for real-time tracking, comparison, and optimization of Large Language Model (LLM) costs across multiple providers. It aggregates pricing data from OpenRouter, OpenAI, Anthropic, and Kilo AI Gateway, normalizing costs to a common metric (USD per 1M tokens) for instant comparison and data-driven model selection.

## Core Features

### 1. Real-Time Pricing Aggregation

- **Multi-provider catalog**: Unified view of 100+ models across OpenRouter, OpenAI, Anthropic, and Kilo
- **Automatic refresh**: Pricing updates every 15 minutes via CronJob at zero cost (OpenRouter `/models` is public)
- **Redis caching**: TTL-based caching (900 seconds) for rapid responses
- **History tracking**: Postgres persistence for 30+ days of historical snapshots enabling trend analysis

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

- **OpenRouter PAYG**: Pay-as-you-go pricing, per-request billing
- **OpenRouter BYOK**: Bring-your-own-key (user API key) pricing
- **Kilo Pass**: Kilo AI Gateway subscription with tier-based pricing (Basic, Pro, Enterprise)
- **Kilo BYOK**: Kilo subscription with customer-supplied model credentials

### 4. Kilo AI Gateway Integration

- **Tier management**: Static tier definitions (Basic, Pro, Enterprise) with pricing rules
- **Streak bonuses**: Volume-based discounts calculated from consecutive months at tier
- **Annual prepayment**: Optional annual payment option with discount calculation
- **Live model availability**: Query Kilo's model catalog in real-time
- **Projection calculator**: Compute effective credits and cost breakdowns for given usage patterns

### 5. Account Balance & Spend Tracking

- **OpenAI integration**: Current billing cycle spend and remaining credit balance
- **Anthropic integration**: Account balance and recent cost activity
- **OpenRouter activity**: Per-model usage tracking (last 30 days) with request counts and token volumes
- **Real-time updates**: Fetch on-demand without caching to ensure accuracy
- **Cost breakdown by model**: Aggregate spending across models for workload analysis

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
| `GET /readyz` | GET | `{"status": "ok"}` | Kubernetes readiness probe (checks DB + Redis connectivity) |
| `GET /metrics` | GET | Prometheus text format | Prometheus metrics (request count, latency, errors) |

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
  "context_length": 200000,
  "max_completion_tokens": 4096,
  "supports_tools": true,
  "supports_vision": true,
  "cached_at": "2026-05-27T08:30:00Z"
}
```

**Response Schema: RankedModel** (extends ModelPricing)
```json
{
  "rank": 1,
  "blended_usd_per_mtok": 12.0,
  "model": { ...ModelPricing... }
}
```

### Comparison

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /compare/{model_id}` | GET | `kilo_tier=pro&kilo_streak_months=8&kilo_annual=false` | `ModelComparison` | Compare pricing across 4 channels |

**Response Schema: ModelComparison**
```json
{
  "model": { ...ModelPricing... },
  "channels": [
    {
      "channel": "openrouter_payg",
      "prompt_usd_per_mtok": 2.7,
      "completion_usd_per_mtok": 13.5,
      "notes": "Effective rate from OpenRouter"
    },
    {
      "channel": "kilo_pass",
      "prompt_usd_per_mtok": 2.1,
      "completion_usd_per_mtok": 10.5,
      "notes": "Pro tier with 8-month streak bonus"
    }
    // ...more channels...
  ]
}
```

### Kilo AI Gateway

| Endpoint | Method | Query Parameters | Response | Purpose |
|----------|--------|------------------|----------|---------|
| `GET /kilo/plans` | GET | — | `[KiloPlan]` | All Kilo subscription tiers |
| `GET /kilo/models` | GET | — | `[ModelPricing]` | Models available on Kilo |
| `GET /kilo/models/{model_id}` | GET | — | `ModelPricing` | Single Kilo model |
| `GET /kilo/projection` | GET | `tier=pro&streak_months=8&annual=false` | `KiloProjection` | Cost projection and effective rates |

**Response Schema: KiloPlan**
```json
{
  "tier": "pro",
  "base_usd_per_mtok_in": 2.0,
  "base_usd_per_mtok_out": 10.0,
  "monthly_credits": 10000000,
  "streak_bonus_percent": 0.15,
  "annual_discount_percent": 0.08,
  "description": "Professional tier for production workloads"
}
```

**Response Schema: KiloProjection**
```json
{
  "tier": "pro",
  "base_monthly_cost": 100,
  "streak_months": 8,
  "streak_bonus_percent": 15,
  "applied_bonus_usd": 15,
  "annual_discount_percent": 8,
  "monthly_effective_cost": 78.2,
  "effective_rate_in": 1.7,
  "effective_rate_out": 8.5
}
```

### Account Activity

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `GET /accounts/usage` | GET | `AccountsUsage` | Current-month spend + remaining credits (OpenAI, Anthropic) |
| `GET /accounts/activity` | GET | `ActivityResponse` | Per-model usage from OpenRouter (last 30 days) |
| `GET /accounts/openai-activity` | GET | `ActivityResponse` | Per-model costs from OpenAI (last 30 days) |

**Response Schema: AccountsUsage**
```json
{
  "accounts": [
    {
      "provider": "openai",
      "spent_usd": 523.45,
      "remaining_credit_usd": 1476.55,
      "subscription_active": true,
      "usage_limit_usd": 2000
    },
    {
      "provider": "anthropic",
      "spent_usd": 234.12,
      "remaining_credit_usd": 765.88,
      "subscription_active": true,
      "usage_limit_usd": 1000
    }
  ]
}
```

**Response Schema: ActivityResponse**
```json
{
  "provider": "openrouter",
  "period_days": 30,
  "total_spend_usd": 1250.50,
  "items": [
    {
      "model_id": "anthropic/claude-3.5-sonnet",
      "cost_usd": 450.25,
      "requests": 1250,
      "prompt_tokens": 15000000,
      "completion_tokens": 5000000
    }
    // ...more models...
  ]
}
```

## Frontend Features

### Dashboard Views

1. **Main Dashboard**
   - Top 10 coding models ranked by blended cost
   - Quick glance at current month spend across providers
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

- **SWR polling**: Frontend fetches `/models/top` every 60 seconds
- **Activity refresh**: User can manually trigger account balance checks
- **Responsive cache handling**: 404s and stale data gracefully handled
- **Dark mode**: Synchronized with system preference, user-overridable

## Data Models

### Core Models

**ModelPricing**
- `id`: Unique provider-prefixed ID (e.g., "anthropic/claude-3.5-sonnet")
- `name`: Human-readable name
- `provider`: Provider identifier
- `prompt_usd_per_mtok`: Input price per 1M tokens
- `completion_usd_per_mtok`: Output price per 1M tokens
- `context_length`: Maximum input context in tokens
- `max_completion_tokens`: Maximum output tokens
- `supports_tools`: Boolean (function calling)
- `supports_vision`: Boolean (image input)
- `cached_at`: ISO timestamp of pricing capture

**RankedModel**
- Extends ModelPricing with:
- `rank`: Integer ranking (1 = lowest blended cost)
- `blended_usd_per_mtok`: Weighted cost metric

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
- **Schedule**: Every 15 minutes
- **Action**: Fetch `/models` from OpenRouter, normalize pricing, persist to Postgres, update Redis cache
- **Cost**: Free (OpenRouter endpoint is public)
- **Failure handling**: Retry with exponential backoff; log and alert on persistent failures

### daily-report
- **Schedule**: Daily (default 9 AM UTC)
- **Action**: Compute savings projections, send email summary to stakeholders
- **Customization**: Baseline model and usage figures configurable

### kilo-diff
- **Schedule**: Daily
- **Action**: Compare previous Kilo pricing snapshot with current; alert on changes
- **Purpose**: Early detection of pricing or tier definition changes

## Environment Configuration

### Required

- `DATABASE_URL`: PostgreSQL connection (async driver)
- `REDIS_URL`: Redis endpoint with optional password

### Optional (for features)

- `OPENAI_ADMIN_KEY`: OpenAI API key for balance/spend tracking
- `ANTHROPIC_ADMIN_KEY`: Anthropic API key for balance tracking
- `OPENROUTER_API_KEY`: OpenRouter key (for authenticated endpoints)
- `KILO_API_KEY`: Kilo API credentials
- `SMTP_*`: Email configuration for daily reports

### Tuning

- `RANK_INPUT_WEIGHT`: Weight for input cost in blended metric (default 0.30)
- `RANK_OUTPUT_WEIGHT`: Weight for output cost in blended metric (default 0.70)
- `RANK_MIN_CONTEXT_TOKENS`: Minimum context window filter (default 1,000,000)
- `CACHE_TTL_SECONDS`: Redis cache duration (default 900)

## Security & Compliance

- **No secrets in code**: All credentials injected via environment or Kubernetes secrets
- **HTTPS/TLS**: Ingress configured with cert-manager for automatic renewal
- **CORS**: Configured to allow same-origin frontend requests
- **Admin key separation**: Admin-level endpoints (if present) validated against separate credentials
- **Audit trail**: All API requests logged with timestamps and response codes
- **Data retention**: Configurable historical snapshot retention (default 90 days)

## Performance Characteristics

- **Response times**: 
  - Cached endpoints: <100ms
  - History queries: <500ms (Postgres index on model_id, date)
  - Comparison computation: <250ms (in-memory calculation)
- **Throughput**: 1000+ req/s per API pod (tuned for 2–3 replicas)
- **Memory**: ~300MB per API pod, ~200MB per web pod
- **Scaling**: Horizontal scaling adds replicas; no session affinity required
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

Edit `app/config.py`:
```python
RANK_INPUT_WEIGHT = 0.30          # Adjust for your workload
RANK_OUTPUT_WEIGHT = 0.70         # (must sum to 1.0)
RANK_MIN_CONTEXT_TOKENS = 1_000_000
RANK_MAX_INPUT_COST = 10.0
RANK_MAX_OUTPUT_COST = 40.0
RANK_MIN_TOOL_SUPPORT = True
```

Then restart the service; ranking recomputes on next `/models/top` request.

### Custom Reports

Edit `app/jobs/daily_report.py`:
```python
BASELINE_MODEL = "anthropic/claude-3.5-sonnet"
MONTHLY_INPUT_TOKENS = 5_000_000
MONTHLY_OUTPUT_TOKENS = 5_000_000
```

Add custom calculations (ROI, volume discounts, team allocations) in the report builder.
