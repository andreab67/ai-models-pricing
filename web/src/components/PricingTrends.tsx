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

import { fmtUsd, useHistory, useTopModels } from "@/lib/api";
import { CHART_BLUE, CHART_GREEN } from "@/lib/chartColors";

export function PricingTrends() {
  const { data: ranked, isLoading } = useTopModels(10);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const models = ranked ?? [];
  const modelId = selectedModel ?? models[0]?.model.id ?? null;

  const { data: history } = useHistory(modelId, 30);

  const chartData =
    history?.map((h) => ({
      date: new Date(h.captured_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      input: h.prompt_usd_per_mtok,
      output: h.completion_usd_per_mtok,
    })) ?? [];

  return (
    <section className="card rounded-lg p-4 w-full">
      <h2 className="mb-1 text-lg font-semibold">Pricing Trends</h2>
      <p className="mb-4 text-xs opacity-60">
        Price history for the top coding models · last 30 days
      </p>

      {isLoading && <p className="text-sm opacity-60">Loading models…</p>}

      {models.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Select model">
            {models.map((r) => {
              const active = modelId === r.model.id;
              return (
                <button
                  key={r.model.id}
                  type="button"
                  onClick={() => setSelectedModel(r.model.id)}
                  className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "bg-blue-600 text-white"
                      : "bg-border text-fg/80 hover:bg-border/70"
                  }`}
                >
                  {r.model.name}
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
                    stroke={CHART_BLUE}
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    type="monotone"
                    dataKey="output"
                    name="Out $/Mtok"
                    stroke={CHART_GREEN}
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
