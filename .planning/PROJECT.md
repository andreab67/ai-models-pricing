# Model Pricing — AI Spend Dashboard

## What This Is

A personal dashboard for tracking real AI spending across Anthropic (Claude), OpenAI, OpenRouter, and Kilo.ai — showing actual costs pulled from provider billing APIs, broken down by model and time range. Each model also surfaces coding-relevant characteristics (context window, cost/Mtok, benchmarks, speed) so spend and capability live in the same view. The existing codebase tracks OpenRouter model *pricing*; this evolves it into a unified *spend* intelligence tool.

## Core Value

Know exactly what you're spending on AI coding tools, per model and provider, with the data to judge whether you're getting value.

## Requirements

### Validated

- ✓ Model pricing data pulled from OpenRouter — existing
- ✓ Kilo Pass effective cost calculator (KiloPass tiers, YAML-driven) — existing
- ✓ Model ranking — top-10 by coding cost efficiency (30/70 input/output blend, ≥64K context, tool support filter) — existing
- ✓ Price history time-series — PostgreSQL snapshots, append-only — existing
- ✓ Daily email digest — top-5 models + Kilo savings vs Sonnet 4.6 — existing
- ✓ Kilo.ai pricing page change detection — SHA-256 diff, email alert — existing
- ✓ VS Code extension — status bar widget (top model rate + Kilo projection) — existing
- ✓ Next.js dashboard — ModelTable, ModelDetailModal, TopTenRanking, KiloCalculator — existing
- ✓ Redis caching with in-memory fallback — existing
- ✓ Kubernetes deployment — home cluster, `model-pricing` namespace, Traefik ingress — existing
- ✓ GitLab CI pipeline — lint → test → build → scan → publish → deploy — existing
- ✓ Prometheus metrics + ServiceMonitor — existing

### Active

- [ ] Pull actual spend from Anthropic billing API
- [ ] Pull actual spend from OpenAI usage API
- [ ] Pull actual spend from OpenRouter usage API
- [ ] Pull actual spend from Kilo.ai platform API
- [ ] Unified spending dashboard — total spend and breakdown by provider / model / time range
- [ ] Time range selector — 7d, 30d, 90d, custom
- [ ] Per-model coding characteristics panel — context window, cost/Mtok (in/out), speed/latency, coding benchmarks (HumanEval, SWE-bench)
- [ ] Project status page — feature inventory showing built vs. pending
- [ ] Dev startup command — documented, single-command `docker compose up` dev environment

### Out of Scope

- Manual spend entry — provider APIs exist for all four targets
- Non-coding model characteristics — focus is coding relevance
- Public-facing access control / multi-user — personal tool

## Context

The codebase already has the foundation: FastAPI + Next.js + Postgres + Redis, deployed on the home k8s cluster at `models.andrea-house.com`. The OpenRouter integration (`services/openrouter.py`) is the pattern to follow for new provider integrations. Spend data requires API keys with billing-read scopes — Anthropic, OpenAI, and OpenRouter all expose usage endpoints; Kilo.ai's API needs to be confirmed.

Cluster operations (deploys, pod logs, config updates) are done exclusively via MCP servers: `home` and `sr-k8s` for Kubernetes, `vps-control` for VPS-level operations. No direct kubectl or bash for cluster ops.

## Constraints

- **Tech stack**: FastAPI / Next.js / PostgreSQL / Redis — no new runtimes
- **Ops tooling**: All cluster operations via MCP servers (home, sr-k8s, vps-control)
- **Deployment target**: Home k8s cluster, `model-pricing` namespace
- **Dev environment**: `docker compose up --build` — must remain the dev entry point

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Pull spend from provider APIs | User wants live data, not manual input | — Pending |
| MCP-first cluster ops | Consistent with existing workflow tooling setup | — Pending |
| Kilo.ai = Kilo.ai platform | Not KiloPass YAML tiers — live billing API | — Pending |
| Coding characteristics in same view | User wants spend + capability collocated, not separate pages | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-25 after initialization*
