# Code Conventions

**Analysis Date:** 2026-05-25

## Python (API)

### Module Header Pattern
Every module opens with a one-line docstring describing purpose, then `from __future__ import annotations`.

```python
"""Rank models for coding workloads."""

from __future__ import annotations
```

### Naming

- **Files/modules:** `snake_case` — `pricing_calculator.py`, `models_api.py`
- **Classes:** `PascalCase` — `ModelPricingSnapshot`, `WrapperCost`
- **Functions/methods:** `snake_case` — `channels_for()`, `effective_discount()`
- **Private helpers:** leading underscore — `_apply_markup()`, `_blended()`, `_normalize()`
- **Constants:** `UPPER_SNAKE` — `CACHE_KEY`, `REQ_COUNT`
- **Module-level singletons:** leading underscore — `_settings = get_settings()`

### Type Annotations
All public functions and most private helpers carry full type annotations using the modern `X | Y` union syntax (Python 3.10+):

```python
def top_n(models: list[ModelPricing], n: int | None = None) -> list[RankedModel]:
```

Return types are always annotated. `Any` is used only for JSON-typed values (`dict[str, Any]`).

### Import Order (ruff `I` rules enforced)
1. Standard library (`from __future__`, then stdlib)
2. Third-party packages
3. Local `app.*` imports

```python
from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.schemas import ModelPricing
```

### Settings Pattern
Configuration is a singleton loaded at module level via `lru_cache`. Never instantiate `Settings()` directly:

```python
# api/app/config.py
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

# In consumer modules
_settings = get_settings()  # called once at module load
```

`Settings` uses `pydantic-settings` with env file support. All fields have defaults; required secrets (SMTP, DB) default to empty string/safe no-op, not errors.

### Error Handling
- HTTP errors raise `HTTPException` at the route layer with explicit `status_code` and `detail`
- Service-level exceptions bubble up; routes catch specific types (e.g. `ValueError` → 400)
- `tenacity` handles external HTTP retries (3 attempts, exponential backoff) in `openrouter.py`
- The cache class catches all `Exception` on Redis operations and falls back to in-memory — failures are logged as warnings, never re-raised

```python
try:
    return kilo.project(tier, streak_months, annual=annual)
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
```

### Logging
`structlog` with JSON output. Pattern: get a module-level logger, then call with keyword arguments:

```python
log = get_logger(__name__)
log.info("openrouter_fetch_ok", count=len(data))
log.warning("redis_unavailable", url=self._url, error=str(exc))
log.error("refresh_pricing_failed", error=str(exc), exc_info=True)
```

Log event names use `snake_case` verbs: `openrouter_fetch_ok`, `refresh_pricing_done`, `redis_get_failed`.

### Async Pattern
All I/O-bound code is `async`/`await`. Routes are async. Services that touch the network, DB, or cache are async. Pure computation functions (ranker, pricing_calculator) are synchronous.

### SQLAlchemy
Uses the async SQLAlchemy 2.x pattern with `session_scope()` context manager:

```python
async with session_scope() as session:
    stmt = select(ModelPricingSnapshot).where(...)
    rows = (await session.execute(stmt)).scalars().all()
```

ORM models use `Mapped` + `mapped_column` (SQLAlchemy 2.x typed mapping, `api/app/models.py`).

### Pydantic Schemas
`BaseModel` subclasses in `api/app/schemas.py`. Field descriptions via `Field(description=...)`. Validation uses `model_validate()`, serialization uses `model_dump(mode="json")`.

### Linting (ruff 0.7.4)
Config in `api/pyproject.toml`:
- `line-length = 100`
- `target-version = "py312"`
- Rules: `E, F, I, W, B, UP, ASYNC, S, RUF`
- `S101` (assert in tests) is ignored
- Run: `ruff check api/`

### No Inline Noqa Suppression (except documented)
The only `# noqa` in the codebase is `# noqa: S104` on the `0.0.0.0` bind address in `api/app/config.py`, which has an inline comment explaining it's intentional for containers.

---

## TypeScript / React (Web)

### File Naming
- **Page files:** `page.tsx` (Next.js App Router convention)
- **Components:** `PascalCase.tsx` — `ModelTable.tsx`, `ThemeToggle.tsx`
- **Lib/utilities:** `camelCase.ts` — `api.ts`
- **Config files:** lowercase — `next.config.mjs`, `tailwind.config.ts`

### Component Pattern
Named exports (not default exports) for all components:

```typescript
export function ModelTable({ onSelect }: Props) { ... }
```

Pages use `default export`:

