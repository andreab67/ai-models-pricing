# Architecture Patterns

**Domain:** Multi-provider AI spend aggregation (FastAPI + Postgres + Redis)
**Researched:** 2026-05-25
**Confidence:** HIGH (provider APIs verified against official docs); MEDIUM (Kilo programmatic usage)

## Executive Summary

The existing system already gives us the right backbone: a CronJob-driven fetcher (`refresh_pricing`), an async SQLAlchemy + asyncpg path, an append-only snapshot table with `ON CONFLICT DO NOTHING`, and a Redis-with-in-memory-fallback cache. The spend feature should be a **strict extension** of that pattern, not a parallel system.

Concretely:

1. **Pull, don't push.** All four providers expose pull-based reporting APIs (Anthropic Admin, OpenAI Costs/Usage, OpenRouter Activity) — no webhooks. Mirror the existing 15-min CronJob pattern, but at a longer interval (hourly) since spend data has minute-level latency on Anthropic/OpenAI and is **30-day daily-grouped only** on OpenRouter.
2. **Daily-grain unified fact table.** The lowest-common-denominator across all four providers is *(date, provider, model)* with cost and token counts. Anthropic and OpenAI can do sub-daily, but OpenRouter caps at daily and Kilo has no usage API at all. Standardize on daily; add per-request detail later for providers that support it.
3. **Adapter interface, not abstraction astronaut.** A `SpendProvider` protocol with one method — `async fetch_spend(start, end) -> list[SpendRecord]` — is enough. The existing `services/openrouter.py` is already 80% an adapter; refactor it to fit, then copy-paste the shape for the other three.
4. **Kilo is the odd one out.** Kilo Gateway has **no usage API** (verified against their docs as of May 2026). We solve this with per-request usage capture: log the `usage` field returned in chat-completion responses ourselves. Since this dashboard is read-only (we don't proxy traffic), Kilo will require a **manual CSV import or scraping fallback** in v1, with a clear "Kilo: data lag X hours" disclosure in the UI.
5. **Build order:** schema → adapter protocol → refactor OpenRouter to fit → Anthropic adapter → OpenAI adapter → dashboard → Kilo workaround last.

---

## Recommended Architecture

### High-Level Component View

```
                   ┌──────────────────────────────────────────┐
                   │           FastAPI (existing)              │
                   │                                            │
   Browser ──────► │  /spend/summary  /spend/by-provider       │
                   │  /spend/by-model /spend/timeseries        │
                   │                                            │
                   │  services/spend.py  ──► repository layer  │
                   │                          (Postgres)        │
                   └──────────────┬───────────────────────────┘
                                  │ reads
                                  ▼
                   ┌──────────────────────────────────────────┐
                   │  spend_record (fact, daily grain)         │
                   │  spend_sync_run  (job audit)              │
                   │  model_pricing_snapshot  (existing)       │
                   └──────────────▲───────────────────────────┘
                                  │ writes (UPSERT)
                                  │
   ┌──────────────────────────────┴───────────────────────────┐
   │            CronJob: sync-spend (hourly)                   │
   │            python -m app.jobs.sync_spend                  │
   │                                                            │
   │   for adapter in registry.enabled():                       │
   │       records = await adapter.fetch_spend(start, end)      │
   │       await repo.upsert_spend(records, source=adapter.id)  │
   │                                                            │
   │   ┌─────────────┐ ┌─────────────┐ ┌────────────┐ ┌──────┐ │
   │   │ Anthropic   │ │ OpenAI      │ │ OpenRouter │ │ Kilo │ │
   │   │ Adapter     │ │ Adapter     │ │ Adapter    │ │ Adptr│ │
   │   └─────┬───────┘ └──────┬──────┘ └─────┬──────┘ └───┬──┘ │
   └─────────┼────────────────┼──────────────┼────────────┼────┘
             ▼                ▼              ▼            ▼
       Anthropic        OpenAI         OpenRouter      Kilo
       Admin API        Costs API      Activity API   (no API —
       /v1/orgs/        /organization/ /api/v1/        CSV import
       cost_report      costs          activity        or skip)
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `services/spend/base.py` | Defines `SpendProvider` protocol, `SpendRecord` dataclass, `ProviderRegistry` | (interface only) |
| `services/spend/anthropic.py` | Adapter — calls Admin cost_report, normalizes to `SpendRecord` | Anthropic Admin API |
| `services/spend/openai.py` | Adapter — calls `/organization/costs`, normalizes | OpenAI Admin API |
| `services/spend/openrouter.py` | Adapter — calls `/api/v1/activity`, normalizes | OpenRouter (management key) |
| `services/spend/kilo.py` | Adapter — CSV ingest in v1, scraping fallback later | Local file / Kilo dashboard |
| `services/spend/repository.py` | UPSERT into `spend_record`, query helpers, dimension lookups | Postgres |
| `services/spend/aggregator.py` | Read-side aggregation: by-provider, by-model, timeseries, totals | Postgres + Redis cache |
| `jobs/sync_spend.py` | CronJob entrypoint — iterates registered adapters, persists, audits | All adapters + repository |
| `routes/spend.py` | New FastAPI router exposing summary/breakdown/timeseries endpoints | aggregator |

**Boundary rule:** Adapters never touch the DB. They return `list[SpendRecord]`. The repository owns all SQL. This keeps the test surface small (mock the adapter, run the repo against a real DB; or test the adapter against a recorded VCR cassette without DB).

---

## Data Model

### Unified Spend Record

The hardest design decision is the canonical record shape. After cross-walking all four providers, the common denominator is:

```python
@dataclass(frozen=True)
class SpendRecord:
    # Identity (composite uniqueness key)
    provider: str            # "anthropic" | "openai" | "openrouter" | "kilo"
    bucket_date: date        # day (UTC) — daily grain
    model_id: str            # provider-native model id (e.g., "claude-opus-4-7")
    # Optional dimension (None when provider doesn't supply it)
    workspace_id: str | None # Anthropic workspace, OpenAI project, OR null
    api_key_id: str | None   # opaque key id when available

    # Measures
    usd_cost: Decimal        # authoritative — what the provider charged
    input_tokens: int        # uncached input
    cached_input_tokens: int # cache reads (Anthropic-specific, 0 elsewhere)
    cache_creation_tokens: int  # Anthropic prompt-cache writes
    output_tokens: int
    request_count: int       # may be None for cost-only sources

    # Provenance
    source_payload_hash: str # SHA-256 of raw payload row — for diff detection
    fetched_at: datetime
```

**Why daily-grain:**
- OpenRouter `/api/v1/activity` is **daily, last 30 days only** — hard cap.
- OpenAI `/organization/costs` supports **`bucket_width=1d` only** (verified).
- Anthropic supports 1m/1h/1d on usage but **cost endpoint is `1d` only**.
- Going finer than daily means storing data we can't get back for 3 of 4 providers.

**Anthropic dual-source caveat:** Anthropic exposes **cost** (`/cost_report`, USD, daily) and **usage** (`/usage_report/messages`, tokens, sub-daily). We need both — cost is authoritative for $, usage gives the token breakdown. The adapter fetches both, joins on `(date, model, workspace)`, and emits a single record. Document this clearly because OpenAI does it the other way (Usage API and Costs API also diverge slightly — Costs is the authoritative one, per OpenAI's own docs).

### Schema (Alembic migration)

```sql
-- New fact table; lives alongside existing model_pricing_snapshot
CREATE TABLE spend_record (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,           -- 'anthropic'|'openai'|'openrouter'|'kilo'
    bucket_date     DATE NOT NULL,
    model_id        TEXT NOT NULL,
    workspace_id    TEXT,                    -- nullable
    api_key_id      TEXT,                    -- nullable

    usd_cost                NUMERIC(14,6) NOT NULL,
    input_tokens            BIGINT NOT NULL DEFAULT 0,
    cached_input_tokens     BIGINT NOT NULL DEFAULT 0,
    cache_creation_tokens   BIGINT NOT NULL DEFAULT 0,
    output_tokens           BIGINT NOT NULL DEFAULT 0,
    request_count           BIGINT,          -- nullable (cost-only sources)

    source_payload_hash     TEXT NOT NULL,
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Idempotent re-runs: same logical row UPSERTs cleanly
    CONSTRAINT spend_record_unique UNIQUE
      (provider, bucket_date, model_id, COALESCE(workspace_id,''), COALESCE(api_key_id,''))
);

CREATE INDEX spend_record_provider_date_idx
  ON spend_record (provider, bucket_date DESC);

CREATE INDEX spend_record_model_date_idx
  ON spend_record (model_id, bucket_date DESC);

CREATE INDEX spend_record_date_idx
  ON spend_record (bucket_date DESC);

-- Audit/observability: who ran when, what did they pull
CREATE TABLE spend_sync_run (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    window_start    DATE NOT NULL,
    window_end      DATE NOT NULL,
    records_upserted INT,
    status          TEXT NOT NULL,           -- 'ok'|'partial'|'error'
    error_message   TEXT
);
CREATE INDEX spend_sync_run_provider_idx ON spend_sync_run (provider, started_at DESC);
```

**Why UPSERT, not append-only:** Unlike pricing snapshots (which are point-in-time observations), spend totals for a given day **change** as the day completes and as the provider's billing system reconciles. A request made at 23:59 UTC may not appear in the cost report for several minutes. Append-only here would produce duplicates and drift. UPSERT on the natural key is correct.

**Why composite unique with COALESCE:** Postgres treats NULL as distinct in unique constraints by default. Wrapping nullable dimensions in `COALESCE(..., '')` collapses them to a single canonical row when the provider doesn't supply that dimension.

**Why not partition by date:** At 4 providers × ~20 models × 365 days = ~30K rows/year. Partitioning is unjustified complexity for a single-user dashboard. Revisit at 1M+ rows.

---

## Polling vs. On-Demand

**Recommendation: scheduled poll (CronJob), not on-demand.**

| Factor | Scheduled poll | On-demand fetch |
|--------|---------------|----------------|
| API rate limits | Predictable, easy to stay under | Spikes when dashboard hits |
| Cost API latency | Anthropic warns 5+ min; OpenAI also lags — bad UX | Same — slow page loads |
| Provider quotas | Anthropic recommends ≤1/min; we'd hit ~4/min just from dashboard hits | Risk of throttling |
| Backfill | Easy — extend the window in the job | Awkward — would need separate flow |
| Existing pattern | Matches `refresh_pricing` exactly | New paradigm to introduce |

**Schedule:** hourly (`0 * * * *`). Each run pulls a rolling 3-day window per provider to absorb late-arriving data and handle re-billing reconciliation. UPSERT makes overlapping windows safe.

```yaml
# k8s/base/cronjob-sync-spend.yaml — new file
schedule: "0 * * * *"
# command: python -m app.jobs.sync_spend --window-days=3
```

**Initial backfill:** A one-shot `--window-days=30` invocation on first deploy populates the trailing 30 days (OpenRouter's hard cap). Anthropic and OpenAI go further back if needed.

**Cache layer for dashboard:** The aggregator caches read results in Redis with a 5-min TTL keyed by `(query_params, last_sync_at)`. This is consistent with existing `services/cache.py` semantics; in-memory fallback continues to apply.

---

## Provider Adapter Interface

### Protocol Definition

```python
# api/app/services/spend/base.py
from typing import Protocol
from datetime import date

class SpendProvider(Protocol):
    """Adapter contract for a single billing provider."""

    id: str                 # 'anthropic' | 'openai' | 'openrouter' | 'kilo'
    display_name: str       # 'Anthropic' (for UI)
    granularity: str        # 'daily' (all four are daily)
    enabled: bool           # gate via config / missing credentials

    async def fetch_spend(
        self,
        window_start: date,
        window_end: date,
    ) -> list[SpendRecord]:
        """Pull spend for the inclusive date range and normalize."""
        ...

    async def healthcheck(self) -> bool:
        """Quick credentials/auth probe — used by /readyz extension."""
        ...
```

### Registry

```python
# api/app/services/spend/registry.py
class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, SpendProvider] = {}

    def register(self, provider: SpendProvider) -> None:
        self._providers[provider.id] = provider

    def enabled(self) -> list[SpendProvider]:
        return [p for p in self._providers.values() if p.enabled]

