"use client";

import {
  errMsg,
  isNotExposed,
  useAccountUsage,
  useActivity,
  fmtUsd,
  type AccountProviderUsage,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Per-provider metadata: display name, accent color, and order. The order
// reflects what the operator wants to see first on the dashboard.
// ---------------------------------------------------------------------------

type ProviderId = AccountProviderUsage["provider"];

interface ProviderMeta {
  label: string;
  accent: string;
  description: string;
}

const META: Record<ProviderId, ProviderMeta> = {
  minimax: {
    label: "MiniMax",
    accent: "text-rose-400",
    description: "mmx token plan / coding plan balance",
  },
  kilo: {
    label: "Kilo",
    accent: "text-cyan-400",
    description: "Kilo Code gateway plan + model access",
  },
  openrouter: {
    label: "OpenRouter",
    accent: "text-violet-400",
    description: "OpenRouter credit balance + per-model activity",
  },
  deepseek: {
    label: "DeepSeek",
    accent: "text-sky-400",
    description: "DeepSeek user balance (USD)",
  },
};

// OpenRouter sits alone at the top because it's the only provider whose card
// carries a per-model activity subtable -- that table reads horizontally and
// doesn't fit cleanly inside a 1/3-width column. The remaining three
// providers share the same compact status grid below.
const PRIMARY: ProviderId = "openrouter";
const REST_ORDER: ProviderId[] = ["minimax", "kilo", "deepseek"];

// ---------------------------------------------------------------------------
// Shared card body. Each provider renders the same status grid: plan, used,
// limit, remaining, period, plus an error/dashboard link. OpenRouter layers
// the per-model activity table on top of this body.
// ---------------------------------------------------------------------------

function ProviderCard({
  account,
  children,
}: {
  account: AccountProviderUsage;
  children?: React.ReactNode;
}) {
  const meta = META[account.provider];
  const usedPct =
    account.limit_usd && account.spent_usd != null
      ? Math.min(100, (account.spent_usd / account.limit_usd) * 100)
      : null;

  const usedColor =
    usedPct == null
      ? "text-muted"
      : usedPct > 85
        ? "text-red-400"
        : usedPct > 60
          ? "text-yellow-400"
          : "text-emerald-400";

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className={`font-semibold ${meta.accent}`}>{meta.label}</span>
          <p className="text-[10px] text-muted/70 uppercase tracking-wider mt-0.5">
            {meta.description}
          </p>
        </div>
        {account.plan && (
          <span className="text-xs text-muted bg-border px-2 py-0.5 rounded shrink-0">
            {account.plan}
          </span>
        )}
      </div>

      {!account.configured ? (
        <p className="text-xs text-muted">
          Key not configured —{" "}
          <span className="text-fg/70">
            set the matching API key in the cluster secret
          </span>
        </p>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : account.spent_usd == null && account.remaining_usd == null && account.usage_count == null && !account.quota_windows?.length ? (
        <p className="text-xs text-emerald-400">Key active</p>
      ) : account.quota_windows && account.quota_windows.length > 0 ? (
        // MiniMax view: render each quota window as its own row. Each entry
        // is one slice of the plan's allowance (e.g. "general 5h", "general
        // weekly", "video 5h") so the operator sees every quota on its own
        // line instead of a single worst-case aggregate.
        <div className="space-y-1.5">
          {account.quota_windows.map((w, i) => {
            const pctColor =
              w.remaining_percent < 20
                ? "text-red-400"
                : w.remaining_percent < 50
                  ? "text-yellow-400"
                  : "text-emerald-400";
            // limit=0 means the quota is "unlimited" -- the vendor returns
            // usage=0 too. Show the percent but skip the "/limit" suffix
            // so we don't render a misleading "0/0".
            const showLimit = w.limit > 0;
            return (
              <div
                key={`${w.name}-${w.period}-${i}`}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-muted">
                  {w.name} <span className="text-muted/60">({w.period})</span>
                </span>
                <span className="font-mono">
                  <span className={`font-semibold ${pctColor}`}>
                    {w.remaining_percent.toFixed(1)}%
                  </span>
                  {showLimit && (
                    <span className="text-muted/70 ml-2">
                      {w.usage}/{w.limit}
                    </span>
                  )}
                  {!showLimit && (
                    <span className="text-muted/60 ml-2">unlimited</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ) : account.usage_count != null || account.usage_limit != null || account.remaining_percent != null ? (
        // Legacy non-USD view (no per-window breakdown available).
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <span className="text-muted">
              {account.remaining_percent != null ? "Remaining" : "Usage"}
            </span>
            <span
              className={`text-right font-mono font-semibold ${
                account.remaining_percent == null
                  ? "text-fg"
                  : account.remaining_percent < 20
                    ? "text-red-400"
                    : account.remaining_percent < 50
                      ? "text-yellow-400"
                      : "text-emerald-400"
              }`}
            >
              {account.remaining_percent != null
                ? `${account.remaining_percent.toFixed(1)}%`
                : `${(account.usage_count ?? 0).toLocaleString()} ${
                    account.currency ?? "reqs"
                  }`}
            </span>

            {account.usage_count != null && account.usage_limit != null && (
              <>
                <span className="text-muted">This period</span>
                <span className="text-right font-mono">
                  {account.usage_count.toLocaleString()} / {account.usage_limit.toLocaleString()}{" "}
                  {account.currency ?? "reqs"}
                </span>
              </>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <span className="text-muted">
              {account.period_start
                ? `Since ${account.period_start.slice(0, 10)}`
                : "Used"}
            </span>
            <span className="text-right font-mono">
              {account.spent_usd != null ? fmtUsd(account.spent_usd) : "—"}
            </span>

            {account.limit_usd != null && (
              <>
                <span className="text-muted">
                  Limit{account.currency ? ` (${account.currency})` : ""}
                </span>
                <span className="text-right font-mono">
                  {fmtUsd(account.limit_usd)}
                </span>
              </>
            )}

            {account.remaining_usd != null && (
              <>
                <span className="text-muted">
                  Remaining{account.currency ? ` (${account.currency})` : ""}
                </span>
                <span
                  className={`text-right font-mono font-semibold ${
                    account.remaining_usd < 5
                      ? "text-red-400"
                      : account.remaining_usd < 20
                        ? "text-yellow-400"
                        : "text-emerald-400"
                  }`}
                >
                  {fmtUsd(account.remaining_usd)}
                </span>
              </>
            )}

            {(account.granted_usd != null || account.topped_up_usd != null) && (
              <>
                <span className="text-muted">Paid</span>
                <span className="text-right font-mono text-fg/80">
                  {fmtUsd(account.topped_up_usd ?? 0)}
                </span>
                <span className="text-muted">Free credit</span>
                <span className="text-right font-mono text-fg/80">
                  {fmtUsd(account.granted_usd ?? 0)}
                </span>
              </>
            )}

            {children}
          </div>
        </>
      )}

      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// OpenRouter card. Inherits the shared body and layers the per-model activity
// table from /api/accounts/activity (admin key required for non-empty rows).
// ---------------------------------------------------------------------------

function OpenRouterActivityTable() {
  const { data: activityData, error: activityError } = useActivity();

  const totalSpend =
    activityData?.items.reduce((s, i) => s + i.cost_usd, 0) ?? null;

  return (
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
          </a>{" "}
          and set OPENROUTER_ADMIN_KEY in cluster secret
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
                <td className="py-1.5 text-right font-mono">
                  {fmtUsd(item.cost_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public component: grid of provider cards.
// ---------------------------------------------------------------------------

export function AccountBalances() {
  const { data, error, isLoading } = useAccountUsage();

  // Account data is private: the web proxy only serves it when
  // EXPOSE_ACCOUNT_DATA=true. Otherwise hide the panel entirely.
  if (isNotExposed(error)) return null;

  return (
    <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
        My API Accounts
      </h2>

      {isLoading && <p className="text-sm text-muted">Loading account data…</p>}
      {error && (
        <p className="text-sm text-red-400">Failed to load: {errMsg(error)}</p>
      )}
      {data && (
        <div className="space-y-4">
          <ProviderCard account={data[PRIMARY]}>
            <OpenRouterActivityTable />
          </ProviderCard>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {REST_ORDER.map((id) => (
              <ProviderCard key={id} account={data[id]} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
