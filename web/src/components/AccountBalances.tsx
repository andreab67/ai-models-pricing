"use client";

import {
  errMsg,
  useAccountUsage,
  useActivity,
  fmtUsd,
  type AccountProviderUsage,
} from "@/lib/api";

function OpenRouterCard({ account }: { account: AccountProviderUsage }) {
  const { data: activityData, error: activityError } = useActivity();

  const usedPct =
    account.limit_usd && account.spent_usd != null
      ? Math.min(100, (account.spent_usd / account.limit_usd) * 100)
      : null;

  const usedColor =
    usedPct == null  ? "text-muted"      :
    usedPct > 85     ? "text-red-400"    :
    usedPct > 60     ? "text-yellow-400" :
    "text-emerald-400";

  const totalSpend =
    activityData?.items.reduce((s, i) => s + i.cost_usd, 0) ?? null;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-violet-400">OpenRouter</span>
        {account.plan && (
          <span className="text-xs text-muted bg-border px-2 py-0.5 rounded">
            {account.plan}
          </span>
        )}
      </div>

      {!account.configured ? (
        <p className="text-xs text-muted">
          Key not configured —{" "}
          <span className="text-fg/70">add OPENROUTER_API_KEY to cluster secret</span>
        </p>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : (
        <>
          {account.spent_usd != null ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="text-muted">
                {account.period_start ? `Since ${account.period_start}` : "Total used"}
              </span>
              <span className="text-right font-mono">{fmtUsd(account.spent_usd)}</span>

              {account.limit_usd != null && (
                <>
                  <span className="text-muted">Credit limit</span>
                  <span className="text-right font-mono">{fmtUsd(account.limit_usd)}</span>
                </>
              )}

              {account.remaining_usd != null && (
                <>
                  <span className="text-muted">Remaining</span>
                  <span
                    className={`text-right font-mono font-semibold ${
                      account.remaining_usd < 5  ? "text-red-400"    :
                      account.remaining_usd < 20 ? "text-yellow-400" :
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

          <div className="pt-2 border-t border-border space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                OpenRouter Models Used
              </span>
              {totalSpend != null && (
                <span className="text-xs font-mono text-muted">{fmtUsd(totalSpend)}</span>
              )}
            </div>

            {activityError && (
              <p className="text-xs text-red-400">
                Activity: {errMsg(activityError)}
              </p>
            )}
            {!activityData && !activityError && (
              <p className="text-xs text-muted">Loading…</p>
            )}
            {activityData && activityData.items.length === 0 && (
              <p className="text-xs text-muted/60">
                Requires OpenRouter management key —{" "}
                <a
                  href="https://openrouter.ai/settings/keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-muted"
                >
                  generate one
                </a>
                {" "}and set OPENROUTER_ADMIN_KEY in cluster secret
              </p>
            )}
            {activityData && activityData.items.length > 0 && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted border-b border-border">
                    <th className="text-left font-normal pb-1.5">Model</th>
                    <th className="text-right font-normal pb-1.5">Requests</th>
                    <th className="text-right font-normal pb-1.5">In tok</th>
                    <th className="text-right font-normal pb-1.5">Out tok</th>
                    <th className="text-right font-normal pb-1.5">Spend</th>
                  </tr>
                </thead>
                <tbody>
                  {activityData.items.map((item) => (
                    <tr
                      key={item.model_id}
                      className="border-b border-border/40 last:border-0"
                    >
                      <td className="py-1.5 font-mono text-fg/80">{item.model_id}</td>
                      <td className="py-1.5 text-right font-mono">
                        {item.requests.toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right font-mono">
                        {item.prompt_tokens.toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right font-mono">
                        {item.completion_tokens.toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right font-mono">{fmtUsd(item.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function AccountBalances() {
  const { data, error, isLoading } = useAccountUsage();

  return (
    <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
        My API Accounts
      </h2>

      {isLoading && <p className="text-sm text-muted">Loading account data…</p>}
      {error && (
        <p className="text-sm text-red-400">Failed to load: {errMsg(error)}</p>
      )}
      {data && <OpenRouterCard account={data.openrouter} />}
    </div>
  );
}
