"use client";

import { useState } from "react";

import {
  ActivityContractError,
  errMsg,
  fmtCount,
  fmtUsd,
  fmtUsdOrDash,
  isNotExposed,
  useAccountUsage,
  useActivity,
  type AccountProviderUsage,
  type ActivityGroupBy,
  type ActivityPeriod,
  type ActivityPeriodKey,
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
    description: "Kilo Code remaining balance per account",
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

// Color for a remaining USD balance: red under $5, yellow under $20.
function balanceColor(usd: number): string {
  return usd < 5 ? "text-red-400" : usd < 20 ? "text-yellow-400" : "text-emerald-400";
}

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

      {/* `warning` is an alarm state that does NOT invalidate the figures
          below (e.g. DeepSeek balance too low to cover a call). It renders
          above the data so the operator still sees the balance and its
          paid/free split -- exactly when they need it most. `error` is the
          hard failure path and does replace the body. */}
      {account.warning && !account.error && (
        <p className="text-xs text-yellow-400">{account.warning}</p>
      )}

      {!account.configured ? (
        <p className="text-xs text-muted">
          Key not configured —{" "}
          <span className="text-fg/70">
            set the matching API key in the cluster secret
          </span>
        </p>
      ) : account.error ? (
        <p className="text-xs text-red-400">{account.error}</p>
      ) : account.spent_usd == null && account.remaining_usd == null && account.usage_count == null && !account.quota_windows?.length && !account.balances?.length ? (
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

            // limit=0 means the vendor reports no request cap for this
            // window (usage=0 too). Show the percent alone rather than a
            // misleading "0/0".
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
                </span>
              </div>
            );
          })}
        </div>
      ) : account.balances && account.balances.length > 0 ? (
        // Kilo view: one remaining-balance row per account (personal, then
        // each organization) -- what is left to spend, not lifetime totals.
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {account.balances.map((b, i) => (
            <div key={`${b.name}-${i}`} className="contents">
              <span className="text-muted">{b.name}</span>
              <span
                className={`text-right font-mono font-semibold ${balanceColor(b.balance_usd)}`}
              >
                {fmtUsd(b.balance_usd)}
              </span>
            </div>
          ))}
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
            {/* Only render a spend row when the vendor actually exposes a
                spend figure. DeepSeek's /user/balance is a snapshot (total
                already includes granted + topped-up), so no spend can be
                derived -- an unconditional row would render a permanent "—". */}
            {account.spent_usd != null && (
              <>
                <span className="text-muted">
                  {account.period_start
                    ? `Since ${account.period_start.slice(0, 10)}`
                    : "Used"}
                </span>
                <span className="text-right font-mono">
                  {fmtUsd(account.spent_usd)}
                </span>
              </>
            )}

            {account.limit_usd != null && (
              <>
                <span className="text-muted">
                  Limit
                  {account.currency ? ` (${account.currency})` : ""}
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
                  className={`text-right font-mono font-semibold ${balanceColor(account.remaining_usd)}`}
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
          </div>
        </>
      )}

      {/* Extra content (e.g. the OpenRouter per-model table) renders once,
          full-width, below the status grid -- not as a grid cell. */}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// OpenRouter card. Inherits the shared body and layers the per-model activity
// table from /api/accounts/activity (admin key required for non-empty rows).
// ---------------------------------------------------------------------------

const PERIOD_OPTIONS: { key: ActivityPeriodKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
];

const GROUP_OPTIONS: { key: ActivityGroupBy; label: string }[] = [
  { key: "model", label: "Model" },
  { key: "api_key", label: "Key" },
  { key: "app", label: "App" },
];

interface ToggleProps<K extends string> {
  label: string;
  options: { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}

function Toggle<K extends string>({ label, options, value, onChange }: ToggleProps<K>) {
  return (
    <div className="flex gap-1" role="group" aria-label={label}>
      {options.map((o) => {
        const active = o.key === value;

        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange(o.key)}
            aria-pressed={active}
            className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
              active ? "bg-blue-600 text-white" : "bg-border text-fg/80 hover:bg-border/70"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// "YYYY-MM-DD" -> "Oct 14". Split instead of new Date(str): that parses as UTC
// midnight and can render the previous day in a western timezone.
function fmtCalendarDate(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);

  if (!y || !m || !d) return ymd;

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

function fmtPeriodLine(p: ActivityPeriod): string {
  const end = fmtCalendarDate(p.end_date);

  if (p.key === "today") {
    return [`Today, ${end}`, p.partial ? "partial" : null, p.timezone]
      .filter((x) => x !== null)
      .join(" · ");
  }

  const range = `${fmtCalendarDate(p.start_date)} – ${end}`;

  return [range, p.partial ? "today partial" : null, p.timezone]
    .filter((x) => x !== null)
    .join(" · ");
}

function fmtFetchedAt(iso: string, timeZone: string): string | null {
  const d = new Date(iso);

  if (Number.isNaN(d.getTime())) return null;

  try {
    return new Intl.DateTimeFormat("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
    }).format(d);
  } catch {
    // unknown timezone name from the API: omit the time rather than guess one
    return null;
  }
}

function OpenRouterActivityTable() {
  const [period, setPeriod] = useState<ActivityPeriodKey>("today");
  const [groupBy, setGroupBy] = useState<ActivityGroupBy>("model");
  const { data, error } = useActivity(period, groupBy);

  const hasCaller = groupBy !== "model";
  const callerLabel = groupBy === "api_key" ? "Key" : "App";
  const lowerBound = data?.status === "incomplete" ? "≥ " : "";
  const usd = (n: number | null) => (n === null ? "—" : `${lowerBound}${fmtUsd(n)}`);
  const fetchedAt = data ? fmtFetchedAt(data.fetched_at, data.period.timezone) : null;

  return (
    <div className="pt-2 border-t border-border space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted">
          OpenRouter usage
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <Toggle label="Period" options={PERIOD_OPTIONS} value={period} onChange={setPeriod} />
          <Toggle label="Group by" options={GROUP_OPTIONS} value={groupBy} onChange={setGroupBy} />
        </div>
      </div>

      {error instanceof ActivityContractError && (
        <p className="text-xs text-red-400">Activity: unexpected response from API</p>
      )}
      {error && !(error instanceof ActivityContractError) && (
        <p className="text-xs text-red-400">Activity: {errMsg(error)}</p>
      )}
      {!data && !error && <p className="text-xs text-muted">Loading…</p>}

      {data && (
        <p className="text-xs text-muted">
          {fmtPeriodLine(data.period)}
          {fetchedAt !== null && ` · fetched ${fetchedAt}`}
        </p>
      )}

      {data?.status === "unconfigured" && (
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
      {data?.status === "error" && (
        <p className="text-xs text-red-400">Activity: {data.error ?? "unknown error"}</p>
      )}
      {data?.warnings.map((w) => (
        <p key={w} className="text-xs text-yellow-400">
          {w}
        </p>
      ))}
      {data?.truncated === true && (
        <p className="text-xs text-yellow-400">
          Result truncated by OpenRouter — totals are lower bounds
        </p>
      )}

      {data && (data.status === "complete" || data.status === "incomplete") && (
        <>
          <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-xs">
            <dt className="text-muted">OpenRouter credit charges</dt>
            <dd className="text-right font-mono">{usd(data.totals.credits_usd)}</dd>
            <dt className="text-muted">Upstream BYOK usage</dt>
            <dd className="text-right font-mono">{usd(data.totals.byok_usd)}</dd>
            <dt className="text-muted">Combined usage</dt>
            <dd className="text-right font-mono">{usd(data.totals.combined_usd)}</dd>
          </dl>

          {data.items.length === 0 && data.status === "complete" && (
            <p className="text-xs text-muted/60">No OpenRouter usage in this period.</p>
          )}
          {data.items.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted border-b border-border">
                  <th className="text-left font-normal pb-1.5">Model</th>
                  {hasCaller && <th className="text-left font-normal pb-1.5">{callerLabel}</th>}
                  <th className="text-right font-normal pb-1.5">Requests</th>
                  <th className="text-right font-normal pb-1.5">In tok</th>
                  <th className="text-right font-normal pb-1.5">Out tok</th>
                  <th className="text-right font-normal pb-1.5">Credits</th>
                  <th className="text-right font-normal pb-1.5">BYOK</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr
                    key={`${item.model_id}\u0000${item.caller ?? ""}`}
                    className="border-b border-border/40 last:border-0"
                  >
                    <td className="py-1.5 font-mono text-fg/80">{item.model_id}</td>
                    {hasCaller && (
                      <td
                        className="py-1.5 text-fg/80"
                        title={item.caller === null ? "No key/app reported by OpenRouter" : undefined}
                      >
                        {item.caller ?? "—"}
                      </td>
                    )}
                    <td className="py-1.5 text-right font-mono">{fmtCount(item.requests)}</td>
                    <td className="py-1.5 text-right font-mono">{fmtCount(item.prompt_tokens)}</td>
                    <td className="py-1.5 text-right font-mono">
                      {fmtCount(item.completion_tokens)}
                    </td>
                    <td className="py-1.5 text-right font-mono">{fmtUsdOrDash(item.credits_usd)}</td>
                    <td className="py-1.5 text-right font-mono">{fmtUsdOrDash(item.byok_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-[10px] text-muted/60">
            BYOK usage is billed by the upstream provider, not OpenRouter, and provider credits
            may cover it (e.g. the Claude Max 5x $100/mo API credit on the linked Anthropic
            Console org covers eligible Anthropic API usage; it does not cover OpenAI
            embeddings). BYOK fees, when charged, are already included in credit charges.
          </p>
        </>
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
