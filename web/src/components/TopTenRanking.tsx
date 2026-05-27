"use client";

import { fmtUsd, useTopModels } from "@/lib/api";

function fmtCtx(tokens: number | null | undefined): string {
  if (!tokens) return "—";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}k`;
  return String(tokens);
}

interface Props {
  onSelect: (modelId: string) => void;
}

export function TopTenRanking({ onSelect }: Props) {
  const { data, isLoading, error } = useTopModels(10);

  return (
    <section className="card rounded-lg p-4 w-full">
      <h2 className="mb-1 text-lg font-semibold">Top 10 Coding Models (1M+ context)</h2>
      <p className="mb-4 text-xs opacity-60">
        Ranked by blended cost (30% input / 70% output) · tool calling support · ≥1M tokens context window
      </p>
      {isLoading && <p className="text-sm opacity-60">Loading…</p>}
      {error && <p className="text-sm text-red-500">Failed to load: {String(error)}</p>}
      {data && (
        <div className="w-full overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted">
                <th className="pb-2 text-left w-8">#</th>
                <th className="pb-2 text-left">Model</th>
                <th className="pb-2 text-right pr-4">Context</th>
                <th className="pb-2 text-right pr-4">In $/Mtok</th>
                <th className="pb-2 text-right pr-4">Out $/Mtok</th>
                <th className="pb-2 text-right">Blended</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr
                  key={r.model.id}
                  tabIndex={0}
                  onClick={() => onSelect(r.model.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(r.model.id))}
                  className="border-b border-border cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 focus:outline-none focus-visible:bg-accent/10"
                >
                  <td className="py-2 font-mono text-xs opacity-50">#{r.rank}</td>
                  <td className="py-2 font-medium pr-4">{r.model.name}</td>
                  <td className="py-2 text-right pr-4 font-mono text-xs opacity-70">
                    {fmtCtx(r.model.context_length)}
                  </td>
                  <td className="py-2 text-right pr-4 font-mono text-xs opacity-70">
                    {fmtUsd(r.model.prompt_usd_per_mtok)}
                  </td>
                  <td className="py-2 text-right pr-4 font-mono text-xs opacity-70">
                    {fmtUsd(r.model.completion_usd_per_mtok)}
                  </td>
                  <td className="py-2 text-right font-mono text-xs font-semibold">
                    {fmtUsd(r.blended_usd_per_mtok)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
