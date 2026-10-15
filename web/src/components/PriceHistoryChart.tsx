"use client";

import { useMemo } from "react";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fmtUsd, type ModelPricing } from "@/lib/api";
import { CHART_BLUE, CHART_GREEN } from "@/lib/chartColors";

const fmtDayLabel = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });

const fmtStamp = (t: number) =>
  new Date(t).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/**
 * Local-date key for a timestamp. Used to bucket hourly snapshots into one
 * point per calendar day. We bucket in the user's local timezone so a snapshot
 * taken at 11pm and one at 1am the next morning land in different days, which
 * matches what the user sees on the X-axis labels.
 */
const localDayKey = (t: number) => {
  const d = new Date(t);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");

  return `${y}-${m}-${day}`;
};

interface DailyPoint {
  day: string;
  t: number;
  input: number;
  output: number;
}

/**
 * Recharts hands the tooltip its callback arguments as untyped `any`. The
 * payload is one of our own `DailyPoint` rows (built by `aggregateByDay`
 * above), so this guard narrows unknown toolt payload back to that shape at
 * the I/O boundary.
 */
function isDailyPoint(value: unknown): value is DailyPoint {
  if (typeof value !== "object" || value === null) return false;

  // SAFETY: recharts Tooltip callback payload is one of our own DailyPoint
  // rows; we widen the access to { t?: unknown } only to read .t for the
  // narrowing check below, never to bypass the type system elsewhere.
  const candidate = value as { t?: unknown };

  return typeof candidate.t === "number";
}

/**
 * Collapse hourly snapshots into one point per local calendar day (the last
 * snapshot of each day). This gives the X axis one unique tick per day, so
 * the chart cannot show duplicate day labels regardless of width.
 */
function aggregateByDay(raw: { t: number; input: number; output: number }[]): DailyPoint[] {
  const lastByDay = new Map<string, DailyPoint>();

  for (const point of raw) {
    const key = localDayKey(point.t);
    const existing = lastByDay.get(key);

    if (!existing || point.t > existing.t) {
      lastByDay.set(key, { day: fmtDayLabel(point.t), t: point.t, input: point.input, output: point.output });
    }
  }

  return Array.from(lastByDay.values()).sort((a, b) => a.t - b.t);
}

/**
 * Input/output price over time. Snapshots are hourly, but the X axis is a
 * category axis of one tick per day — aggregating hourly snapshots into one
 * point per day keeps the labels unique (no duplicate "Sep 17" entries) and
 * the chart honest (a flat price line is flat by day, not by the hour).
 */
export function PriceHistoryChart({
  history,
  strokeWidth = 1.5,
  compact = false,
}: {
  history: ModelPricing[];
  strokeWidth?: number;
  compact?: boolean;
}) {
  const data = useMemo(() => {
    const raw = history
      .map((h) => ({
        t: new Date(h.captured_at).getTime(),
        input: h.prompt_usd_per_mtok,
        output: h.completion_usd_per_mtok,
      }))
      .filter((d) => Number.isFinite(d.t));

    return aggregateByDay(raw);
  }, [history]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
        <XAxis
          dataKey="day"
          stroke="rgb(var(--muted))"
          fontSize={11}
          interval="preserveStartEnd"
          minTickGap={24}
        />
        <YAxis
          stroke="rgb(var(--muted))"
          fontSize={11}
          tickFormatter={(v: number) => fmtUsd(v)}
        />
        <Tooltip
          labelFormatter={(_label, items) => {
            const payload = items?.[0]?.payload;

            return isDailyPoint(payload) ? fmtStamp(payload.t) : "";
          }}
          formatter={(v: number) => fmtUsd(v)}
          contentStyle={{
            background: "rgb(var(--card))",
            border: "1px solid rgb(var(--border))",
            color: "rgb(var(--fg))",
          }}
        />
        <Legend wrapperStyle={compact ? { fontSize: 11 } : undefined} />
        <Line
          type="monotone"
          dataKey="input"
          name="In $/Mtok"
          stroke={CHART_BLUE}
          dot={false}
          strokeWidth={strokeWidth}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="output"
          name="Out $/Mtok"
          stroke={CHART_GREEN}
          dot={false}
          strokeWidth={strokeWidth}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
