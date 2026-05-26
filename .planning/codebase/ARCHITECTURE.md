# Architecture

**Analysis Date:** 2026-05-25

## Overview

Model Pricing is a read-heavy web application that tracks and compares LLM pricing across access channels (OpenRouter PAYG/BYOK and Kilo Pass tiers). It fetches live pricing from OpenRouter's API every 15 minutes, persists time-series snapshots to PostgreSQL, and serves a Next.js dashboard and REST API to users at `models.andrea-house.com`. A secondary feature computes effective per-token cost under Kilo Pass subscription tiers and alerts when the Kilo pricing page changes.

## Components

| Component | Responsibility | Technology |
|-----------|----------------|------------|
| API | REST backend — serves pricing, ranking, comparison, Kilo math | FastAPI (Python), asyncpg, Redis |
| Web | Browser dashboard — model table, top-10 ranking, trend charts, Kilo calculator | Next.js 14 App Router, Tailwind, SWR, Recharts |
| PostgreSQL | Append-only time-series of pricing snapshots | Postgres 16, SQLAlchemy async ORM, Alembic |
| Redis | Primary cache for OpenRouter model list (15-min TTL); in-memory fallback if Redis is unavailable | Redis 7 |
| CronJob: refresh-pricing | Runs every 15 min — fetches OpenRouter, normalizes, caches, persists | `app.jobs.refresh_pricing` |
| CronJob: daily-report | Runs daily — ranks top-5 models, computes projected savings vs. Claude Sonnet 4.6, emails HTML report | `app.jobs.daily_report` |
| CronJob: kilo-diff | Runs weekly — SHA-256 hashes kilo.ai/pricing page; emails alert if changed | `app.jobs.kilo_diff` |
| VSCode extension | Status bar widget — polls `/models/top?n=1` and `/kilo/projection`, displays blended rate | TypeScript VS Code extension |

## Data Flow

### Live request path (cache-warm)

```
Browser → Next.js /api/* rewrite → FastAPI
  GET /models              → cache.get("openrouter:models:normalized")  → list[ModelPricing]
  GET /models/top          → list_models() → ranker.top_n()             → list[RankedModel]
  GET /compare/{model_id}  → get_model() + pricing_calculator.compare() → ModelComparison
  GET /kilo/plans          → kilo.load_plans() (kilo_plans.yaml)        → list[KiloPlan]
  GET /kilo/projection     → kilo.project()                             → KiloProjection
```

### Pricing refresh path (cache-miss or CronJob)

```
OpenRouter API (https://openrouter.ai/api/v1/models)
  → openrouter.fetch_raw()          # httpx with tenacity retry (3 attempts)
  → openrouter._normalize()         # per-token → USD/Mtok, extract capabilities
  → cache.set("openrouter:models:normalized", ttl=900s)
  → openrouter._persist()           # pg_insert ON CONFLICT DO NOTHING
    → model_pricing_snapshot table  # append-only; unique on (model_id, captured_at)
```

### History / trend path

```
Browser GET /models/{model_id}/history?days=N
  → openrouter.get_history()
  → SELECT * FROM model_pricing_snapshot WHERE model_id=? AND captured_at >= now()-Nd
  → list[ModelPricing]  (mapped from ORM rows)
```

### Daily report path

```
CronJob (daily) → jobs/daily_report.py
  → openrouter.list_models(use_cache=False)   # fresh fetch
  → ranker.top_n(models, n=5)
  → kilo.effective_discount("pro", 8)         # cheapest after Kilo discount
  → Jinja2 render(templates/daily_report.html)
  → mailer.send()                             # SMTP via smtp.andrea-house.com
```

### Kilo diff path

```
CronJob (weekly) → jobs/kilo_diff.py
  → kilo.fetch_pricing_hash()   # httpx GET kilo.ai/pricing, BeautifulSoup strip, SHA-256
  → cache.get("kilo:pricing:last_hash")
  → if changed: mailer.send() + cache.set(new_hash, ttl=30d)
```

