"use client";

import { useState } from "react";
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

import { fmtUsd, useActivity, useHistory } from "@/lib/api";

export function PricingTrends() {
  const { data: activity, isLoading } = useActivity();
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const items = activity?.items ?? [];
  const modelId = selectedModel ?? items[0]?.model_id ?? null;

  const { data: history } = useHistory(modelId, 30);

  if (!isLoading && items.length === 0) return null;

  const chartData =
    history?.map((h) => ({
      date: new Date(h.captured_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      input: h.prompt_usd_per_mtok,
      output: h.completion_usd_per_mtok,
    })) ?? [];

  const activeId = modelId;

  return (
    <section className="card rounded-lg p-4 w-full">
      <h2 className="mb-1 text-lg font-semibold">Pricing Trends</h2>
      <p className="mb-4 text-xs opacity-60">
        Price history for models you use via OpenRouter · last 30 days
      </p>

      {isLoading && <p className="text-sm opacity-60">Loading activity…</p>}

      {items.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {items.map((m) => {
              const label = m.model_id.includes("/")
                ? m.model_id.split("/")[1]
                : m.model_id;
              const active = (activeId === m.model_id);
              return (
                <button
                  key={m.model_id}
                  type="button"
                  onClick={() => setSelectedModel(m.model_id)}
                  className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "bg-blue-600 text-white"
                      : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                  }`}
                >
                  {label}
                  <span className="ml-2 opacity-70">{fmtUsd(m.cost_usd)}</span>
                </button>
              );
            })}
          </div>

          {chartData.length > 1 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="rgb(var(--muted))" fontSize={11} />
                  <YAxis
                    stroke="rgb(var(--muted))"
                    fontSize={11}
                    tickFormatter={(v: number) => `$${v}`}
                  />
                  <Tooltip
                    formatter={(v: number) => fmtUsd(v)}
                    contentStyle={{
                      background: "rgb(var(--card))",
                      border: "1px solid rgb(var(--border))",
                      color: "rgb(var(--fg))",
                    }}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="input"
                    name="In $/Mtok"
                    stroke="#3b82f6"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    type="monotone"
                    dataKey="output"
                    name="Out $/Mtok"
                    stroke="#22c55e"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm opacity-60">
              Not enough price history yet for this model — check back tomorrow.
            </p>
          )}
        </>
      )}
    </section>
  );
}
