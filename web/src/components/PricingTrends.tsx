"use client";

import { useState } from "react";

import { PriceHistoryChart } from "@/components/PriceHistoryChart";
import { fmtUsd, isNotExposed, useActivity, useHistory, useTopModels } from "@/lib/api";

interface Choice {
  model_id: string;
  cost_usd: number | null;
}

export function PricingTrends() {
  const { data: activity, isLoading: activityLoading, error: activityError } = useActivity();
  const accountDataHidden = isNotExposed(activityError);
  // Without private usage data, chart the current top-ranked models instead.
  const { data: top, isLoading: topLoading } = useTopModels(10);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const usage: Choice[] = (activity?.items ?? []).map((i) => ({
    model_id: i.model_id,
    cost_usd: i.cost_usd,
  }));
  const fromUsage = usage.length > 0;
  const items: Choice[] = fromUsage
    ? usage
    : (top ?? []).map((r) => ({ model_id: r.model.id, cost_usd: null }));
  const isLoading = activityLoading || (!fromUsage && topLoading);
  const modelId = selectedModel ?? items[0]?.model_id ?? null;

  const { data: history } = useHistory(modelId, 30);

  if (!isLoading && items.length === 0)
    return (
      <section className="card rounded-lg p-4 w-full">
        <h2 className="mb-1 text-lg font-semibold">Pricing Trends</h2>
        <p className="text-sm opacity-60">No models with price history yet.</p>
      </section>
    );

  return (
    <section className="card rounded-lg p-4 w-full">
      <h2 className="mb-1 text-lg font-semibold">Pricing Trends</h2>
      <p className="mb-4 text-xs opacity-60">
        {fromUsage
          ? "Price history for models you use via OpenRouter · last 30 days"
          : accountDataHidden
            ? "Price history for the current top-ranked coding models · last 30 days"
            : activityError
              ? "Couldn't load your OpenRouter usage — showing the current top-ranked coding models · last 30 days"
              : "No OpenRouter usage yet — showing the current top-ranked coding models · last 30 days"}
      </p>

      {isLoading && <p className="text-sm opacity-60">Loading…</p>}

      {items.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Select model">
            {items.map((m) => {
              const label = m.model_id.includes("/") ? m.model_id.split("/")[1] : m.model_id;
              const active = modelId === m.model_id;
              return (
                <button
                  key={m.model_id}
                  type="button"
                  onClick={() => setSelectedModel(m.model_id)}
                  aria-pressed={active}
                  className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "bg-blue-600 text-white"
                      : "bg-border text-fg/80 hover:bg-border/70"
                  }`}
                >
                  {label}
                  {m.cost_usd != null && (
                    <span className="ml-2 opacity-70">{fmtUsd(m.cost_usd)}</span>
                  )}
                </button>
              );
            })}
          </div>

          {history && history.length > 1 ? (
            <div className="h-72">
              <PriceHistoryChart history={history} strokeWidth={2} />
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
