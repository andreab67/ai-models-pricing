"use client";

import { useAccountUsage, fmtUsd, type AccountProviderUsage } from "@/lib/api";

const PROVIDER_LABELS: Record<string, { name: string; color: string }> = {
  openai: { name: "OpenAI", color: "text-green-400" },
  anthropic: { name: "Anthropic", color: "text-orange-400" },
};

function ProviderCard({ account }: { account: AccountProviderUsage }) {
  const meta = PROVIDER_LABELS[account.provider];

  const usedPct =
    account.limit_usd && account.spent_usd != null
      ? Math.min(100, (account.spent_usd / account.limit_usd) * 100)
      : null;

  const barColor =
    usedPct == null ? "bg-zinc-600" :
    usedPct > 85 ? "bg-red-500" :
    usedPct > 60 ? "bg-yellow-500" :
    "bg-emerald-500";

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className={`font-semibold ${meta.color}`}>{meta.name}</span>
        {account.plan && (
          <span className="text-xs text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded">
            {account.plan}
          </span>
        )}
      </div>

      {!account.configured ? (
        <p className="text-xs text-zinc-500">
          API key not configured —{" "}
          <span className="text-zinc-400">add {account.provider.toUpperCase()}_API_KEY to cluster secret</span>
        </p>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : (
        <p className="text-xs text-emerald-400">Key active</p>
      )}
    </div>
  );
}

export function AccountBalances() {
  const { data, error, isLoading } = useAccountUsage();

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/50 p-4 space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
        My API Accounts
      </h2>

      {isLoading && (
        <p className="text-sm text-zinc-500">Loading account data…</p>
      )}
      {error && (
        <p className="text-sm text-red-400">Failed to load: {error.message}</p>
      )}
      {data && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <ProviderCard account={data.openai} />
          <ProviderCard account={data.anthropic} />
        </div>
      )}
    </div>
  );
}