# wired in main.py via lifespan or get_registry() dependency
```

**To add a 5th provider:** create `services/spend/<new>.py` implementing the protocol, register it in `main.py` (one line), wire its API key into `config.py` + `secret.example.yaml`. No changes to repository, jobs, routes, or UI.

### Per-Provider Adapter Notes

**Anthropic adapter** (`services/spend/anthropic.py`):
- Endpoints: `/v1/organizations/cost_report` (USD, daily) + `/v1/organizations/usage_report/messages` (tokens, `group_by=model`, `bucket_width=1d`)
- Auth: `x-api-key: $ANTHROPIC_ADMIN_KEY` (must start `sk-ant-admin...`, not a regular key)
- Header: `anthropic-version: 2023-06-01`
- Pagination: `has_more` / `next_page` — loop until exhausted
- Output: join cost + usage on `(date, model)` to emit one `SpendRecord`
- Confidence: HIGH (full docs reviewed)

**OpenAI adapter** (`services/spend/openai.py`):
- Endpoints: `GET /organization/costs` (authoritative for $) + `GET /organization/usage/completions` (for token detail)
- Auth: Admin Key (separate from inference key) — `Authorization: Bearer $OPENAI_ADMIN_KEY`
- Params: `start_time`, `end_time` in **Unix seconds** (not ISO — different from Anthropic), `bucket_width=1d`, `group_by[]=line_item` to surface per-model rows
- `line_item` is the per-model dimension — parse it to extract model id
- Confidence: HIGH

**OpenRouter adapter** (`services/spend/openrouter.py` — refactor existing file):
- Endpoint: `GET https://openrouter.ai/api/v1/activity`
- Auth: **management key** (distinct from inference key — has the analytics scope) as Bearer
- Returns last 30 completed UTC days, grouped by `(date, endpoint_id, model, provider)`
- Cost field already split as `usage` (standard) and `usage_byok` (BYOK passthrough) — sum or keep separate per UX decision
- Refactor opportunity: the existing `openrouter.py` already implements an *implicit* adapter shape (fetch_raw → _normalize → _persist). Generalize: extract `SpendProvider` protocol from this file's natural shape rather than imposing one externally.
- Confidence: HIGH

