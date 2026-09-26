import useSWR, { type SWRConfiguration } from "swr";

export interface ModelPricing {
  id: string;
  name: string;
  provider: string | null;
  prompt_usd_per_mtok: number;
  completion_usd_per_mtok: number;
  request_usd: number;
  image_usd: number;
  context_length: number | null;
  max_completion_tokens: number | null;
  supports_tools: boolean;
  supports_vision: boolean;
  throughput_tps: number | null;
  latency_ms: number | null;
  speed_provider: string | null;
  captured_at: string;
}

export interface RankedModel {
  model: ModelPricing;
  score: number;
  blended_usd_per_mtok: number;
  rank: number;
}

export type Channel =
  | "openrouter_payg"
  | "openrouter_byok"
  | "kilo_pass"
  | "kilo_byok";

export interface WrapperCost {
  channel: Channel;
  prompt_usd_per_mtok: number;
  completion_usd_per_mtok: number;
  notes: string | null;
}

export interface ModelComparison {
  model: ModelPricing;
  channels: WrapperCost[];
}

export interface KiloPlan {
  tier: string;
  monthly_usd: number;
  paid_credits_usd: number;
  max_bonus_pct: number;
  annual_usd: number | null;
  annual_bonus_pct: number | null;
}

export interface KiloProjection {
  tier: string;
  streak_months: number;
  paid_credits_usd: number;
  bonus_pct: number;
  bonus_credits_usd: number;
  total_effective_credits_usd: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "Invalid request parameters";
  } catch {
    // non-JSON error body
  }
  return res.statusText || "Request failed";
}

const fetcher = async <T,>(url: string): Promise<T> => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new ApiError(`${res.status}: ${await errorDetail(res)}`, res.status);
  }
  return (await res.json()) as T;
};

/** Encode a provider-qualified model id ("vendor/model:variant") for a URL path. */
export function modelPath(modelId: string): string {
  return modelId.split("/").map(encodeURIComponent).join("/");
}

export const STREAK_MIN = 1;
export const STREAK_MAX = 120;

export function clampStreak(n: number): number {
  if (!Number.isFinite(n)) return STREAK_MIN;
  return Math.min(STREAK_MAX, Math.max(STREAK_MIN, Math.trunc(n)));
}

