# Software Bill of Materials (SBOM)

## Overview
This document provides a comprehensive inventory of all dependencies, libraries, and third-party components used in the AI Model Pricing Dashboard.

## Backend Dependencies

### Python 3.14
- **FastAPI** >=0.116.0 - Modern Python web framework
- **Starlette** >=0.49.1 - ASGI toolkit (FastAPI's foundation)
- **uvicorn[standard]** >=0.32.1 - ASGI server
- **SQLAlchemy[asyncio]** >=2.0.40 - SQL toolkit and ORM
- **Alembic** >=1.15.0 - Database migrations
- **Pydantic** >=2.10.0 - Data validation
- **pydantic-settings** >=2.7.0 - Settings management from env vars
- **psycopg[binary,pool]** >=3.3.4 - PostgreSQL driver (psycopg 3)
- **redis** ==5.2.0 - Redis client
- **httpx** ==0.27.2 - Async HTTP client
- **tenacity** ==9.0.0 - Retry library (used for OpenRouter fetch backoff)
- **PyYAML** ==6.0.2 - YAML parser (Kilo plan definitions)
- **structlog** ==24.4.0 - Structured logging
- **prometheus-client** ==0.21.0 - `/metrics` instrumentation
- **Jinja2** ==3.1.4 - Daily report HTML templating
- **beautifulsoup4** ==4.12.3 - Kilo pricing-page text extraction (kilo-diff)
- **aiosmtplib** ==3.0.2 - Async SMTP client (email reports)

### Development & Testing
- **pytest** ==8.3.3 - Testing framework
- **pytest-asyncio** ==0.24.0 - Async test support
- **ruff** ==0.7.4 - Python linter & formatter
- **mypy** ==1.13.0 - Static type checking
- **respx** ==0.21.1 - HTTP mocking for tests

## Frontend Dependencies

### Node.js 22 (LTS)
- **Next.js** ^15 - React framework with App Router
- **React** ^19 / **React DOM** ^19 - UI library
- **next-themes** ^0.4.3 - Dark/light mode
- **TypeScript** ^5 - Type safety
- **Tailwind CSS** ^4.3.3 (via `@tailwindcss/postcss`) - Utility-first CSS
- **Recharts** ^2.15.0 - React charting library
- **SWR** ^2.4.1 - Data fetching
- **lucide-react** ^0.511.0 - Icon library

### Development
- **ESLint** ^9 (flat config, `eslint .`) - Code linting
- **eslint-config-next** ^15, **@eslint/eslintrc** ^3.3.1
- **postcss** ^8.4.49
- **@types/node** ^22, **@types/react** ^19, **@types/react-dom** ^19 - TypeScript definitions

### Pinned Overrides (security)
- **cross-spawn** ^7.0.5, **picomatch** ^4.0.4 — forced via `package.json` `overrides`; the web Dockerfile fails the build if the resolved `picomatch` drops below the fixed release

## Infrastructure

### Container & Orchestration
- **Docker** - Container runtime
- **Kubernetes** 1.27+ (CronJob `spec.timeZone` requires 1.27+) - Orchestration platform
- **Kustomize** - Kubernetes customization

### Networking & Security
- **Traefik** - Ingress controller (`ingressClassName: traefik`; no version pinned in the manifests)
- **OpenSSL** - Cryptography

### Observability
- **Prometheus** - Metrics collection (scrape `/metrics`; optional `ServiceMonitor` for Prometheus Operator)
- **Grafana** (optional, not shipped) - Metrics visualization

### Databases
- **PostgreSQL** 16 (`postgres:16-alpine` in `docker-compose.yml`) - Relational database
- **Redis** 7 (`redis:7-alpine` in `docker-compose.yml`) - In-memory cache

## Third-Party APIs

### Model Providers
- **OpenRouter** API - Multi-provider LLM gateway
- **OpenAI** API - GPT models
- **Anthropic** API - Claude models
- **Kilo** API - Pricing tier management

## License Compliance

Most production dependencies use permissive (MIT/BSD/Apache) licenses. Redis
is the one source-available exception, noted below — confirm it's acceptable
for your deployment before shipping.

### Key License Notes
- **FastAPI, Starlette**: BSD 3-Clause
- **SQLAlchemy**: MIT
- **React, Next.js**: MIT
- **Tailwind CSS**: MIT
- **Recharts**: MIT
- **PostgreSQL**: PostgreSQL License (permissive)
- **Redis**: Licensing depends on the version. Up to 7.2.x: BSD-3-Clause. 7.4.x: RSALv2/SSPLv1 (source-available, not OSI-approved). 8.0+: RSALv2/SSPLv1/AGPLv3 (AGPLv3 is OSI-approved open source). This repo's `docker-compose.yml` uses `redis:7-alpine`; verify which license your deployed Redis image/version uses.

## Pinned Versions

Critical dependencies are pinned in lock files:
- `api/pyproject.toml` - Python dependency specifications
- `web/package-lock.json` - Node.js exact versions

## Security Considerations

- All dependencies are regularly scanned via Trivy
- Known CVEs are suppressed only with documented justification (see `.trivyignore`)
- No pre-built binaries are committed to version control
- All build artifacts are generated at build-time in CI/CD

## Updates & Maintenance

- Python: Quarterly minor version updates, immediate patch releases for security
- Node.js: Track LTS releases, upgrade annually
- Framework dependencies: Monthly review, quarterly upgrades
- Patch dependencies: Automated via Dependabot or manual review

## Support & Verification

For questions about dependency compatibility or license compliance, refer to:
- Individual LICENSE files in `node_modules/` and Python site-packages
- GitHub dependency graph at repository settings
- SBOM validation via CycloneDX (available in releases)
