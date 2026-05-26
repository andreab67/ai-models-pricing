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

import { useActivity, useHistory, useTopModels } from "@/lib/api";

export default function TrendsPage() {
  const { data: top } = useTopModels(10);
  const { data: activity } = useActivity();
  const [modelId, setModelId] = useState<string | null>(null);
  const { data: history } = useHistory(modelId, 90);

  // Merge Top 10 + user's activity models into one deduplicated list
  const topIds = new Set(top?.map((r) => r.model.id) ?? []);
  const activityModels = activity?.items.map((i) => ({ id: i.model_id, name: i.model_id.split("/")[1] ?? i.model_id })) ?? [];
  const topModels = top?.map((r) => ({ id: r.model.id, name: r.model.name })) ?? [];
  const allModels = [
    ...topModels,
    ...activityModels.filter((m) => !topIds.has(m.id)),
  ];

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
            className="ml-2 rounded border border-border bg-[rgb(var(--card))] text-[rgb(var(--fg))] p-1 text-sm"
          >
            <option value="">Select…</option>
            {allModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
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
