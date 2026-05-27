# AI Model Pricing Dashboard

**Real-time cost tracking and optimization across 10+ LLM providers in one unified interface.**

A production-grade dashboard for tracking, comparing, and optimizing Large Language Model (LLM) costs across OpenRouter, OpenAI, Anthropic, and Kilo AI Gateway. Built with enterprise-ready infrastructure, this system provides teams with the cost visibility and data-driven insights needed to maximize ROI on AI workloads.

![Dashboard](docs/dashboard.jpg)

## Why This Matters

Organizations running multi-provider AI workloads lack a unified view of costs and capabilities. This creates friction:

- **Spreadsheet sprawl**: Manual price tracking becomes outdated within hours as providers update rates
- **Hidden costs**: Tiering structures, volume discounts, and subscription bonuses are easy to miss
- **Suboptimal selection**: Without real-time pricing, teams default to familiar models instead of cost-optimal ones
- **Fragmented visibility**: Tracking spend across provider dashboards is time-consuming and error-prone

This dashboard solves all of these problems by:
- **Aggregating 100+ models** from competing providers into a single searchable catalog
- **Auto-updating every 15 minutes** at zero cost (pricing is public data)
- **Normalizing costs** to USD per 1M tokens for apples-to-apples comparison
- **Ranking models intelligently** based on cost, context window, and capabilities
- **Tracking spend** in real-time across OpenAI, Anthropic, and OpenRouter accounts
- **Visualizing trends** over 30 days to detect pricing changes and opportunities

## What's Included

| Component | Path | Purpose |
| --- | --- | --- |
| **FastAPI Backend** | `api/` | Pricing aggregation, normalization, caching, historical tracking |
| **Next.js Dashboard** | `web/` | Modern responsive UI with real-time charts and dark mode |
| **Kubernetes Manifests** | `k8s/` | Production-ready deployment (Traefik, cert-manager, CronJobs) |
| **Local Dev Stack** | `docker-compose.yml` | Self-contained environment (Postgres + Redis + API + Web) |
| **Feature Docs** | `FUNCTIONAL.md` | Complete API reference and data models |
| **Component Inventory** | `SBOM.md` | All dependencies with licenses and security notes |

## Key Features

- **Multi-Provider Aggregation**
  - Unified pricing for OpenRouter, OpenAI, Anthropic, Kilo
  - Real-time balance & spend tracking for each account
  - Per-model usage statistics (last 30 days)

- **Intelligent Ranking**
  - Blended cost metric: 30% input + 70% output (tunable)
  - Automatic filters: tool support, 1M+ context, cost bounds
  - Top-N models computed in real-time

- **Channel Comparison**
  - Compare pricing across OpenRouter PAYG/BYOK, Kilo Pass/BYOK
  - Kilo tier projections with streak bonuses and annual discounts
  - Side-by-side pricing table with effective rates

- **Historical Trend Analysis**
  - 30-day price history with trend visualization
  - Postgres-backed persistence for audit compliance
  - Anomaly detection at a glance

- **Account Integration**
  - OpenAI: current-month spend + remaining credit balance
  - Anthropic: account balance and recent activity
  - OpenRouter: per-model usage, request counts, token volumes

- **Production Infrastructure**
  - Kubernetes-ready with health checks and metrics
  - Horizontal scaling (2–3 replicas per service)
  - Automated pricing refresh every 15 minutes
  - Configurable daily report emails

## Dashboard Screenshots

### Pricing Trends Visualization

![Pricing Trends](docs/pricing-trends.jpg)

30-day price history for any model, visualized as line chart with input (blue) and output (green) trends. Easily spot pricing changes and market opportunities.

## Quick Start (Local)

```bash
# 1. Clone and configure
git clone https://github.com/yourusername/ai-models-pricing.git
cd ai-models-pricing
cp api/.env.example api/.env

# 2. Start the full stack (Postgres + Redis + API + Web)
docker compose up --build

# 3. Populate initial data (otherwise table is empty until first refresh)
docker compose exec api python -m app.jobs.refresh_pricing

# 4. Open the dashboard
# Dashboard:  http://localhost:3000
# API docs:   http://localhost:8000/docs
```

### Backend-Only Setup

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://pricing:pricing@localhost:5432/pricing
export REDIS_URL=redis://localhost:6379/0
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend-Only Setup

```bash
cd web
npm install
API_BASE_URL=http://localhost:8000 npm run dev
```

## API Overview

### Models

- `GET /models` — full catalog
- `GET /models/top?n=10` — top-N ranking
- `GET /models/{id}` — single model
- `GET /models/{id}/history?days=30` — price history

### Comparison

- `GET /compare/{model_id}` — pricing across 4 channels
- `GET /kilo/plans` — Kilo tier definitions
- `GET /kilo/projection?tier=pro` — effective cost calculation

### Account Activity

- `GET /accounts/usage` — spend + balance (OpenAI, Anthropic)
- `GET /accounts/activity` — OpenRouter activity (last 30 days)
- `GET /accounts/openai-activity` — OpenAI costs by model

See `FUNCTIONAL.md` for complete endpoint documentation and response schemas.

## Production Deployment (Kubernetes)

### Prerequisites

- Postgres and Redis (external cluster services)
- Container registry (DockerHub, ECR, GCR, etc.)
- Kubernetes secret `model-pricing-secrets` with:
  - `DATABASE_URL` — PostgreSQL connection string
  - `REDIS_URL` — Redis endpoint
  - API keys (optional): `OPENAI_ADMIN_KEY`, `ANTHROPIC_ADMIN_KEY`, `KILO_API_KEY`