**Kilo adapter** (`services/spend/kilo.py`):
- **There is no programmatic usage/billing endpoint** as of May 2026 (verified across `gateway/api-reference`, `gateway/usage-and-billing`, `gateway/authentication`). Per-request `usage` is returned in chat-completion responses, but this dashboard does not proxy inference traffic.
- v1 strategy: **manual CSV import** — a route `POST /spend/import` accepts the CSV the user downloads from app.kilo.ai. The adapter parses, dedupes, and UPSERTs.
- v2 fallback: authenticated scrape of the dashboard (fragile; gate behind an opt-in flag).
- v3 (best): file a feature request and switch to API when shipped.
- UI must clearly label Kilo data as "last imported: <date>" to avoid implying live freshness.
- Confidence: MEDIUM (docs may have hidden endpoint we missed) — research flag.

---

## Patterns to Follow

### Pattern 1: Same-Shape Adapters

**What:** Every adapter has the same public surface (`fetch_spend`, `healthcheck`, the same dataclass output). Internal complexity is encapsulated.

**When:** Always. The moment one adapter starts returning a different shape, the registry/job/aggregator code starts branching on provider — and the abstraction has failed.

**Example:**
```python
class AnthropicAdapter:
    id = "anthropic"
    display_name = "Anthropic"
    granularity = "daily"

    def __init__(self, admin_key: str, http: httpx.AsyncClient) -> None:
        self._key = admin_key
        self._http = http
        self.enabled = bool(admin_key)

    async def fetch_spend(self, start: date, end: date) -> list[SpendRecord]:
        cost_rows = await self._fetch_cost(start, end)
        usage_rows = await self._fetch_usage(start, end)
        return list(self._join(cost_rows, usage_rows))
```

