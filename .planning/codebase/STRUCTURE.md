# Directory Structure

**Analysis Date:** 2026-05-25

## Root Layout

```
model-pricing/
├── api/                    # Python FastAPI backend + CronJob entrypoints
├── web/                    # Next.js 14 frontend
├── k8s/                    # Kubernetes manifests (Kustomize)
├── vscode/                 # VS Code extension + workspace config
├── docker-compose.yml      # Local dev stack (postgres + redis + api + web)
├── .gitlab-ci.yml          # CI/CD pipeline
├── .gitignore
└── README.md
```

## api/ — Backend Service

```
api/
├── Dockerfile              # Multi-stage Python build; runs uvicorn on port 8000
├── .dockerignore
├── .env.example            # Documents all required env vars
├── pyproject.toml          # Dependencies: FastAPI, SQLAlchemy, httpx, pydantic-settings, etc.
├── alembic.ini             # Alembic migration config; DATABASE_URL from env
├── alembic/
│   ├── env.py              # Async migration runner using asyncpg
│   ├── script.py.mako
│   └── versions/
│       └── 20260525_0001_initial.py   # Creates model_pricing_snapshot + kilo_plan_snapshot
└── app/
    ├── __init__.py          # __version__ = "0.1.0"
    ├── main.py              # FastAPI app factory; registers routers, CORS, metrics middleware
    ├── config.py            # Pydantic Settings (env vars + .env file); singleton via lru_cache
    ├── db.py                # SQLAlchemy async engine + session_scope() context manager
    ├── models.py            # ORM models: ModelPricingSnapshot, KiloPlanSnapshot
    ├── schemas.py           # Pydantic response schemas: ModelPricing, RankedModel, ModelComparison, KiloPlan, KiloProjection
    ├── logging.py           # structlog configuration; get_logger() wrapper
    ├── data/
    │   └── kilo_plans.yaml  # Static Kilo Pass tier definitions (monthly_usd, paid_credits_usd, bonus growth schedule)
    ├── routes/
    │   ├── __init__.py
    │   ├── health.py        # GET /healthz, GET /readyz
    │   ├── models_api.py    # GET /models, GET /models/top, GET /models/{id}, GET /models/{id}/history
    │   └── compare.py       # GET /compare/{id}, GET /kilo/plans, GET /kilo/projection
    ├── services/
    │   ├── __init__.py
    │   ├── cache.py         # Cache class — Redis primary + in-memory fallback
    │   ├── openrouter.py    # fetch_raw(), _normalize(), refresh_pricing(), list_models(), get_model(), get_history()
    │   ├── kilo.py          # load_plans(), project(), effective_discount(), fetch_pricing_hash()
    │   ├── pricing_calculator.py   # channels_for(), compare() — computes 4-channel WrapperCost
    │   ├── ranker.py        # top_n() — weighted cost ranking with eligibility filter
    │   └── mailer.py        # send() — async SMTP via aiosmtplib
    ├── jobs/
    │   ├── __init__.py
    │   ├── refresh_pricing.py   # CronJob entrypoint: calls refresh_pricing(persist=True)
    │   ├── daily_report.py      # CronJob entrypoint: top-5 email report with projected savings
    │   └── kilo_diff.py         # CronJob entrypoint: kilo.ai/pricing hash diff alert
    └── templates/
        └── daily_report.html    # Jinja2 HTML email template for daily report
```

## web/ — Frontend

```
web/
├── Dockerfile              # Next.js standalone output; serves on port 3000
├── .dockerignore
├── next.config.mjs         # Rewrites /api/* → API_BASE_URL/*; output: standalone
├── package.json            # Next.js 14, React 18, Tailwind, SWR, Recharts
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
├── next-env.d.ts
├── public/                 # Static assets (.gitkeep only — no assets yet)
└── src/
    ├── app/                # Next.js App Router
    │   ├── layout.tsx      # Root layout: ThemeToggle, nav (Dashboard / Trends), global styles
    │   ├── globals.css     # CSS custom properties for design tokens (--fg, --bg, --card, --border, --muted)
    │   ├── page.tsx        # Dashboard: KiloPassCalculator + TopTenRanking + ModelTable + ModelDetailModal
    │   ├── about/
    │   │   └── page.tsx    # Static about page
    │   └── trends/
    │       └── page.tsx    # Pricing trend chart (Recharts LineChart) — picks from top-10 models
    ├── components/
    │   ├── KiloPassCalculator.tsx   # Tier/streak/annual selector; shows KiloProjection from API
    │   ├── ModelDetailModal.tsx     # Modal overlay — shows ModelComparison (4-channel breakdown)
    │   ├── ModelTable.tsx           # Full model catalog table with sort/filter
    │   ├── TopTenRanking.tsx        # Ranked top-10 list sidebar
    │   └── ThemeToggle.tsx          # Light/dark theme switch
    └── lib/
        └── api.ts          # SWR hooks: useModels, useTopModels, useComparison, useKiloPlans, useKiloProjection, useHistory; fmtUsd helper
```

