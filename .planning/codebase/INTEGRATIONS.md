# External Integrations

**Analysis Date:** 2026-05-25

## APIs & External Services

### OpenRouter (`https://openrouter.ai/api/v1`)

- **Purpose:** Primary data source — fetches the full catalogue of LLM model pricing
- **Endpoint used:** `GET /models` (returns per-token USD pricing for all models)
- **Auth:** No API key required for the public `/models` endpoint (unauthenticated)
- **Client:** `httpx.AsyncClient` with `tenacity` retry (3 attempts, exponential backoff)
- **Refresh cadence:** Every 15 minutes via Kubernetes CronJob `refresh-pricing`
- **Normalization:** Per-token decimals converted to USD/1M tokens in `api/app/services/openrouter.py`
- **Config env vars:** `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`), `OPENROUTER_TIMEOUT_S` (default 15s), `OPENROUTER_REFRESH_SECONDS` (default 900)

### Kilo Code (`https://kilo.ai/pricing`)

- **Purpose:** Secondary pricing source — compares Kilo Pass subscription credits vs. OpenRouter PAYG
- **Integration type:** Web scrape (HTML page), not an API
- **Client:** `httpx.AsyncClient` + `beautifulsoup4` HTML parser (`api/app/services/kilo.py`)
- **Usage:** Weekly CronJob `kilo-diff` hashes visible page text to detect tier/pricing changes and triggers email alert on diff
- **Static plan data:** Kilo tier definitions (paid credits, bonus %, annual discount) stored locally in `api/app/data/kilo_plans.yaml` and loaded via `PyYAML`
- **Config env vars:** `KILO_PRICING_URL` (default `https://kilo.ai/pricing`), `KILO_DIFF_USER_AGENT`

## Data Sources

### PostgreSQL 16 (self-hosted)

- **Purpose:** Persistent time-series storage of OpenRouter pricing snapshots
- **Schema:** `model_pricing_snapshots` table — one row per `(model_id, captured_at)` hourly bucket, with raw JSON blob
- **Connection:** `asyncpg` via SQLAlchemy asyncio engine
- **Migrations:** Alembic (`api/alembic/`); applied at startup by `migrate` init container
- **Config env var:** `DATABASE_URL` (`postgresql+asyncpg://...`)
- **Production delivery:** Kubernetes StatefulSet (`k8s/base/postgres-statefulset.yaml`) with PVC

### Redis 7 (self-hosted)

- **Purpose:** Short-lived read cache for OpenRouter normalized model list (avoids re-fetching on every API request)
- **Cache key:** `openrouter:models:normalized`
- **TTL:** 900 seconds (15 min, matches refresh cadence); configurable via `CACHE_TTL_SECONDS`
- **Client:** `redis-py 5.2.0` async client (`api/app/services/cache.py`)
- **Config env var:** `REDIS_URL` (default `redis://localhost:6379/0`)
- **Production delivery:** Kubernetes Deployment (`k8s/base/redis-deployment.yaml`)

## Notifications / Messaging

### SMTP Email (daily report)

- **Purpose:** Sends a daily HTML digest of the best-value coding models and Kilo vs. OpenRouter comparison
- **Client:** `aiosmtplib 3.0.2` (`api/app/services/mailer.py`)
- **Template:** Jinja2 HTML template at `api/app/templates/daily_report.html`
- **Triggered by:** Kubernetes CronJob `daily-report` (`k8s/base/cronjob-daily-report.yaml`)
- **Also triggered by:** Kilo pricing page diff detection (change alert email)
- **Auth:** STARTTLS with username/password credentials
- **Config env vars:**
  - `SMTP_HOST` — SMTP server hostname (required; no default)
  - `SMTP_PORT` — default `587`
  - `SMTP_USERNAME` — SMTP auth username
  - `SMTP_PASSWORD` — SMTP auth password (secret)
  - `SMTP_STARTTLS` — default `true`
  - `SMTP_FROM` — default `pricing-bot@andrea-house.com`
  - `SMTP_TO` — JSON list of recipient addresses (e.g. `["andreab@greenyogainc.com"]`)
- **Behavior when unconfigured:** Logs a warning and skips send silently (no crash)

## Monitoring / Observability

### Prometheus

- **Purpose:** Collects HTTP request count and latency metrics from the API
- **Exposition:** `GET /metrics` endpoint on the API service (Prometheus text format)
- **Metrics exposed:** `http_requests_total` (counter, labels: method/path/status), `http_request_duration_seconds` (histogram, labels: method/path)
- **Collection:** Prometheus Operator `ServiceMonitor` scrapes every 30s (`k8s/base/servicemonitor.yaml`)
- **Client:** `prometheus-client 0.21.0` with multiprocess mode support (`api/app/main.py`)

### Structured Logging (structlog)

- **Purpose:** JSON-formatted application logs shipped to cluster log aggregator
- **Library:** `structlog 24.4.0` (`api/app/logging.py`)
- **Format:** ISO timestamp + log level + key-value pairs as JSON to stdout
- **Config env var:** `LOG_LEVEL` (default `INFO`)

## Container Registry

### Harbor (`harbor.andrea-house.com`)

- **Purpose:** Private OCI registry storing built API and web images
- **Images:** `model-pricing/api`, `model-pricing/web`
- **Auth:** Robot account credentials (`HARBOR_USERNAME`, `HARBOR_PASSWORD`) — used by Kaniko during CI build and by `imagePullSecrets: harbor-pull` in Kubernetes pods
- **Tags:** `latest` + `$CI_COMMIT_SHORT_SHA` per build

## TLS / Certificate Management

### Let's Encrypt (via cert-manager)

- **Purpose:** Automated TLS certificates for `models.andrea-house.com`
- **ClusterIssuer:** `letsencrypt-prod`
- **Delivery:** cert-manager renews and stores cert in secret `models-andrea-house-tls` (`k8s/base/ingress.yaml`)

---

*Integration audit: 2026-05-25*
