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
        <p className="text-xs text-red-400 break-all">{account.error}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <span className="text-zinc-400">Spent this month</span>
            <span className="text-right font-mono">
              {account.spent_usd != null ? fmtUsd(account.spent_usd) : "—"}
            </span>

            {account.limit_usd != null && (
              <>
                <span className="text-zinc-400">Credit limit</span>
                <span className="text-right font-mono">{fmtUsd(account.limit_usd)}</span>
              </>
            )}

            {account.remaining_usd != null && (
              <>
                <span className="text-zinc-400">Remaining</span>
                <span
                  className={`text-right font-mono font-semibold ${
                    account.remaining_usd < 5 ? "text-red-400" :
                    account.remaining_usd < 20 ? "text-yellow-400" :
                    "text-emerald-400"
                  }`}
                >
                  {fmtUsd(account.remaining_usd)}
                </span>
              </>
            )}
          </div>

          {usedPct != null && (
            <div className="space-y-1">
              <div className="h-1.5 w-full rounded-full bg-zinc-700">
                <div
                  className={`h-1.5 rounded-full transition-all ${barColor}`}
                  style={{ width: `${usedPct}%` }}
                />
              </div>
              <p className="text-xs text-zinc-500 text-right">{usedPct.toFixed(1)}% used</p>
            </div>
          )}

          {account.period_start && (
            <p className="text-xs text-zinc-600">Since {account.period_start}</p>
          )}
        </>
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
