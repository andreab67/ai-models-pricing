"use client";

import { useKiloProjection } from "@/lib/api";

interface Props {
  tier: string;
  setTier: (t: string) => void;
  streakMonths: number;
  setStreakMonths: (n: number) => void;
  annual: boolean;
  setAnnual: (a: boolean) => void;
}

export function KiloPassCalculator({
  tier,
  setTier,
  streakMonths,
  setStreakMonths,
  annual,
  setAnnual,
}: Props) {
  const { data, isLoading, error } = useKiloProjection(tier, streakMonths, annual);

  return (
    <div className="card rounded-lg p-4">
      <h3 className="mb-3 text-sm font-semibold tracking-wide uppercase opacity-70">
        Kilo Pass assumptions
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="text-sm">
          Tier
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="mt-1 block w-full rounded border bg-transparent p-1 text-sm"
            style={{ borderColor: "rgb(var(--border))" }}
          >
            <option value="starter">Starter ($19/mo)</option>
            <option value="pro">Pro ($49/mo)</option>
            <option value="expert">Expert ($199/mo)</option>
          </select>
        </label>
        <label className="text-sm">
          Streak (months)
          <input
            type="number"
            value={streakMonths}
            min={1}
            max={120}
            onChange={(e) => setStreakMonths(parseInt(e.target.value || "1", 10))}
            disabled={annual}
            className="mt-1 block w-full rounded border bg-transparent p-1 text-sm disabled:opacity-50"
            style={{ borderColor: "rgb(var(--border))" }}
          />
        </label>
        <label className="flex items-end gap-2 text-sm">
          <input
            type="checkbox"
            checked={annual}
            onChange={(e) => setAnnual(e.target.checked)}
          />
          Annual plan (flat 50% bonus)
        </label>
      </div>

      <div className="mt-3 text-sm">
        {isLoading && <span className="opacity-60">Loading…</span>}
        {error && <span className="text-red-500">Error: {String(error)}</span>}
        {data && (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Paid credits" value={`$${data.paid_credits_usd.toFixed(2)}`} />
            <Stat label="Bonus %" value={`${(data.bonus_pct * 100).toFixed(1)}%`} />
            <Stat
              label="Bonus credits"
              value={`$${data.bonus_credits_usd.toFixed(2)}`}
            />
            <Stat
              label="Effective"
              value={`$${data.total_effective_credits_usd.toFixed(2)}`}
              highlight
            />
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className="rounded border px-2 py-1"
      style={{
        borderColor: "rgb(var(--border))",
        background: highlight ? "rgba(34,197,94,0.08)" : undefined,
      }}
    >
      <div className="text-xs opacity-60">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}
