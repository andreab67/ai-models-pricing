"use client";

import {
  errMsg,
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
  alibaba: {
    label: "Alibaba DashScope",
    accent: "text-amber-400",
    description: "Alibaba Bailian / DashScope key check",
  },
  anthropic: {
    label: "Anthropic",
    accent: "text-orange-400",
    description: "Anthropic org billing balance",
  },
  openai: {
    label: "OpenAI",
    accent: "text-emerald-400",
    description: "OpenAI credit-grant window",
  },
  deepseek: {
    label: "DeepSeek",
    accent: "text-sky-400",
    description: "DeepSeek user balance (USD)",
  },
  cursor: {
    label: "Cursor",
    accent: "text-fuchsia-400",
    description: "Cursor IDE usage (deep-link to console)",
  },
};

// OpenRouter sits alone at the top because it's the only provider whose card
// carries a per-model activity subtable — that table reads horizontally and
// doesn't fit cleanly inside a 1/3-width column. The remaining seven
// providers share the same compact status grid below.
const PRIMARY: ProviderId = "openrouter";
const REST_ORDER: ProviderId[] = [
  "minimax",
  "kilo",
  "alibaba",
  "anthropic",
  "openai",
  "deepseek",
  "cursor",
];

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
        <div className="space-y-1">
          <p className="text-xs text-muted">
            Key not configured —{" "}
            <span className="text-fg/70">
              set the matching API key in the cluster secret
            </span>
          </p>
          {account.dashboard_url && (
            <a
              href={account.dashboard_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:underline"
            >
              Open console →
            </a>
          )}
        </div>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : account.spent_usd == null && account.remaining_usd == null && account.usage_count == null ? (
        <p className="text-xs text-emerald-400">Key active</p>
      ) : account.usage_count != null || account.usage_limit != null || account.remaining_percent != null ? (
        // Non-USD view: MiniMax returns request counts and a remaining
        // percent per plan window, not dollar amounts.
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

            {account.plan_models && account.plan_models.length > 0 && (
              <>
                <span className="text-muted">Plans</span>
                <span className="text-right text-fg/70 font-mono text-xs">
                  {account.plan_models.join(", ")}
                </span>
              </>
            )}
          </div>

          {account.remaining_percent != null && (
            <p className="text-xs text-right text-muted">
              {account.usage_count != null && account.usage_limit != null
                ? `${account.usage_count.toLocaleString()} of ${account.usage_limit.toLocaleString()} ${account.currency ?? "reqs"} used`
                : `lowest remaining percent across plans`}
            </p>
          )}
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
                <span className="text-muted">Remaining</span>
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
          </div>

          {usedPct != null && (
            <p className={`text-xs text-right ${usedColor}`}>
              {usedPct.toFixed(1)}% used
            </p>
          )}
        </>
      )}

      {account.dashboard_url && account.configured && !account.error && (
        <a
          href={account.dashboard_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-400 hover:underline"
        >
          Open vendor dashboard →
        </a>
      )}

      {children}
    </div>
  );
}

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
