# Tech Stack

**Analysis Date:** 2026-05-25

## Languages

- **Python 3.12** — API backend (`api/`)
- **TypeScript 5.6.3** — Frontend (`web/src/`)
- **YAML** — Kilo plans data (`api/app/data/kilo_plans.yaml`), Kubernetes manifests (`k8s/`)

## Frameworks & Libraries

### API (Python)

- **FastAPI 0.115.5** — REST API framework (`api/app/main.py`)
- **Uvicorn 0.32.1** (with `standard` extras) — ASGI server; 2-worker prod config in `api/Dockerfile`
- **Pydantic 2.9.2** — Schema validation and serialization (`api/app/schemas.py`)
- **pydantic-settings 2.6.1** — Config loading from env vars (`api/app/config.py`)
- **SQLAlchemy 2.0.36** (asyncio) — ORM and DB access (`api/app/db.py`, `api/app/models.py`)
- **asyncpg 0.30.0** — Async PostgreSQL driver
- **Alembic 1.13.3** — DB migrations (`api/alembic/`)
- **redis 5.2.0** — Redis client for caching (`api/app/services/cache.py`)
- **httpx 0.27.2** — Async HTTP client for external API calls
- **tenacity 9.0.0** — Retry logic for OpenRouter fetches (`api/app/services/openrouter.py`)
- **structlog 24.4.0** — Structured JSON logging (`api/app/logging.py`)
- **prometheus-client 0.21.0** — Prometheus metrics endpoint at `/metrics` (`api/app/main.py`)
- **aiosmtplib 3.0.2** — Async SMTP client for email reports (`api/app/services/mailer.py`)
- **Jinja2 3.1.4** — HTML email templating (`api/app/templates/daily_report.html`)
- **PyYAML 6.0.2** — Loads Kilo plan definitions from YAML
- **beautifulsoup4 4.12.3** — HTML scraping of Kilo pricing page (`api/app/services/kilo.py`)

### Web (Node/React)

- **Next.js 14.2.18** — React framework with App Router (`web/`)
- **React 18.3.1** / **react-dom 18.3.1** — UI runtime
- **Tailwind CSS 3.4.15** — Utility-first styling
- **Recharts 2.13.3** — Chart library for price history graphs
- **SWR 2.2.5** — Data fetching and caching hooks
- **lucide-react 0.460.0** — Icon set
- **next-themes 0.4.3** — Light/dark theme switching

## Build & Tooling

### API

- **Ruff 0.7.4** — Linter and formatter (`api/pyproject.toml` lint config: line-length 100, py312 target)
  - Rules: `E, F, I, W, B, UP, ASYNC, S, RUF`
- **mypy 1.13.0** — Static type checking
- **pytest 8.3.3** + **pytest-asyncio 0.24.0** — Test runner; `asyncio_mode = "auto"` (`api/pyproject.toml`)
- **respx 0.21.1** — httpx mock library for tests
- **setuptools >=68** — Build backend
- Docker multi-stage build: `builder` (compiles wheels) → `runtime` (installs from wheels, `python:3.12-slim`)

### Web

- **ESLint 9.15.0** + **eslint-config-next 14.2.18** — Linting
- **TypeScript** `tsc --noEmit` — Type checking (`npm run typecheck`)
- **PostCSS 8.4.49** + **autoprefixer 10.4.20** — CSS processing
- Docker multi-stage build: `deps` (npm ci) → `builder` (next build) → `runner` (standalone output, `node:20-alpine`)

### CI/CD

- **GitLab CI** (`.gitlab-ci.yml`) — 6-stage pipeline: lint → test → build → scan → publish → deploy
- **Kaniko v1.23.2** — Rootless container image builds in CI
- **Trivy 0.57.1** — Container vulnerability scanning (HIGH/CRITICAL, unfixed CVEs block main)
- **kubeconform** — Kubernetes manifest validation in lint stage
- **kubectl 1.31** (bitnami image) + **kustomize** — Production deployment via `k8s/overlays/prod`

## Runtime Dependencies (key ones)

| Service | Version | Purpose |
|---------|---------|---------|
| PostgreSQL | 16-alpine | Persistent storage for pricing snapshots |
| Redis | 7-alpine | In-process cache (TTL 15 min default) |
| Python | 3.12-slim | API runtime |
| Node.js | 20-alpine | Web runtime |

## Infrastructure

- **Kubernetes** — Production deployment (`k8s/` with Kustomize, namespace `model-pricing`)
- **Harbor** (`harbor.andrea-house.com`) — Private container registry; images: `model-pricing/api`, `model-pricing/web`
- **Traefik** — Ingress controller; TLS termination at `models.andrea-house.com`
- **cert-manager** — Automated TLS via `letsencrypt-prod` ClusterIssuer
- **Prometheus Operator** — Scrapes `/metrics` via `ServiceMonitor` (`k8s/base/servicemonitor.yaml`)
- **Kustomize overlays** — `k8s/base/` + `k8s/overlays/prod/` structure
- **CronJobs** (Kubernetes):
  - `refresh-pricing` — every 15 min, fetches OpenRouter data (`k8s/base/cronjob-refresh-pricing.yaml`)
  - `daily-report` — sends email digest (`k8s/base/cronjob-daily-report.yaml`)
  - `kilo-diff` — weekly Kilo pricing page change detection (`k8s/base/cronjob-kilo-diff.yaml`)
- **Config delivery** — `ConfigMap` (`model-pricing-config`) + `Secret` (`model-pricing-secrets`) mounted via `envFrom`

---

*Stack analysis: 2026-05-25*
