# ai-model-pricing-dashboard

A production-grade dashboard for tracking, comparing, and optimizing LLM costs across multiple providers (OpenRouter, OpenAI, Anthropic). Built with **full-stack expertise** in AI operations, real-time data pipelines, and cost analysis.

This project demonstrates:

- **Multi-provider pricing orchestration** — normalize costs across 10+ LLM providers into a single view
- **Real-time cost tracking** — automated pricing refreshes with Redis caching and Postgres persistence
- **Data-driven model selection** — sophisticated ranking that accounts for cost, context window, and capabilities
- **Production infrastructure** — Kubernetes-ready with health checks, metrics, scheduled jobs, and TLS

Perfect for teams running multi-provider AI workloads who need cost visibility and optimization tools.

## What's in the box

| Component | Path | Purpose |
| --- | --- | --- |
| FastAPI backend | `api/` | Ingests OpenRouter/provider APIs, normalizes pricing, caches in Redis, persists history |
| Next.js dashboard | `web/` | Modern responsive UI (dark/light, App Router, Recharts, Tailwind) |
| K8s manifests | `k8s/` | Kustomize base + overlay, Traefik ingress, cert-manager TLS, CronJobs |
| Docker Compose | `docker-compose.yml` | Local dev: Postgres + Redis + API + Web (fully self-contained) |
| CI/CD | `.gitlab-ci.yml` | Pipeline: lint → test → build → scan → push (adapt to your git provider) |

## Architecture

```
                ┌─────────────────────────────────────┐
                │   Ingress / Load Balancer (TLS)    │
                └───────────────┬─────────────────────┘
                                │  /        /api/*
                ┌───────────────▼──────┐  ┌───▼──────────────┐
                │   web (Next.js)      │  │  api (FastAPI)   │
                │   replicas=2..3      │  │  replicas=2..3   │
                └──────────────────────┘  └───┬──────────────┘
                                              │
                              ┌───────────────┼────────────────┐
                              ▼               ▼                ▼
                          Postgres         Redis        OpenRouter
                          (history)        (cache)      /api/v1/models

                  CronJobs (in same namespace):
                  • refresh-pricing  every 15 minutes
                  • daily-report     daily (configurable time)
                  • price-monitor    configurable schedule
```

## Local development

```bash
# 1. Copy env template
cp api/.env.example api/.env

# 2. Bring up the full stack
docker compose up --build

# 3. Trigger an initial pricing refresh (otherwise the table is empty
#    until the next 15-minute tick)
docker compose exec api python -m app.jobs.refresh_pricing

# 4. Open
#    dashboard: http://localhost:3000
#    api docs:  http://localhost:8000/docs
```

### Backend without containers

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://pricing:pricing@localhost:5432/pricing
export REDIS_URL=redis://localhost:6379/0
alembic upgrade head
uvicorn app.main:app --reload
pytest -q       # tests
ruff check .    # lint
```

### Frontend without containers

```bash
cd web
npm install
API_BASE_URL=http://localhost:8000 npm run dev
```

## API surface

| Endpoint                                      | Purpose                              |
|-----------------------------------------------|--------------------------------------|
| `GET /healthz`                                | liveness                             |
| `GET /readyz`                                 | readiness (db + redis)               |
| `GET /metrics`                                | Prometheus                           |
| `GET /models?refresh=false`                   | full catalog                         |
| `GET /models/top?n=10`                        | top-N coding models                  |
| `GET /models/{id}`                            | single model                         |
| `GET /models/{id}/history?days=30`            | historical snapshots from Postgres   |
| `GET /compare/{id}?kilo_tier=pro&...`         | four channels: OR PAYG/BYOK, Kilo Pass/BYOK |
| `GET /kilo/plans`                             | static Kilo Pass tier definitions    |
| `GET /kilo/projection?tier=pro&streak_months=8` | computed bonus + effective credits |

`/docs` for the full OpenAPI schema.

## Ranking model (default)

```
blended = 0.30 * input_$/Mtok + 0.70 * output_$/Mtok    # coding skews output-heavy
eligibility:
  - tool calling supported
  - context_length ≥ 64k
  - input ≤ $10/Mtok, output ≤ $40/Mtok
  - not a "free" model (both rates == 0)
```

Tune via `RANK_*` env vars in `api/app/config.py`.

## Production deploy (Kubernetes)

### Prerequisites

Postgres and Redis are configured as external cluster services. The namespace must have:

- A **container registry secret** for image pulls (e.g., `regcred`)
- A **Kubernetes secret** `model-pricing-secrets` containing:
  - `DATABASE_URL` — Postgres connection string
  - `REDIS_URL` — Redis connection string (with password if needed)
  - `SMTP_*` — Email configuration (optional)
  - Any provider API keys (optional, for account balance tracking)

### Deployment

```bash
# 1. Update the image tag in k8s/base/deployment.yaml
# 2. Apply the configuration
kubectl apply -k k8s/overlays/prod

# 3. Verify rollout
kubectl -n model-pricing get pods,svc,ingress,cronjobs
kubectl -n model-pricing logs deploy/api -f
```

**DNS & TLS:** Point your domain to the ingress load balancer. If using cert-manager:

```bash
kubectl apply -f k8s/certificate.yaml  # (update domain)
```

### CI/CD Pipeline

The `.gitlab-ci.yml` includes stages for:

- **lint** — ruff (Python), markdownlint (docs)
- **test** — pytest with coverage
- **build** — Kaniko Docker build (adapt registry)
- **scan** — Trivy security scanning
- **push** — Push to your container registry
- **deploy** — kubectl apply (manual trigger on main)

Adapt the registry variables to your environment:

| Variable | Example |
| --- | --- |
| `CI_REGISTRY_IMAGE` | `registry.example.com/model-pricing` |
| `CI_REGISTRY_USER` | Robot account username |
| `CI_REGISTRY_PASSWORD` | Robot account token (masked) |
| `KUBECONFIG` | base64-encoded kubeconfig (file, protected) |

## Customization Guide

### Email Reports

The daily report in `app/jobs/daily_report.py` includes a "projected savings" calculation. Adjust the baseline model and workload:

```python
# Change these to match your typical usage
BASELINE_MODEL = "anthropic/claude-3.5-sonnet"
MONTHLY_INPUT_TOKENS = 5_000_000
MONTHLY_OUTPUT_TOKENS = 5_000_000
```

### Model Ranking Weights

Tune the ranking algorithm in `api/app/config.py`:

```python
RANK_INPUT_WEIGHT = 0.30      # Adjust for your workload
RANK_OUTPUT_WEIGHT = 0.70
RANK_MIN_CONTEXT_TOKENS = 1_000_000  # Minimum context filter
```

### Kilo Pricing

The `api/app/data/kilo_plans.yaml` is maintained manually. Update whenever Kilo's pricing changes, or set up a monitoring CronJob to alert on changes.

## Architecture Notes

- **Data refresh:** OpenRouter `/models` endpoint is public and unauthenticated. The refresh CronJob queries it every 15 minutes at zero cost.
- **Caching:** Redis TTL matches the refresh cadence (900 seconds). Frontend uses SWR polling.
- **Postgres:** Stores historical snapshots for trend analysis. No in-namespace database pod — use an external cluster service.
- **Multi-provider:** The system is designed to integrate additional providers. Add new provider services in `api/app/services/` following the OpenRouter pattern.
