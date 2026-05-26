# model-pricing

Live OpenRouter token pricing vs. Kilo Code plan math, served at
`models.andrea-house.com`. Deploys to the `k8s-home` cluster.

## What's in the box

| Component       | Path                  | Notes                                                  |
|-----------------|-----------------------|--------------------------------------------------------|
| FastAPI backend | `api/`                | Polls OpenRouter, caches in Redis, persists snapshots in Postgres, renders daily email |
| Next.js dashboard | `web/`              | App Router, Tailwind, Recharts, dark/light, mobile responsive |
| K8s manifests   | `k8s/`                | Kustomize base + prod overlay, Traefik ingress, cert-manager TLS, CronJobs, ServiceMonitor |
| GitLab CI       | `.gitlab-ci.yml`      | lint → test → Kaniko build → Trivy scan → Harbor push → manual deploy |
| Local dev       | `docker-compose.yml`  | Postgres + Redis + API + Web                           |

## Architecture

```
                ┌────────────────────────────────────────────┐
                │   Traefik @ models.andrea-house.com (TLS)  │
                └───────────────┬────────────────────────────┘
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

                  CronJobs (in same namespace, same image):
                  • refresh-pricing  every 15m
                  • daily-report     08:00 America/Denver
                  • kilo-diff        Mon 07:00 (alerts on Kilo page change)
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

## Production deploy (k8s-home)

```bash
# 1. Harbor pull secret (one-time per namespace)
kubectl -n model-pricing create secret docker-registry harbor-pull \
  --docker-server=harbor.andrea-house.com \
  --docker-username=<robot> \
  --docker-password=<token>

# 2. Real secrets (replace the example with SealedSecret/ExternalSecret in prod)
kubectl -n model-pricing apply -f k8s/base/secret.example.yaml  # EDIT FIRST

# 3. Apply the overlay
kubectl apply -k k8s/overlays/prod

# 4. Verify
kubectl -n model-pricing get pods,svc,ingress,cronjobs
kubectl -n model-pricing logs deploy/api -f
kubectl -n model-pricing create job --from=cronjob/refresh-pricing seed
```

DNS: point `models.andrea-house.com` to the Traefik LB. cert-manager will mint
the cert via the `letsencrypt-prod` ClusterIssuer (ensure that's installed).

### CI/CD

The pipeline mirrors the ntp-checker structure. Required GitLab variables:

| Variable           | Notes                              |
|--------------------|------------------------------------|
| `HARBOR_REGISTRY`  | `harbor.andrea-house.com`          |
| `HARBOR_USERNAME`  | Harbor robot account               |
| `HARBOR_PASSWORD`  | Harbor robot secret (masked)       |
| `HARBOR_REPOSITORY`| `model-pricing`                    |
| `KUBE_CONFIG`      | base64 kubeconfig (file, protected) |

Production deploy is a manual job on `main`. Pre-push verification runs ruff,
pytest, and Trivy. Drop your ntp-checker `.gitlab-ci.yml` next to mine and
I'll diff/align.

## VSCode

See `vscode/README.md` for the recommended extensions and the companion
status-bar extension that shows live OpenRouter cost from this API.

## Notes & known limitations

- The "projected savings" line in the daily email assumes a 5M-in / 5M-out
  monthly workload against Claude Sonnet 4.6 baseline at Kilo Pass pro/m8.
  Override in `app/jobs/daily_report.py` if your baseline differs.
- `kilo_plans.yaml` is hand-maintained. The `kilo-diff` CronJob hashes the
  live page weekly and emails when it changes — refresh the YAML and commit.
- Postgres runs as a single-replica StatefulSet. Fine for this workload;
  swap to CloudNativePG or your managed flavor for HA.
- OpenRouter free tier rate limits (50 req/day) don't matter here because
  `/models` is unauthenticated and not throttled at that scale.
