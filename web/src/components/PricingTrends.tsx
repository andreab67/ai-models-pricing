"use client";

import { useState } from "react";

import { PriceHistoryChart } from "@/components/PriceHistoryChart";
import { useHistory, useTopModels } from "@/lib/api";

export function PricingTrends() {
  const { data: ranked, isLoading } = useTopModels(10);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const models = ranked ?? [];
  const modelId = selectedModel ?? models[0]?.model.id ?? null;

  const { data: history } = useHistory(modelId, 30);

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
                  aria-pressed={active}
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