## Key Design Decisions

**Append-only snapshot table.** `model_pricing_snapshot` uses `ON CONFLICT DO NOTHING` on `(model_id, captured_at)` bucketed to the hour. This gives a free price-history time series without any UPDATE logic; the trade-off is table growth over time (no pruning implemented).

**Redis with in-memory fallback.** `app/services/cache.py` implements a two-tier cache: Redis primary with an in-process dict fallback. This keeps the API alive through transient Redis outages, at the cost of per-replica cache inconsistency when Redis is down.

**Kilo plans as checked-in YAML.** `api/app/data/kilo_plans.yaml` is the source of truth for Kilo Pass tier definitions. The kilo-diff CronJob detects when the live page changes and alerts so the YAML can be updated manually. This avoids fragile scraping of tier math but requires a redeploy to update rates.

**Next.js as API proxy.** All `/api/*` routes are rewritten by Next.js (`next.config.mjs`) to the backend service. The browser never calls the FastAPI host directly; CORS is only needed for the local dev origin.

**Four channel comparison.** `pricing_calculator.py` computes four channels for any model: `openrouter_payg` (+5.5% markup), `openrouter_byok` (+5.0%), `kilo_pass` (effective discount from streak/tier math), `kilo_byok` (true passthrough). The discount formula is: `1 - paid / (paid + bonus_credits)`.

**Ranking is cost-weighted, not raw cheapest.** `ranker.py` uses a 30/70 input/output blend (coding is output-heavy), filters by tool support, context ≥ 64K, and price caps. Score is `max(0, 100 - blended_cost)` so higher is better.

## Deployment Model

Production is Kubernetes on a self-hosted cluster (`home` context). Namespace: `model-pricing`. Ingress is Traefik at `models.andrea-house.com` with cert-manager Let's Encrypt TLS.

```
Traefik Ingress (models.andrea-house.com)
  /api  → api Service → api Deployment (2 replicas, RollingUpdate, PDB minAvailable:1)
  /     → web Service → web Deployment

api Deployment
  initContainer: alembic upgrade head  (runs migrations before pod starts)
  containers:    uvicorn (port 8000)
  envFrom:       model-pricing-config (ConfigMap) + model-pricing-secrets (Secret)
  annotations:   prometheus.io/scrape=true → /metrics (Prometheus client, multiprocess)

PostgreSQL  → StatefulSet, PVC
Redis       → Deployment

CronJobs:
  refresh-pricing   */15 * * * *    python -m app.jobs.refresh_pricing
  daily-report      (schedule TBD)  python -m app.jobs.daily_report
  kilo-diff         (schedule TBD)  python -m app.jobs.kilo_diff

Images: harbor.andrea-house.com/model-pricing/{api,web}:0.1.0
```

Local dev uses `docker compose up --build` (`docker-compose.yml`): postgres → redis → migrate → api → web.

## Error Handling

**API:** FastAPI exception handlers. Services log structured JSON via structlog. HTTP errors surface as JSON `{"detail": "..."}`.

**Caching:** Redis failures are caught and logged as warnings; the in-memory fallback activates automatically. Redis client is reset on failure so the next request retries the connection.

**OpenRouter fetch:** `tenacity` retries up to 3 times with exponential backoff on `httpx.HTTPError`. Reraises after exhaustion.

**Jobs:** All job entrypoints wrap the async main in a try/except, log the error with `exc_info=True`, and exit with code 1 so Kubernetes marks the Job as failed and respects `backoffLimit`.

## Metrics & Observability

- `http_requests_total` (Counter, labels: method/path/status) — `MetricsMiddleware` in `main.py`
- `http_request_duration_seconds` (Histogram, labels: method/path)
- Exposed at `GET /metrics` in Prometheus multiprocess format
- `ServiceMonitor` in `k8s/base/servicemonitor.yaml` wires Prometheus scraping

---

*Architecture analysis: 2026-05-25*
