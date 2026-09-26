"use client";

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
import { CHART_BLUE, CHART_GREEN } from "@/lib/chartTheme";

const fmtDay = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });

const fmtStamp = (t: number) =>
  new Date(t).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/**
 * Input/output price over time on a numeric time axis. Snapshots are hourly,
 * so a category axis either repeats day labels or collapses points; a time
 * scale keeps every point at its real position.
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
  const data = history
    .map((h) => ({
      t: new Date(h.captured_at).getTime(),
      input: h.prompt_usd_per_mtok,
      output: h.completion_usd_per_mtok,
    }))
    .filter((d) => Number.isFinite(d.t))
    .sort((a, b) => a.t - b.t);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={fmtDay}
          stroke="rgb(var(--muted))"
          fontSize={11}
        />
        <YAxis
          stroke="rgb(var(--muted))"
          fontSize={11}
          tickFormatter={(v: number) => fmtUsd(v)}
        />
        <Tooltip
          labelFormatter={(t) => fmtStamp(Number(t))}
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