### Pattern 2: Job-Level Resilience, Not Adapter-Level

**What:** The `sync_spend` job iterates adapters; a single adapter failure logs + records a `spend_sync_run` row with status `error` but does **not** abort the run. Other providers still get their data.

**When:** Multi-source pull jobs where partial data is better than no data.

**Example:**
```python
for adapter in registry.enabled():
    run = await repo.start_run(adapter.id, start, end)
    try:
        records = await adapter.fetch_spend(start, end)
        n = await repo.upsert_spend(records)
        await repo.finish_run(run, status="ok", records=n)
    except Exception as exc:
        log.error("adapter_failed", provider=adapter.id, exc_info=exc)
        await repo.finish_run(run, status="error", error=str(exc))
        # continue — don't re-raise
```

### Pattern 3: Reuse Existing Cache + Mailer + Metrics Wiring

**What:** New `/spend/*` routes hit `services/cache.py` exactly like `/models` does today. The aggregator emits the same Prometheus counter/histogram via the existing `MetricsMiddleware`. No new observability stack.

**When:** Always. The existing infra is fine; extending it is faster and more consistent than introducing a parallel cache or metrics layer.

### Pattern 4: Schema-First, UI Last

**What:** Lock the `SpendRecord` shape and the `spend_record` table before writing any adapter. The DB shape is the integration contract.