### Deploy

```bash
# 1. Build and push images
docker build -t <registry>/api:latest api/
docker build -t <registry>/web:latest web/
docker push <registry>/api:latest
docker push <registry>/web:latest

# 2. Update image references in k8s/base/deployment.yaml

# 3. Deploy
kubectl create namespace model-pricing
kubectl apply -k k8s/overlays/prod

# 4. Verify
kubectl -n model-pricing get pods,svc,ingress
kubectl -n model-pricing logs deploy/api -f
```

**Configure TLS:**
```bash
# Update domain in k8s/certificate.yaml, then apply
kubectl apply -f k8s/certificate.yaml
```

## Architecture

```
Ingress (TLS) → Load Balancer
    ├─ /         → Next.js (web, replicas=2–3)
    └─ /api/*    → FastAPI (api, replicas=2–3)
          ├─ Postgres (history, model catalog)
          ├─ Redis (900s TTL cache)
          └─ External APIs
              ├─ OpenRouter /models (free, public)
              ├─ OpenAI admin API (optional, billing only)
              ├─ Anthropic admin API (optional, billing only)
              └─ Kilo API (optional, if using Kilo)

Scheduled Tasks (CronJobs in same namespace):
  • refresh-pricing   every 15 minutes
  • daily-report      daily at 9 AM UTC
  • kilo-diff         daily (pricing change alerts)
```

## Configuration

### Ranking Algorithm

Adjust weights in `api/app/config.py`:

```python
RANK_INPUT_WEIGHT = 0.30       # 30% of blended cost
RANK_OUTPUT_WEIGHT = 0.70      # 70% of blended cost
RANK_MIN_CONTEXT_TOKENS = 1_000_000   # Exclude smaller models
RANK_MAX_INPUT_COST = 10.0     # USD per million tokens
RANK_MAX_OUTPUT_COST = 40.0    # USD per million tokens
```

### Email Reports

Customize the daily report in `api/app/jobs/daily_report.py`:

```python
BASELINE_MODEL = "anthropic/claude-3.5-sonnet"
MONTHLY_INPUT_TOKENS = 5_000_000
MONTHLY_OUTPUT_TOKENS = 5_000_000
```

### Kilo Pricing

Kilo tiers are defined in `api/app/data/kilo_plans.yaml`. Update whenever Kilo pricing changes, or create a monitoring CronJob for automated alerts.

## Customization Guide

### Add a New Provider

1. Create `api/app/services/provider_name.py` implementing:
   - `async def list_models() -> list[ModelPricing]`
   - `async def get_model(id: str) -> ModelPricing | None`
   - `async def get_history(id: str, days: int) -> list[ModelPricing]`

2. Register in `api/app/main.py` and wire up routes

3. Add environment variables for credentials

4. Update `SBOM.md` with new dependencies

### Custom Visualizations

The dashboard uses **Recharts** for charting. Add new chart types in `web/src/components/`:

- Line charts (price trends over time)
- Bar charts (channel comparison)
- Pie charts (spend breakdown by provider)
- Heatmaps (cost matrix across models × providers)

### Custom Reports

Extend `api/app/jobs/daily_report.py` with:
- ROI calculations for each model
- Volume discount projections
- Team-level cost allocation
- Unused capacity alerts
- Competitive pricing intel

## Monitoring & Observability

- **Prometheus metrics**: Request count, latency, cache hit rate
- **Structured logging**: JSON format with context (model_id, provider, error_code)
- **Health checks**: `/healthz` (liveness), `/readyz` (readiness with DB check)
- **Grafana**: Optional dashboard for request patterns and cache performance

## Security

- **No secrets in code**: All credentials via environment or Kubernetes secrets
- **TLS everywhere**: cert-manager auto-renews certificates
- **Audit logging**: All API requests logged with timestamp, user, and response
- **CORS**: Configured for same-origin requests only
- **Rate limiting**: Optional throttling via middleware (not enabled by default)
- **Input validation**: Pydantic schemas enforce types and ranges

## Performance

- **Response times**: <100ms (cached) / <500ms (history queries)
- **Throughput**: 1000+ req/s per pod
- **Memory**: ~300MB API, ~200MB web per pod
- **Scaling**: Horizontal scaling with 2–3 replicas
- **Cold start**: ~2 seconds per pod

## Dependencies

- **Backend**: Python 3.14, FastAPI, SQLAlchemy 2.0, Pydantic 2.0, Postgres, Redis
- **Frontend**: Node.js 22, Next.js 15, React 19, TypeScript, Tailwind CSS, Recharts
- **Infrastructure**: Docker, Kubernetes 1.28+, Traefik, cert-manager

See `SBOM.md` for complete dependency inventory and license compliance.

## License

BSD 3-Clause License. See LICENSE file for details.

## Support

For questions about deployment, customization, or integration:

1. Review `FUNCTIONAL.md` for API reference
2. Check `SBOM.md` for dependency compatibility
3. See `docker-compose.yml` for local dev setup
4. Review `k8s/` for production manifest examples

---

**Built for teams running multi-provider AI workloads who need cost visibility, optimization, and data-driven insights.**

Need custom modifications or production deployment guidance? The codebase is designed for extensibility—pricing providers, ranking algorithms, and report formats are all customizable without modifying core infrastructure.
