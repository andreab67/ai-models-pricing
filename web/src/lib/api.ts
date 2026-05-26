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

const fetcher = async <T,>(url: string): Promise<T> => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${url} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
};

const defaultConfig: SWRConfiguration = {
  revalidateOnFocus: false,
  refreshInterval: 300_000, // 5 min
};

export function useModels() {
  return useSWR<ModelPricing[]>("/api/models", fetcher, defaultConfig);
}

export function useTopModels(n: number = 10) {
  return useSWR<RankedModel[]>(`/api/models/top?n=${n}`, fetcher, defaultConfig);
}

export function useComparison(
  modelId: string | null,
  kiloTier: string,
  kiloStreakMonths: number,
  kiloAnnual: boolean,
) {
  const url = modelId
    ? `/api/compare/${modelId}?kilo_tier=${kiloTier}&kilo_streak_months=${kiloStreakMonths}&kilo_annual=${kiloAnnual}`
    : null;
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
  const url = `/api/kilo/projection?tier=${tier}&streak_months=${streakMonths}&annual=${annual}`;
  return useSWR<KiloProjection>(url, fetcher, defaultConfig);
}

export function useHistory(modelId: string | null, days: number = 30) {
  const url = modelId ? `/api/models/${modelId}/history?days=${days}` : null;
  return useSWR<ModelPricing[]>(url, fetcher, defaultConfig);
}

export interface AccountProviderUsage {
  provider: "openai" | "anthropic";
  configured: boolean;
  plan: string | null;
  limit_usd: number | null;
  spent_usd: number | null;
  remaining_usd: number | null;
  period_start: string | null;
  error: string | null;
}

export interface AccountsUsage {
  openai: AccountProviderUsage;
  anthropic: AccountProviderUsage;
  fetched_at: string;
}

export function useAccountUsage() {
  return useSWR<AccountsUsage>("/api/accounts/usage", fetcher, {
    ...defaultConfig,
    refreshInterval: 300_000,
  });
}

export function fmtUsd(n: number): string {
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}