**Why:** Adapters are easy to rewrite; migrations are not. Three adapters built against an unstable record shape = three rewrites.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Mirroring Each Provider's Response Verbatim

**What:** Storing Anthropic's response JSON in one table, OpenAI's in another, OpenRouter's in a third, then JOINing in the aggregator.

**Why bad:** Every dashboard query becomes a 4-way UNION with provider-specific field handling. Adding the 5th provider means rewriting every query. The aggregator becomes a Frankensteinified normalizer-after-the-fact.

**Instead:** Normalize **at the adapter boundary**. The DB sees only `SpendRecord` shape. Provider-specific JSON, if kept at all, lives in a separate `spend_raw` audit table that no read path queries.

### Anti-Pattern 2: Storing Per-Request Detail for Sources That Don't Have It

**What:** A `spend_request` table designed for per-request rows, populated with synthetic single-row entries for OpenRouter/Kilo because they only provide daily aggregates.

**Why bad:** Lying about grain. Queries that look like "show me request count per hour" return garbage when half the data is fake hourly aggregates of daily totals.

**Instead:** Daily grain everywhere. If per-request detail becomes valuable later for Anthropic/OpenAI, add a separate `spend_request_detail` table — and accept that "show requests" only works for those two providers.

### Anti-Pattern 3: Reusing the Existing `model_pricing_snapshot` Table

**What:** Cramming spend rows into the pricing snapshot table because "they're both about money and models."

**Why bad:** Different grain (snapshots are 15-min observations of price, spend is daily totals of cost). Different uniqueness keys. Different update semantics (snapshot is append-only, spend is UPSERT). Different query patterns. Joining them at read time is fine; merging them at storage time is a deadweight.

