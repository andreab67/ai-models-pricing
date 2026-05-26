"use client";

import { useAccountUsage, fmtUsd, type AccountProviderUsage } from "@/lib/api";

const PROVIDER_META: Record<string, { name: string; color: string }> = {
  openrouter: { name: "OpenRouter", color: "text-violet-400" },
  kilo:       { name: "Kilo Code",  color: "text-blue-400"   },
  openai:     { name: "OpenAI",     color: "text-green-400"  },
  anthropic:  { name: "Anthropic",  color: "text-orange-400" },
};

function ProviderCard({ account }: { account: AccountProviderUsage }) {
  const meta = PROVIDER_META[account.provider];
  const isKilo = account.provider === "kilo";

  const usedPct =
    account.limit_usd && account.spent_usd != null
      ? Math.min(100, (account.spent_usd / account.limit_usd) * 100)
      : null;

  const usedColor =
    usedPct == null   ? "text-zinc-500"   :
    usedPct > 85      ? "text-red-400"    :
    usedPct > 60      ? "text-yellow-400" :
    "text-emerald-400";

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
          Key not configured —{" "}
          <span className="text-zinc-400">
            add {account.provider.toUpperCase()}_API_KEY to cluster secret
          </span>
        </p>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : isKilo ? (
        <p className="text-xs text-zinc-400">
          Live spend not available via API — check{" "}
          <span className="text-zinc-300">kilo.ai dashboard</span>
        </p>
      ) : (
        <>
          {account.spent_usd != null ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="text-zinc-400">{account.period_start ? `Since ${account.period_start}` : "Total used"}</span>
              <span className="text-right font-mono">{fmtUsd(account.spent_usd)}</span>

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
                      account.remaining_usd < 5  ? "text-red-400"     :
                      account.remaining_usd < 20 ? "text-yellow-400"  :
                      "text-emerald-400"
                    }`}
                  >
                    {fmtUsd(account.remaining_usd)}
                  </span>
                </>
              )}
            </div>
          ) : (
            <p className="text-xs text-emerald-400">Key active</p>
          )}

          {usedPct != null && (
            <p className={`text-xs text-right ${usedColor}`}>{usedPct.toFixed(1)}% used</p>
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

      {isLoading && <p className="text-sm text-zinc-500">Loading account data…</p>}
      {error && <p className="text-sm text-red-400">Failed to load: {error.message}</p>}
      {data && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <ProviderCard account={data.openrouter} />
          <ProviderCard account={data.kilo} />
          <ProviderCard account={data.openai} />
          <ProviderCard account={data.anthropic} />
        </div>
      )}
    </div>
  );
}
