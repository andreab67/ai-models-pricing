"use client";

import { fmtUsd, useTopModels } from "@/lib/api";

interface Props {
  onSelect: (modelId: string) => void;
}

export function TopTenRanking({ onSelect }: Props) {
  const { data, isLoading, error } = useTopModels(10);

  return (
    <section className="card rounded-lg p-4">
      <h2 className="mb-3 text-lg font-semibold">Top 10 coding models</h2>
      <p className="mb-3 text-xs opacity-60">
        Ranked by blended cost (30% input / 70% output) with tool support and
        ≥64k context.
      </p>
      {isLoading && <p className="text-sm opacity-60">Loading…</p>}
      {error && <p className="text-sm text-red-500">Failed to load: {String(error)}</p>}
      {data && (
        <ol className="space-y-1">
          {data.map((r) => (
            <li key={r.model.id}>
              <button
                type="button"
                onClick={() => onSelect(r.model.id)}
                className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-black/5 dark:hover:bg-white/5"
              >
                <span className="flex items-center gap-2">
                  <span className="w-6 font-mono text-xs opacity-60">
                    #{r.rank}
                  </span>
                  <span className="font-medium">{r.model.name}</span>
                </span>
                <span className="font-mono text-xs opacity-70">
                  {fmtUsd(r.blended_usd_per_mtok)}/Mtok
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
