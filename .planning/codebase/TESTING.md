# Testing

**Analysis Date:** 2026-05-25

## Test Strategy

The project has unit tests for the two core computation services (pricing calculator and ranker). There are no integration tests, no API-level tests, and no frontend tests. The test suite is deliberately narrow and fast — it covers pure business logic without spinning up any services locally. CI provides the live-service integration layer (Postgres + Redis via GitLab service containers).

## What's Tested

### `api/tests/test_pricing_calculator.py`
Tests `api/app/services/pricing_calculator.py` — the function that computes per-channel costs.

| Test | What it verifies |
|------|-----------------|
| `test_openrouter_payg_adds_5_5_percent` | PAYG markup is `rate * 1.055` for both prompt and completion |
| `test_openrouter_byok_adds_5_percent` | BYOK markup is `rate * 1.05` |
| `test_kilo_byok_is_passthrough` | Kilo BYOK channel returns raw provider prices unchanged |
| `test_kilo_pass_applies_discount_at_month_8` | At streak month 8 monthly, 40% bonus produces ~28.57% effective discount |
| `test_kilo_pass_annual_is_50_pct_bonus` | Annual plan applies flat 50% bonus → ~33.3% effective discount |

### `api/tests/test_ranker.py`
Tests `api/app/services/ranker.py` — eligibility filtering and ranking logic.

| Test | What it verifies |
|------|-----------------|
| `test_excludes_free_models` | Models with 0/0 pricing are excluded from ranking |
| `test_excludes_models_without_tool_support` | `supports_tools=False` disqualifies a model |
| `test_excludes_small_context` | Models with context < 64K (default threshold) are excluded |
| `test_orders_by_blended_cost` | Sorted ascending by `0.30*input + 0.70*output`; `rank` field is 1-indexed |

## How to Run Tests

```bash
# From the api/ directory (or set PYTHONPATH)
cd api
pip install -e ".[dev]"
pytest -q

# With verbose output
pytest -v

# Run a single test file
pytest tests/test_pricing_calculator.py -v

# Run a single test
pytest tests/test_ranker.py::test_orders_by_blended_cost -v
```

**CI command** (`.gitlab-ci.yml`):
```bash
pytest -q
```

CI runs with live Postgres (`postgresql+asyncpg://pricing:pricing@postgres:5432/pricing`) and Redis (`redis://redis:6379/0`) via GitLab service containers. The test suite itself does not currently use either service — this infrastructure is in place for future integration tests.

## Coverage and Gaps

### Well Tested
- `pricing_calculator.channels_for()` — all four channel types and their markup/discount math
- `ranker.top_n()` — all three eligibility rules and sort ordering

### Not Tested
The following are entirely untested:

**Services:**
- `api/app/services/openrouter.py` — `fetch_raw()`, `_normalize()`, `refresh_pricing()`, `_persist()`, `list_models()`, `get_history()`
- `api/app/services/cache.py` — Redis fallback logic, TTL expiry, JSON encode/decode
- `api/app/services/kilo.py` — `monthly_bonus_pct()`, `project()`, `fetch_pricing_hash()`, the YAML loader
- `api/app/services/mailer.py` — email sending (untested)

**Routes:**
- `api/app/routes/compare.py` — compare endpoint, Kilo plans/projection endpoints
- `api/app/routes/models_api.py` — list, top, detail, history endpoints
- `api/app/routes/health.py` — `/healthz`, `/readyz`

**Jobs:**
- `api/app/jobs/refresh_pricing.py`
- `api/app/jobs/daily_report.py`
- `api/app/jobs/kilo_diff.py`

**Web (frontend):**
- No tests at all — no Jest, Vitest, or Playwright configuration present
- `web/src/lib/api.ts` — SWR hooks, `fmtUsd()` formatter, `fetcher()` — all untested
- All components in `web/src/components/` are untested

**Database layer:**
- `api/app/db.py` — `session_scope()`, connection pool setup
- Alembic migrations (`api/alembic/versions/`) — not tested in CI

### Coverage Configuration
No coverage threshold is enforced. No `--cov` flag is passed in CI. Coverage is not measured.

## Test Infrastructure

### Framework
- **Runner:** pytest 8.3.3 (`api/pyproject.toml`)
- **Async mode:** `asyncio_mode = "auto"` — all `async def test_*` functions run automatically without `@pytest.mark.asyncio`
- **Test path:** `testpaths = ["tests"]`
- **HTTP mocking:** `respx` 0.21.1 is installed as a dev dependency (for mocking `httpx` calls) but not yet used in any test
- **Type checking:** `mypy` 1.13.0 is a dev dependency; not wired into CI

### Fixtures
Tests use pytest fixtures for test data. The `sonnet` fixture in `test_pricing_calculator.py` is the only fixture defined:

```python
@pytest.fixture
def sonnet() -> ModelPricing:
    return ModelPricing(
        id="anthropic/claude-sonnet-4.6",
        name="Claude Sonnet 4.6",
        provider="anthropic",
        prompt_usd_per_mtok=3.0,
        completion_usd_per_mtok=15.0,
        context_length=1_000_000,
        supports_tools=True,
        supports_vision=True,
        captured_at=datetime.now(UTC),
    )
```

`test_ranker.py` uses a local factory function `_m()` instead of a fixture:

```python
def _m(mid: str, p: float, c: float, ctx: int = 200_000, tools: bool = True) -> ModelPricing:
    return ModelPricing(id=mid, name=mid, provider=mid.split("/")[0], ...)
```

### No Test Database
Tests do not touch the database. The `DATABASE_URL` and `REDIS_URL` CI environment variables are set for future integration tests but no current test exercises them.

### Assertion Style
- Floating-point comparisons use `pytest.approx(value, rel=1e-3)` for relative tolerance
- Set membership uses `{r.model.id for r in ranked} == {"x/y"}` pattern
- Ordering asserts use list equality on `.model.id` fields

## Adding New Tests

- Place test files in `api/tests/` with prefix `test_`
- For new service tests: import the service module directly and call functions with `ModelPricing` instances built inline or via fixtures
- For async tests: just write `async def test_*()` — no decorator needed with `asyncio_mode = "auto"`
- For HTTP-mocking tests (openrouter, kilo): use `respx` which is already installed; mock `httpx.AsyncClient`
- For route-level tests: add `httpx` + `pytest-asyncio` test client pattern against the FastAPI `app` object in `api/app/main.py`