/** Account endpoints return 404 when the web proxy does not expose them. */
export function isNotExposed(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

const defaultConfig: SWRConfiguration = {
  revalidateOnFocus: false,
  refreshInterval: 300_000, // 5 min
};

/**
 * Account endpoints answer 404 when the web proxy does not expose them
 * (EXPOSE_ACCOUNT_DATA unset). That is a permanent answer, so do not retry
 * it. Keep retrying other errors (SWR pauses interval polling while an error
 * is set, so giving up would leave the panel stale until reload), with
 * exponential backoff capped at 5 minutes.
 */
const accountConfig: SWRConfiguration = {
  ...defaultConfig,
  onErrorRetry: (error, _key, config, revalidate, { retryCount }) => {
    if (error instanceof ApiError && error.status === 404) return;
    const base = config.errorRetryInterval ?? 5_000;
    const delay = Math.min(base * 2 ** retryCount, 300_000);
    setTimeout(() => revalidate({ retryCount, dedupe: true }), delay);
  },
};

export function useModels() {
  return useSWR<ModelPricing[]>("/api/models", fetcher, defaultConfig);
}

export function useTopModels(n: number = 10) {
  return useSWR<RankedModel[]>(`/api/models/top?n=${n}`, fetcher, defaultConfig);
}

/**
 * Channel comparison for one model. Omit (or pass null for) the Kilo tier or
 * streak to let the API use the configured KILO_TIER at the steady-state
 * streak (the month the bonus reaches its cap). The month-1 welcome bonus is
 * one-off, so hard-coding month 1 overstated the recurring Kilo discount.
 */
export function useComparison(
  modelId: string | null,
  kiloTier?: string | null,
  kiloStreakMonths?: number | null,
  kiloAnnual: boolean = false,
) {
  let url: string | null = null;
  if (modelId) {
    const params = new URLSearchParams({ kilo_annual: String(kiloAnnual) });
    if (kiloTier) params.set("kilo_tier", kiloTier);
    if (kiloStreakMonths != null) {
      params.set("kilo_streak_months", String(clampStreak(kiloStreakMonths)));
    }
    url = `/api/compare/${modelPath(modelId)}?${params}`;
  }
  return useSWR<ModelComparison>(url, fetcher, defaultConfig);
}

export function useKiloPlans() {
  return useSWR<KiloPlan[]>("/api/kilo/plans", fetcher, defaultConfig);
}

export function useKiloProjection(
  tier: string,
  streakMonths: number,
  annual: boolean,
) {
  const url = `/api/kilo/projection?${new URLSearchParams({
    tier,
    streak_months: String(clampStreak(streakMonths)),
    annual: String(annual),
  })}`;
  return useSWR<KiloProjection>(url, fetcher, defaultConfig);
}

export function useHistory(modelId: string | null, days: number = 30) {
  const url = modelId ? `/api/models/${modelPath(modelId)}/history?days=${days}` : null;
  return useSWR<ModelPricing[]>(url, fetcher, defaultConfig);
}

export interface AccountProviderUsage {
  provider: "openrouter" | "kilo";
  configured: boolean;
  plan: string | null;
  limit_usd: number | null;
  spent_usd: number | null;
  remaining_usd: number | null;
  period_start: string | null;
  model_count: number | null;
  error: string | null;
}

export interface AccountsUsage {
  openrouter: AccountProviderUsage;
  kilo: AccountProviderUsage;
  fetched_at: string;
}

export function useAccountUsage() {
  return useSWR<AccountsUsage>("/api/accounts/usage", fetcher, accountConfig);
}

export interface ModelActivityItem {
  model_id: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface ActivityResponse {
  items: ModelActivityItem[];
  fetched_at: string;
}

export function useKiloModels() {
  return useSWR<ModelPricing[]>("/api/kilo/models", fetcher, {
    ...defaultConfig,
    refreshInterval: 900_000, // 15 min
  });
}

export function useActivity() {
  return useSWR<ActivityResponse>("/api/accounts/activity", fetcher, {
    ...accountConfig,
    refreshInterval: 900_000, // 15 min
  });
}

export function fmtUsd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "$0";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs < 0.01) return `${sign}$${abs.toFixed(4)}`;
  if (abs < 1) return `${sign}$${abs.toFixed(3)}`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function fmtSpeed(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${Math.round(n)} tok/s`;
}

export function fmtLatency(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

// Compact context-window formatter (1k / 1M suffix).
export function fmtCtx(tokens: number | null | undefined): string {
  if (tokens == null) return "—";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}k`;
  return String(tokens);
}

// Shared error formatter — keeps the three error surfaces (ModelTable,
// TopTenRanking, AccountBalances) consistent regardless of whether the
// thrown value is an Error, a string, or an arbitrary object. Deliberately
// avoids JSON.stringify on raw objects so React internals (digest, stack,
// componentStack) never leak into user-visible red text.
export function errMsg(error: unknown): string {
  if (error == null) return "Unknown error";
  if (typeof error === "string") return error || "Request failed";
  if (error instanceof Error) return error.message;
  if (typeof error === "object") {
    const e = error as { message?: unknown; statusText?: unknown };
    if (typeof e.message === "string") return e.message;
    if (typeof e.statusText === "string") return e.statusText;
  }
  return "Request failed";
}

// ---------------------------------------------------------------------------
// model-speed — https://model-speed.andrea-house.com
// CORS is open ("*") so the browser fetches directly.
// ---------------------------------------------------------------------------

const MODEL_SPEED_BASE = "https://model-speed.andrea-house.com";

export type Gateway = "openrouter" | "kilo";
export type ProbeStatus = "ok" | "throttled" | "timeout" | "error";

export interface SpeedProbeResult {
  gateway: Gateway;
  model_id: string;
  model_name: string;
  status: ProbeStatus;
  ttft_ms: number | null;
  tokens_per_sec: number | null;
  total_ms: number | null;
  completion_tokens: number | null;
  score_ms: number | null;
  error: string | null;
  captured_at: string;
  advertised_tokens_per_sec: number | null;
  tokens_per_sec_delta: number | null;
}

export interface SpeedChainEntry {
  rank: number;
  gateway: Gateway;
  model_id: string;
  score_ms: number;
  ttft_ms: number;
  tokens_per_sec: number;
}

export interface SpeedChain {
  generated_at: string;
  run_id: number;
  entries: SpeedChainEntry[];
}

export interface SpeedLatest {
  run_id: number;
  generated_at: string;
  results: SpeedProbeResult[];
  leaderboard: { rank: number; probe: SpeedProbeResult }[];
  chain: SpeedChain | null;
}

export interface SpeedRunSummary {
  id: number;
  started_at: string;
  finished_at: string | null;
  ok_count: number;
  throttled_count: number;
  error_count: number;
}

const speedConfig: SWRConfiguration = {
  revalidateOnFocus: false,
  refreshInterval: 60_000,
};

export function useSpeedLatest() {
  return useSWR<SpeedLatest>(`${MODEL_SPEED_BASE}/speed/latest`, fetcher, speedConfig);
}

export function useSpeedRuns(limit = 10) {
  return useSWR<SpeedRunSummary[]>(
    `${MODEL_SPEED_BASE}/speed/runs?limit=${limit}`,
    fetcher,
    speedConfig,
  );
}
