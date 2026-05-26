# Feature Landscape

**Domain:** Personal AI spend dashboard for coding workflows (Anthropic + OpenAI + OpenRouter + Kilo.ai)
**Researched:** 2026-05-25
**Confidence:** MEDIUM (mix of HIGH on provider APIs, MEDIUM-LOW on chart UX best practices and "what users expect" — extrapolated from the OSS AI-spend tracker ecosystem)

## Framing

This is a **personal, single-user tool** that already has a working OpenRouter pricing/ranking/Kilo foundation. The features evaluated below are filtered through that lens: anything that exists primarily to serve "teams", "tenants", "departments", or "showback/chargeback" is an anti-feature here, regardless of how prominently it appears in commercial FinOps tools.

The reference comparable is not Cloudzero or Finout — it is the OSS ccusage / claude-code-stats / Tokdash / phuryn-claude-usage cluster, plus Helicone/Langfuse for what a "real" cost dashboard renders. ([ccusage](https://github.com/ryoppippi/ccusage), [claude-code-stats](https://github.com/AeternaLabsHQ/claude-code-stats), [Tokdash](https://github.com/JingbiaoMei/tokdash), [LLMeter](https://www.llmeter.org/))

---

## Table Stakes

Features that would feel "missing" if absent. The dashboard would look unfinished without them.

| Feature | Why Expected | Complexity | Notes / Codebase Status |
|---------|--------------|------------|-------------------------|
| **Total spend headline (USD)** for current time range | First thing every cost dashboard shows; the answer to "what am I spending?" | Low | New — needs spend ingestion landed first |
| **Spend over time chart** (line or stacked area by provider) | Universal pattern: AWS Cost Explorer, OpenAI usage page, Helicone, Langfuse all lead with this | Low | New — Recharts already in stack ([Recharts stacked area](https://recharts.github.io/en-US/examples/StackedAreaChart/)) |
| **Per-provider breakdown** (Anthropic / OpenAI / OpenRouter / Kilo) | Whole reason to unify four providers; otherwise just use each provider's own dashboard | Low | New |
| **Per-model breakdown** within selected range | Models are the cost unit; "Claude Sonnet 4.6 cost me $X" is the real question | Low | New — pairs with existing ModelTable |
| **Time range selector with presets** (7d, 30d, 90d, custom) | Already in PROJECT.md as required. Pill-button row is the de-facto standard ([UX patterns](https://uxpatterns.dev/patterns/forms/date-range), [claude-code-stats](https://github.com/AeternaLabsHQ/claude-code-stats)) | Low | New — global filter, applies to all panels |
| **Token counts alongside dollars** (input / output / cached) | Anthropic Admin API surfaces cache hit ratio explicitly; OpenAI Usage API splits input/output. Hiding tokens means you can't sanity-check the dollar number ([Anthropic vs OpenAI billing APIs](https://www.finout.io/blog/anthropic-vs-openai-billig-api)) | Low | New |
| **Model comparison table** with cost/Mtok in/out, context window, tool support | Already exists as ModelTable for OpenRouter; needs the coding-characteristics columns added | Low | Partial — extend existing |
| **Per-model coding characteristics panel** (context, $/Mtok in/out, speed, HumanEval/SWE-bench/LiveCodeBench) | The differentiator the user explicitly asked for in PROJECT.md; ranks of "where to spend next dollar" require capability data next to cost ([Morph](https://www.morphllm.com/llm-context-window-comparison), [WhatLLM](https://whatllm.org/)) | Med | New — benchmark data sourcing is the work, not the UI |
| **Last-refreshed timestamp** on every spend panel | Spend data lags (Anthropic/OpenAI have minute-to-hourly granularity). Without a timestamp the user can't tell if "$0" means "no spend" or "ingestion broken" ([OpenAI Usage API](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058)) | Low | New — critical for trust |
| **Provider connection status** (which API keys are connected, last successful sync) | If one provider's ingestion silently breaks, totals lie. A "providers" status strip catches this | Low | New |
| **Top-N most expensive models** in the selected window | Helicone, Langfuse, OpenAI usage page all do this. Pairs naturally with the existing top-10 ranker | Low | New — reuse ranker pattern |
| **CSV / JSON export** of the current view | Personal tool means the user will want to slice it in a spreadsheet or paste it into LLM-driven analysis | Low | New — cheap to ship |
| **Persisted time-series of spend** | Already the pattern for pricing (`model_pricing_snapshot`). Mirror it for spend so historical queries don't re-hit provider APIs | Low | New — follows ARCHITECTURE.md append-only pattern |

---

## Differentiators

Features that distinguish this tool from a generic FinOps dashboard, given the personal-coding-workflow positioning. These earn the project's keep beyond what each provider's native dashboard already does.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Spend + capability in one row** | Every other dashboard shows spend or comparison, not both. Showing "you spent $X on Sonnet 4.6 — here's its context window, HumanEval, and how Opus would compare" is the whole pitch | Med | Requires joining spend rows to the existing pricing/capabilities data |
| **Kilo Pass effective-cost overlay** ("you spent $X PAYG; on Kilo Pro this would have been $Y") | Existing KiloCalculator already does the math for hypothetical usage; applying it retroactively to real spend is unique and directly answers "should I subscribe?" | Med | Reuse `kilo.project()` and `pricing_calculator.compare()` against ingested usage |
| **Cost-efficiency score per model** (existing ranker, but applied to *your actual usage mix*) | Existing ranker assumes 30/70 input/output. Your real ratio differs per model and per project — recompute against observed traffic | Med | Extends existing `ranker.py`; needs aggregation of real input/output token splits |
| **Cache hit-rate display** (Anthropic prompt caching, OpenAI cached input) | Caching is the single biggest cost lever on Claude. Anthropic Admin API exposes hit ratio; OpenAI surfaces `cached_tokens`. Surfacing this nudges better prompt design ([Anthropic Admin API](https://www.finout.io/blog/anthropic-vs-openai-billig-api)) | Low | Just plumbing once the API client is in place |
| **"Burn rate" forecast** for current period (extrapolate to month-end) | ccusage and claude-code-stats both have this; it's the "are you on track to overspend?" widget that motivates the dashboard being open | Low | Trivial math once the time-series exists ([Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)) |
| **Project status page** ("what's built vs. pending") | Already requested in PROJECT.md. Differentiator because most spend dashboards bury this in a README. Mirror the `## Validated / Active / Out of Scope` from PROJECT.md as a live page driven by frontmatter or YAML | Low | Drives self-awareness; pairs well with the GSD workflow |
| **Daily email digest extended to spend** (top-5 + Kilo savings already exist; add yesterday's actual spend) | The daily email is already shipped — extending it is one of the highest-ROI moves available | Low | Extend existing `daily_report.py` |
| **VS Code status bar shows today's spend** (not just blended rate) | Existing extension already polls `/models/top` and `/kilo/projection`. Adding `/spend/today` makes the widget answer "should I keep coding?" instead of just "what's a cheap model?" | Low | Extend existing extension |
| **Spend annotations** (e.g., "deployed change X on day Y" markers on the chart) | Personal tool advantage: you can correlate a spike to a specific change you made. Even a simple textarea-backed list of timestamped notes is enough | Low | Optional; high signal for a single user |
| **Per-API-key segmentation** (Anthropic, OpenAI, OpenRouter all support this) | If the user has separate keys for VS Code vs. CLI vs. side projects, breakdown by key answers "which workflow is expensive?" | Med | Depends on whether user actually uses multiple keys |
| **"What if I switched" calculator** — replay the period with model B's prices | Natural extension of the existing comparison logic and Kilo overlay | Med | Killer feature; depends on storing per-call input/output token counts, not just aggregates |

---

## Anti-Features

Things to deliberately NOT build. These appear in commercial FinOps tools but actively harm a personal, opinionated coding-spend dashboard.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|--------------------|
| **Multi-user / RBAC / tenants / workspaces** | PROJECT.md explicitly says "Public-facing access control / multi-user — personal tool". A bare-IP whitelist or single env-var token is enough | Single-tenant; if exposure matters, put behind Traefik basic auth or the existing OIDC if one's wired |
| **Budgets, alerts, threshold notifications, Slack/PagerDuty webhooks** | This is solved upstream: each provider already has spending limits and Anthropic/OpenAI send their own emails. Re-implementing it produces a notification mess and a second source of truth | Use provider-native budget controls; surface the limit value on the dashboard read-only |
| **Manual spend entry / receipt upload / invoice import** | PROJECT.md explicit out-of-scope. All four providers have APIs | If an API doesn't return spend, file an issue and wait — don't paper over it |
| **Recommendation engine** ("you could save $X by switching to model Y") | FinOps anti-pattern when not validated. The existing ranker + Kilo calculator already produce comparable info; surfacing it as a recommendation without context invites bad calls ([FinOps pitfalls](https://www.finops.org/wg/adopting-finops-avoiding-pitfalls/)) | Show the data, let the user decide. Maybe a "see comparison" link, not "switch to this" |
| **Showback / chargeback / cost allocation** | Single user. There's nothing to allocate to | Skip entirely |
| **Forecasting beyond a simple linear burn-rate** (ML-based, anomaly detection, etc.) | Overengineered for one user's spend pattern. Linear extrapolation of the current period is enough signal | Linear "at this rate, you'll hit $X by end of month" — no more |
| **Per-request trace inspection** (Helicone-style proxy with full request/response capture) | Out of scope: this is observability, not spend. Adds a proxy hop, storage costs, PII concerns. Helicone/Langfuse already exist if needed ([Helicone](https://docs.helicone.ai/guides/cookbooks/cost-tracking)) | Aggregate usage from billing APIs only. Don't proxy traffic |
| **Real-time WebSocket streaming of spend** | Provider billing APIs are minute-to-hourly granularity at best. Polling every 5–15 minutes is fine; WS gives no extra fidelity | Periodic refresh on a CronJob (already the pattern). Last-refreshed timestamp visible |
| **"Compare to industry benchmarks" / peer-comparison features** | No data, no peers, no relevance | Skip |
| **Currency switching / FX conversion** | All four providers bill in USD. Adding currency dropdowns is dead UI | USD-only; note it once in a footer if it matters |
| **More than ~4 segments in stacked area** | Visualization research is unanimous: stacked area readability falls off a cliff past 4–5 series. With exactly 4 providers this is fine; resist adding sub-segments inline ([Inforiver stacked area](https://inforiver.com/insights/stacked-area-charts-when-to-use-and-avoid/)) | Keep stacked area at provider level. Drill into model breakdown via a separate bar chart or table |
| **Tag-based cost allocation arbitrary key/value** | Cloud FinOps pattern. Not relevant — there are no untagged resources here, just provider+model | Provider and model are the only meaningful dimensions; per-key is a useful third |

---

## Feature Dependencies

```
Time range selector
  └── (gates every other panel)

Provider spend ingestion (4 services, one per provider)
  └── Spend time-series persistence (mirror of model_pricing_snapshot)
      ├── Total spend headline
      ├── Spend over time chart (stacked area)
      ├── Per-provider breakdown
      ├── Per-model breakdown (requires model_id in usage rows)
      │   └── Top-N expensive models
      ├── Burn rate forecast
      └── "What if I switched" replay (requires per-call input/output token counts, not just $ aggregates)

Per-model coding characteristics
  ├── extends existing ModelTable
  ├── benchmark data ingestion (HumanEval, SWE-bench, LiveCodeBench — likely manually curated or via WhatLLM/Morph scrape)
  └── pairs with per-model breakdown to enable "spend + capability in one row"

Kilo overlay on real spend
  ├── requires existing kilo.project() (have)
  └── requires per-call OR per-day token aggregates (new)

Provider connection status panel
  ├── reuses ingestion job state
  └── precondition for trusting all of the above

Project status page
  └── independent — can ship anytime
```

---

## MVP Recommendation

Given the codebase already has the OpenRouter+Kilo+ranking foundation, MVP is the unified spend layer:

1. **Anthropic spend ingestion** — biggest cost line for a coding workflow; Admin API is the most polished of the four ([Anthropic Admin API](https://www.finout.io/blog/anthropics-enterprise-analytics))
2. **OpenAI spend ingestion** — second; Usage API is well-documented and stable
3. **OpenRouter spend ingestion** — third; same provider as existing pricing integration, easiest plumbing
4. **Spend time-series schema** + persistence (mirror `model_pricing_snapshot`)
5. **Dashboard: total + stacked-area-by-provider + time range selector**
6. **Dashboard: per-model breakdown table** (extends existing ModelTable with `spend_in_range` and `tokens_in_range` columns)
7. **Per-model coding characteristics added to ModelTable** (context, $/Mtok in/out, HumanEval/SWE-bench)
8. **Project status page**
9. **Kilo.ai ingestion** — last because the API needs confirmation (PROJECT.md notes this)

Defer to post-MVP:
- Burn rate forecast (cheap, but only useful once a full month of data exists)
- Daily email extension to include actual spend (cheap; trivial after #4 lands)
- VS Code status bar "today's spend" (small extension change)
- Kilo overlay applied retroactively to real spend (high-value but needs the data layer fully landed first)
- "What if I switched" replay (requires per-call granularity; defer until per-aggregate version proves valuable)
- Per-API-key segmentation (only if user actually uses multiple keys)
- Spend annotations (nice-to-have)

Anti-features stay out at every phase.

---

## Chart-Type Recommendations (focused guidance)

| Question being answered | Best chart | Why |
|-------------------------|------------|-----|
| "What's the trend of my spend?" | **Stacked area chart** with one band per provider | Shows both total and composition in one view; ≤4 series = readable ([Domo area charts](https://www.domo.com/learn/charts/area-charts)) |
| "Which model cost the most this period?" | **Horizontal bar chart**, sorted descending, top 10 | Ranking is precise (vs. area which is approximate); horizontal accommodates long model names |
| "How does cost split across providers right now?" | **Headline numbers + small sparkline per provider**, NOT a pie chart | Pies are bad for >3 segments and bad for time comparison; a row of "Anthropic $X (↑12% vs last period)" cards is clearer |
| "How does today compare to other days?" | **Bar chart with one bar per day**, last 30 days | Discrete time buckets = bars, not area |
| "What's my cache hit rate trending?" | **Line chart** (single series, 0–100%) | Single ratio over time → line, not area |
| "Should I switch model A → model B?" | **Side-by-side comparison table** with diff column | Quantitative comparison; charts hide the numbers |

Recharts in the existing stack handles all of these natively. ([Recharts](https://recharts.org/))

---

## Time Range UX (focused guidance)

The de-facto pattern for spend dashboards ([OpenAI usage page](https://platform.openai.com/settings/organization/usage), [claude-code-stats](https://github.com/AeternaLabsHQ/claude-code-stats), [Tokdash](https://github.com/JingbiaoMei/tokdash), [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/)):

1. **Top-of-page pill row**: `Today | 7d | 30d | 90d | Custom` — single source of truth, applies to ALL panels on the page
2. **Selected pill is visually distinct** (background fill, not just border)
3. **Custom opens a two-input date range picker** with "Apply" — don't fire requests on every keystroke
4. **The current range is reflected in the URL** (`?range=30d` or `?from=...&to=...`) — enables sharing/bookmarking and browser-back
5. **Default to 30d** — long enough for trends, short enough that the API isn't hammered
6. **Show the resolved range explicitly** ("May 1, 2026 – May 25, 2026") near the pills so the user always knows what they're looking at
7. **Comparison mode (optional differentiator)**: "vs. previous period" toggle — Helicone and OpenAI both do this; produces the up/down arrows next to headline numbers

What to avoid:
- Year-pill (1y) — encourages over-long queries that are expensive and rarely useful for personal AI spend
- Per-panel time selectors — splits the mental model and invites mismatched views
- Calendar-only (no presets) — forces five clicks for the most common task

---

## Model Comparison Table (focused guidance)

Building on the existing `ModelTable` component, the proven column set across [Morph](https://www.morphllm.com/llm-context-window-comparison), [WhatLLM](https://whatllm.org/), [BenchLM](https://benchlm.ai/blog/posts/context-window-comparison), and [CostGoat](https://costgoat.com/compare/llm-api):

**Identity columns** (sticky-left):
- Model name (with provider badge: Anthropic / OpenAI / OpenRouter / Kilo)
- Family / variant grouping (collapsible)

**Cost columns:**
- $/Mtok input
- $/Mtok output
- $/Mtok cached input (Anthropic + OpenAI surface this; null otherwise)
- Effective blended cost (existing ranker logic, 30/70 default but user-tunable)
- **Your spend this range (new — joins with ingested usage)**
- **Your tokens this range** (new)

**Capability columns:**
- Context window (input)
- Max output tokens
- Tool/function calling support (yes/no badge)
- Effective context (RULER-style) — flag as "advertised vs effective" if data available ([BenchLM](https://benchlm.ai/blog/posts/context-window-comparison))

**Benchmark columns (coding-focused, per PROJECT.md):**
- HumanEval pass@1
- SWE-bench Verified
- LiveCodeBench
- Speed (tok/s) — observed if possible, else self-reported

**Sort/filter:**
- Sort by any column (existing pattern)
- Filter by provider (multi-select)
- Filter by min context window
- Filter by tool support
- Filter to "models I've actually used this range" — high-signal for a personal tool
- Search box for model name

**Anti-pattern**: trying to show 15+ columns by default. Default to ~6 visible columns with a "configure columns" menu; let the user pick what matters. Persist column choice to localStorage.

---

## Project Status Page (focused guidance)

Per PROJECT.md, this page should mirror the `## Validated / Active / Out of Scope` taxonomy as a live page.

Recommended structure:

```
[Header: "Project Status — last updated 2026-05-25"]

[3 columns: Validated | Active | Out of Scope]
  - each item is a row with: title, optional phase reference, optional link
  - use lightweight badge styling (no traffic-light kanban — it implies a process)

[Below: Recent decisions]
  - mirror PROJECT.md's Key Decisions table
  - show status (Pending / Done) and rationale

[Footer: link to PROJECT.md source-of-truth]
```

Implementation options (in order of preference):
1. **Read PROJECT.md at request time, parse the markdown, render** — single source of truth, no drift. Use a server-side markdown parser; cache for 5 min
2. **Static-generate at deploy time from PROJECT.md** — fine if rebuilds are frequent
3. **Maintain a separate `status.yaml`** — bad; duplicates state, will drift

Avoid: Gantt charts, burndown charts, percent-complete bars, milestone celebrations, "team velocity" — all are project-management theater for a personal tool.

---

## Reference Implementations Worth Studying

| Project | What to steal | What to skip |
|---------|---------------|--------------|
| [ccusage](https://github.com/ryoppippi/ccusage) | Daily/monthly/session report taxonomy; cache token tracking; offline mode with cached pricing | CLI-only output (we want a web dashboard) |
| [claude-code-stats](https://github.com/AeternaLabsHQ/claude-code-stats) | Global time-range pill UX; local HTML dashboard pattern | Local-only storage (we have Postgres) |
| [Tokdash](https://github.com/JingbiaoMei/tokdash) | Date range presets + custom Flatpickr; per-session drill-down | 3D visualizations (gimmick) |
| [LLMeter](https://www.llmeter.org/) | "Connect your provider keys, get unified spend" framing; spend-by-model panel layout | Marketing landing-page UI |
| [Langfuse](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Cost breakdown by usage type (input/output/cache); dashboard math conventions | Trace/span model — out of scope |
| [Helicone](https://docs.helicone.ai/guides/cookbooks/cost-tracking) | Per-user/per-endpoint cost cookbook; model registry approach | Proxy-based capture model |
| [WhatLLM](https://whatllm.org/), [Morph](https://www.morphllm.com/llm-context-window-comparison) | Model comparison table columns and sort/filter UX | Their stack rankings (we have our own ranker) |

---

## Sources

- [ccusage](https://github.com/ryoppippi/ccusage) — Claude Code usage analysis CLI
- [claude-code-stats](https://github.com/AeternaLabsHQ/claude-code-stats) — Local HTML dashboard for Claude Code
- [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) — Real-time monitor with burn rate / forecasts
- [Tokdash](https://github.com/JingbiaoMei/tokdash) — Token usage dashboard with date picker pattern
- [LLMeter](https://www.llmeter.org/) — OSS multi-provider AI cost dashboard
- [Langfuse — Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [Helicone — Cost Tracking & Optimization](https://docs.helicone.ai/guides/cookbooks/cost-tracking)
- [Anthropic vs OpenAI Billing APIs (Finout)](https://www.finout.io/blog/anthropic-vs-openai-billig-api)
- [Anthropic's Enterprise Analytics API (Finout)](https://www.finout.io/blog/anthropics-enterprise-analytics)
- [OpenAI Usage API announcement](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058)
- [Morph — LLM Context Window Comparison](https://www.morphllm.com/llm-context-window-comparison)
- [WhatLLM](https://whatllm.org/) — Live model comparison
- [BenchLM — Effective Context Window Comparison](https://benchlm.ai/blog/posts/context-window-comparison)
- [CostGoat — LLM API Pricing Comparison](https://costgoat.com/compare/llm-api)
- [Recharts — Stacked Area Chart](https://recharts.github.io/en-US/examples/StackedAreaChart/)
- [Domo — Area Charts Guide](https://www.domo.com/learn/charts/area-charts)
- [Inforiver — Stacked Area Charts: When to Avoid](https://inforiver.com/insights/stacked-area-charts-when-to-use-and-avoid/)
- [UX Patterns — Date Range](https://uxpatterns.dev/patterns/forms/date-range)
- [Smashing Magazine — UX Strategies for Real-Time Dashboards](https://www.smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/)
- [FinOps Foundation — Adopting FinOps Pitfalls](https://www.finops.org/wg/adopting-finops-avoiding-pitfalls/)
- [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/)
- [OpenAI Platform Usage](https://platform.openai.com/settings/organization/usage)