```typescript
export default function DashboardPage() { ... }
```

### Props Typing
Always an explicit `interface Props { ... }` defined inline above the component:

```typescript
interface Props {
  onSelect: (id: string) => void;
}
```

### Strict TypeScript
`tsconfig.json` has `"strict": true`. No `allowJs`. `noEmit` (types only, Next.js handles build). Path alias `@/*` maps to `src/*`.

### Data Fetching Pattern
All API calls use `useSWR` hooks defined in `web/src/lib/api.ts`. One hook per endpoint, all returning typed generics:

```typescript
export function useModels() {
  return useSWR<ModelPricing[]>("/api/models", fetcher, defaultConfig);
}
```

Global SWR config: `revalidateOnFocus: false`, `refreshInterval: 300_000` (5 min auto-refresh).

### Interface Mirroring
TypeScript interfaces in `web/src/lib/api.ts` mirror the Pydantic schemas in `api/app/schemas.py` field-for-field. Types use `number` (not `bigint`), `string | null` for optionals, and string literal unions for discriminated types:

```typescript
export type Channel = "openrouter_payg" | "openrouter_byok" | "kilo_pass" | "kilo_byok";
```

### Styling Rules
Tailwind utility classes are the primary styling mechanism. Custom design tokens are CSS variables in `web/src/app/globals.css` using RGB component syntax:

```css
:root { --bg: 248 250 252; --accent: 34 197 94; }
```

Consumed as `rgb(var(--bg))` or `bg-[rgb(var(--bg))]`.

**Inline `style={{...}}` props are present** in several components (e.g. `ModelTable.tsx`, `layout.tsx`, `KiloPassCalculator.tsx`) — specifically for dynamic CSS variable references that Tailwind cannot express statically. This is a partially-implemented convention: the codebase has inline styles despite the project-level rule against them. New code should prefer Tailwind classes or the `.card` utility class defined in `globals.css`.

### Client vs. Server Components
Files that use React state or browser APIs are marked `"use client"` at the top. Layout and page files that only compose are server components by default (no directive needed).

---

## Configuration

### Environment Variables
- API: loaded via `pydantic-settings` from `.env` at `api/app/config.py`
- Web: `API_BASE_URL` env var consumed in `next.config.mjs` for proxy rewrites
- Example files: `api/.env.example`, `k8s/base/secret.example.yaml`
- Never committed: actual `.env`, secret values

### YAML Data Files
Static plan data lives in `api/app/data/kilo_plans.yaml` and is loaded at runtime via `_load_yaml()`. Version-controlled, not a secret.

### Alembic Migrations
Located at `api/alembic/versions/`. Migration files named `YYYYMMDD_NNNN_description.py` (e.g. `20260525_0001_initial.py`).

---

## Git / CI

### Branch Strategy
`main` is the production branch. CI pipelines gate on `main` for builds/deploys.

### CI Pipeline Stages
`lint → test → build → scan → publish → deploy`

- `lint:api` — ruff on `api/**`
- `lint:web` — `next lint` + `tsc --noEmit` on `web/**`
- `lint:k8s` — kubeconform on `k8s/**`
- `test:api` — pytest with live Postgres + Redis services
- Build via Kaniko (not Docker-in-Docker), pushes to Harbor
- Scan via Trivy (`HIGH,CRITICAL`, `--ignore-unfixed`)
- Deploy is `when: manual` on `main`

### Change-Based Rules
CI jobs use `changes:` filters so only affected components run on feature branches. All jobs also run on `merge_request_event`.

---

## Notable Patterns

### Module-Level Singleton Services
Services that are expensive to initialize (`cache`, `_settings`) are instantiated once at module import time and reused. `get_settings()` uses `@lru_cache(maxsize=1)`.

### Separation of I/O and Computation
Pure computation functions (`pricing_calculator.channels_for`, `ranker.top_n`, `kilo.project`) are synchronous and take plain data types — no I/O, no async. Routes wire them together with async data-fetching calls.

### Job Entrypoints as `__main__` Scripts
CronJob scripts in `api/app/jobs/` follow the same pattern: `async def _main() -> int`, then `if __name__ == "__main__": sys.exit(asyncio.run(_main()))`.

### Graceful Degradation
The Redis cache falls back to in-process `dict` when Redis is unreachable. Routes remain functional; only freshness and cross-replica consistency degrade.

### API Proxy via Next.js Rewrites
The web frontend never calls the API directly — all requests go to `/api/*` and Next.js rewrites to `API_BASE_URL`. This avoids CORS issues in production and keeps the API internal.