**Instead:** Separate fact tables. Join in the aggregator when you want "for model X, current rate is Y and yesterday's spend was Z."

### Anti-Pattern 4: Synchronous Refresh on Dashboard Load

**What:** A GET on `/spend/summary` that triggers `await registry.refresh_all()` if cache is stale.

**Why bad:** Page loads block on 4 external APIs, two of which (Anthropic, OpenAI) explicitly warn about polling frequency. First user request after cache eviction gets a 10s+ stall. Provider rate limits become user-visible.

**Instead:** Stay strictly pull-based via CronJob. Dashboard reads from DB only. If the user wants "refresh now," surface a button that enqueues a one-off job — never run the fetch in the request path.

### Anti-Pattern 5: Treating Kilo's Missing API as a Blocker

**What:** Delaying the whole feature until Kilo ships a usage API.

**Why bad:** Three-quarters of the value (Anthropic + OpenAI + OpenRouter) is deliverable without Kilo. Holding it hostage is wrong.

**Instead:** Ship the unified dashboard with three live providers and a clearly-labeled "Kilo: import CSV" affordance. Mark Kilo as a research flag for the next milestone.

---

## Scalability Considerations

Personal-use tool — the scaling story is mostly "don't over-engineer."

| Concern | At current (1 user) | At 10 providers, 5 years data | At hypothetical 100 users |
|---------|---------------------|-------------------------------|---------------------------|
| Row count | ~30K rows | ~250K rows | ~25M rows |
| Query path | Indexed scan on `(provider, bucket_date)` — sub-ms | Same, still trivial | Add monthly materialized view |
| Sync job runtime | ~5s per provider | ~30s total | Parallelize adapters (asyncio.gather, currently serial is fine) |
| Postgres size | ~10 MB | ~100 MB | ~10 GB — partition by year |
| Redis cache | 5-min TTL, same as today | Same | Add per-user namespaces |

**Today's decision:** Do not partition, do not materialize, do not parallelize. Single CronJob run, serial adapters, B-tree indexes. The existing 2-replica API deployment + single Postgres StatefulSet is sized correctly.

