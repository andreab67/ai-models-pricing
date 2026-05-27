# Software Bill of Materials (SBOM)

## Overview
This document provides a comprehensive inventory of all dependencies, libraries, and third-party components used in the AI Model Pricing Dashboard.

## Backend Dependencies

### Python 3.14
- **FastAPI** 0.104+ - Modern Python web framework
- **SQLAlchemy** 2.0+ - SQL toolkit and ORM
- **Alembic** - Database migrations
- **Pydantic** 2.0+ - Data validation
- **psycopg** (PostgreSQL async driver)
- **redis** - Redis client
- **httpx** - Async HTTP client
- **tenacity** - Retry library
- **PyYAML** - YAML parser
- **python-dotenv** - Environment configuration

### Development & Testing
- **pytest** - Testing framework
- **pytest-asyncio** - Async test support
- **ruff** - Python linter & formatter

## Frontend Dependencies

### Node.js 22 (LTS)
- **Next.js** 15+ - React framework with App Router
- **React** 19+ - UI library
- **TypeScript** 5+ - Type safety
- **Tailwind CSS** 3+ - Utility-first CSS
- **Recharts** - React charting library
- **SWR** 2.4+ - Data fetching
- **lucide-react** - Icon library
- **clsx** - Conditional classnames

### Development
- **ESLint** - Code linting
- **Prettier** - Code formatting
- **@types/node**, **@types/react** - TypeScript definitions

## Infrastructure

### Container & Orchestration
- **Docker** - Container runtime
- **Kubernetes** 1.28+ - Orchestration platform
- **Kustomize** - Kubernetes customization

### Networking & Security
- **Traefik** 2.10+ - Ingress controller
- **cert-manager** - TLS certificate management
- **OpenSSL** - Cryptography

### Observability
- **Prometheus** - Metrics collection
- **Grafana** (optional) - Metrics visualization

### Databases
- **PostgreSQL** 16+ - Relational database
- **Redis** 7+ - In-memory cache

## Third-Party APIs

### Model Providers
- **OpenRouter** API - Multi-provider LLM gateway
- **OpenAI** API - Claude, GPT models
- **Anthropic** API - Claude models
- **Kilo** API - Pricing tier management

## License Compliance

All production dependencies are compatible with BSD 3-Clause licensing. No GPL, AGPL, or restrictive licenses are used in the core codebase.

### Key License Notes
- **FastAPI, Starlette**: BSD 3-Clause compatible
- **SQLAlchemy**: MIT
- **React, Next.js**: MIT
- **Tailwind CSS**: MIT
- **Recharts**: MIT
- **PostgreSQL**: PostgreSQL License (permissive)
- **Redis**: Redis Source Available License (permissive for operational use)

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