## k8s/ — Kubernetes Manifests

```
k8s/
├── base/                   # Kustomize base — all resources
│   ├── kustomization.yaml  # Lists all resources; image tags: harbor.andrea-house.com/model-pricing/{api,web}:0.1.0
│   ├── namespace.yaml      # namespace: model-pricing
│   ├── configmap.yaml      # Non-secret env vars: ENVIRONMENT, LOG_LEVEL, CORS_ORIGINS, REDIS_URL, SMTP_*
│   ├── secret.example.yaml # Template for model-pricing-secrets (DATABASE_URL, SMTP_PASSWORD, etc.)
│   ├── api-deployment.yaml # 2 replicas; initContainer runs alembic migrate; PDB minAvailable:1
│   ├── api-service.yaml    # ClusterIP on port 8000
│   ├── web-deployment.yaml # Next.js standalone
│   ├── web-service.yaml    # ClusterIP on port 3000
│   ├── ingress.yaml        # Traefik; TLS via cert-manager; /api → api, / → web; host: models.andrea-house.com
│   ├── postgres-statefulset.yaml   # Postgres 16, PVC
│   ├── postgres-service.yaml       # ClusterIP
│   ├── redis-deployment.yaml       # Redis 7
│   ├── redis-service.yaml          # ClusterIP
│   ├── cronjob-refresh-pricing.yaml  # */15 * * * *; python -m app.jobs.refresh_pricing
│   ├── cronjob-daily-report.yaml     # Daily email report
│   ├── cronjob-kilo-diff.yaml        # Weekly Kilo page hash check
│   └── servicemonitor.yaml           # Prometheus ServiceMonitor for /metrics scraping
└── overlays/
    └── prod/
        └── kustomization.yaml  # Prod overlay (image tag overrides, etc.)
```

## vscode/ — VS Code Extension & Workspace Config

```
vscode/
├── README.md               # How to install the extension
├── dotvscode/
│   ├── extensions.json          # Recommended extensions for contributors
│   └── settings.example.json    # Example workspace settings (modelPricing.apiBaseUrl, etc.)
└── extension/
    ├── package.json        # Extension manifest: contributes modelPricing.* settings + commands
    ├── tsconfig.json
    ├── .vscodeignore
    ├── README.md
    └── src/
        └── extension.ts   # activate(): status bar item polling /models/top + /kilo/projection every N seconds
```

## Naming Conventions

**Python files:** `snake_case.py`. Module names match their primary concern (e.g., `openrouter.py`, `pricing_calculator.py`).

**TypeScript files:** `PascalCase.tsx` for React components (`ModelTable.tsx`); `camelCase.ts` for non-component modules (`api.ts`).

**Kubernetes manifests:** `<resource-type>-<name>.yaml` (e.g., `api-deployment.yaml`, `cronjob-refresh-pricing.yaml`).

**Alembic migrations:** `YYYYMMDD_NNNN_<description>.py`.

## Where to Add New Code

**New API endpoint:**
- Add router function to an existing file in `api/app/routes/` or create a new `api/app/routes/<name>.py`
- Register the router in `api/app/main.py` via `app.include_router(...)`
- Add corresponding Pydantic schema to `api/app/schemas.py`

**New backend service / business logic:**
- Create `api/app/services/<name>.py`
- Import in the route or job that needs it

**New CronJob:**
- Add entrypoint to `api/app/jobs/<name>.py`
- Add `k8s/base/cronjob-<name>.yaml` and register it in `k8s/base/kustomization.yaml`

**New database table:**
- Add ORM model to `api/app/models.py`
- Generate Alembic migration: `alembic revision --autogenerate -m "description"`
- Place generated file in `api/alembic/versions/`

**New frontend page:**
- Create `web/src/app/<path>/page.tsx` (Next.js App Router file-based routing)
- Add nav link in `web/src/app/layout.tsx` if needed

**New frontend component:**
- Create `web/src/components/<ComponentName>.tsx`
- Add SWR data hook to `web/src/lib/api.ts` if the component needs API data

**New Kilo tier or pricing change:**
- Edit `api/app/data/kilo_plans.yaml` — this is the only file to change; no code modification needed

---

*Structure analysis: 2026-05-25*