**Trigger to revisit:** When `spend_record` exceeds 1M rows OR a dashboard query exceeds 200ms p95, evaluate materialized views (`mv_spend_daily_by_provider`, refreshed by the sync job's final step).

---

## API Surface (FastAPI Routes)

New router `api/app/routes/spend.py`:

| Method | Path | Returns | Notes |
|--------|------|---------|-------|
| GET | `/spend/summary?range=7d|30d|90d|custom&start=&end=` | total USD, by-provider split, delta vs previous period | Replaces a homepage card |
| GET | `/spend/by-provider?range=` | list of `{provider, usd, pct_of_total, request_count}` | Pie/bar chart data |
| GET | `/spend/by-model?range=&provider=` | list of `{provider, model_id, usd, tokens_in, tokens_out, request_count}` | Table data |
| GET | `/spend/timeseries?range=&group_by=provider|model` | daily series for line chart | Cached 5 min |
| GET | `/spend/sync-status` | `{provider, last_run_at, last_status, window}` per provider | Health badge |
| POST | `/spend/import/kilo` | upload CSV → records inserted | Kilo workaround |
| POST | `/spend/sync` (auth: admin) | enqueue an immediate sync run | Optional, post-MVP |

Pydantic schemas live in `schemas.py` alongside existing ones; SWR hooks in `web/src/lib/api.ts` mirror existing conventions (`useSpendSummary`, `useSpendByProvider`, etc.).

---

## Build Order (Phased)

1. **Schema + repository** (1-2h)
   - Alembic migration for `spend_record` + `spend_sync_run`
   - ORM models in `app/models.py`
   - `services/spend/repository.py` with `upsert_spend`, `query_by_range`, `last_sync_for`
   - Unit tests with a Postgres test container

2. **Adapter protocol + registry** (1h)
   - `services/spend/base.py` (`SpendProvider` protocol, `SpendRecord` dataclass)
   - `services/spend/registry.py`
   - No real adapters yet — write a `FakeAdapter` for the test suite

3. **OpenRouter adapter** (2h) — known territory
   - New `services/spend/openrouter.py` consuming `/api/v1/activity`
   - Use **management key** (env: `OPENROUTER_MANAGEMENT_KEY`), distinct from existing inference key
   - VCR-style cassette tests
   - This validates the protocol against a known shape before touching Anthropic/OpenAI

4. **Anthropic adapter** (3h)
   - `services/spend/anthropic.py` — two endpoints, join cost+usage
   - New secret: `ANTHROPIC_ADMIN_KEY`
   - Test with cassettes

5. **OpenAI adapter** (2h)
   - `services/spend/openai.py`
   - New secret: `OPENAI_ADMIN_KEY`
   - Test with cassettes

6. **CronJob + initial backfill** (1h)
   - `app/jobs/sync_spend.py` mirroring `refresh_pricing.py` shape
   - `k8s/base/cronjob-sync-spend.yaml` (hourly)
   - One-shot 30-day backfill on first deploy (manual `kubectl create job --from=cronjob/sync-spend`)

7. **Aggregator + read routes** (2h)
   - `services/spend/aggregator.py` with Redis cache integration
   - `routes/spend.py` with the endpoints above
   - Pydantic schemas

8. **Frontend dashboard** (3-4h)
   - `web/src/app/spend/page.tsx` or extend existing dashboard
   - Components: `SpendSummaryCard`, `SpendByProviderChart`, `SpendByModelTable`, `SpendTimeseriesChart`, `TimeRangeSelector`
   - SWR hooks in `lib/api.ts`

9. **Kilo workaround** (1h)
   - `POST /spend/import/kilo` route + parser
   - File-upload UI affordance
   - Status badge in `/spend/sync-status`

10. **Project status page** (1h)
    - `web/src/app/status/page.tsx` reading from a static feature manifest

**Total estimate:** ~16-20h for one engineer. Sequencing matters: 1 → 2 → 3 (proves protocol) → 4,5,6 (build out + automate) → 7,8 (UX) → 9,10 (cleanup).

---

## Sources

- [Anthropic Usage and Cost API (official docs)](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api) — HIGH
- [Anthropic Cost Report API reference](https://docs.anthropic.com/en/api/admin-api/usage-cost/get-cost-report) — HIGH
- [OpenAI Costs API reference](https://developers.openai.com/api/reference/python/resources/admin/subresources/organization/subresources/usage/methods/costs) — HIGH
- [OpenAI Usage API announcement (community.openai.com)](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058) — HIGH
- [OpenRouter Get User Activity endpoint](https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity) — HIGH
- [OpenRouter Activity Export guide](https://openrouter.ai/docs/guides/guides/activity-export) — HIGH
- [Kilo Gateway Usage & Billing](https://kilo.ai/docs/gateway/usage-and-billing) — MEDIUM (sparse docs, no usage API confirmed)
- [Kilo Gateway API Reference](https://kilo.ai/docs/gateway/api-reference) — MEDIUM
- [Kilo Gateway Authentication](https://kilo.ai/docs/gateway/authentication) — MEDIUM
- [Registry-Driven Strategy Pattern for FastAPI (Medium)](https://medium.com/@snehal.shelar/build-dynamic-behavior-registry-based-strategy-for-scalable-fastapi-app-3e74c1f5952e) — MEDIUM
- [Adapter pattern for multi-provider integrations (Medium)](https://medium.com/@olorondu_emeka/adapter-design-pattern-a-guide-to-manage-multiple-third-party-integrations-dc342f435daf) — LOW (general reference)
- [Postgres as a Data Warehouse / star schema (Xata)](https://xata.io/blog/postgres-data-warehouse) — MEDIUM
- Existing repo: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md` — HIGH
