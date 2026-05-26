"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useHistory, useTopModels } from "@/lib/api";

export default function TrendsPage() {
  const { data: top } = useTopModels(10);
  const [modelId, setModelId] = useState<string | null>(null);
  const { data: history } = useHistory(modelId, 90);

  const chartData =
    history?.map((s) => ({
      ts: new Date(s.captured_at).toLocaleDateString(),
      input: s.prompt_usd_per_mtok,
      output: s.completion_usd_per_mtok,
    })) ?? [];

  return (
    <div className="space-y-6">
      <section className="card rounded-lg p-4">
        <h2 className="mb-3 text-lg font-semibold">Pricing trends</h2>
        <label className="text-sm">
          Model
          <select
            value={modelId ?? ""}
            onChange={(e) => setModelId(e.target.value || null)}
            className="ml-2 rounded border border-border bg-transparent p-1 text-sm"
          >
            <option value="">Select…</option>
            {top?.map((r) => (
              <option key={r.model.id} value={r.model.id}>
                {r.model.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      {modelId && (
        <section className="card h-96 rounded-lg p-4">
          {chartData.length === 0 ? (
            <p className="text-sm opacity-60">
              No history yet for {modelId} — wait for the next CronJob tick.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
                <XAxis dataKey="ts" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "rgb(var(--card))",
                    border: "1px solid rgb(var(--border))",
                    color: "rgb(var(--fg))",
                  }}
                />
                <Line type="monotone" dataKey="input" stroke="#3b82f6" dot={false} />
                <Line type="monotone" dataKey="output" stroke="#22c55e" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>
      )}
    </div>
  );
}
