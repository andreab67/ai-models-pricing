"use client";

import { useMemo, useState } from "react";

import { fmtUsd, useModels, type ModelPricing } from "@/lib/api";

type SortKey =
  | "name"
  | "prompt_usd_per_mtok"
  | "completion_usd_per_mtok"
  | "context_length";

interface Props {
  onSelect: (id: string) => void;
}

export function ModelTable({ onSelect }: Props) {
  const { data, isLoading, error } = useModels();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("completion_usd_per_mtok");
  const [asc, setAsc] = useState(true);

  const rows = useMemo<ModelPricing[]>(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? data.filter(
          (m) =>
            m.id.toLowerCase().includes(q) ||
            m.name.toLowerCase().includes(q) ||
            (m.provider ?? "").toLowerCase().includes(q),
        )
      : data;
    const sorted = [...filtered].sort((a, b) => {
      const av = a[sort];
      const bv = b[sort];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [data, query, sort, asc]);

  const toggleSort = (k: SortKey) => {
    if (sort === k) setAsc((v) => !v);
    else {
      setSort(k);
      setAsc(true);
    }
  };

  return (
    <section className="card rounded-lg p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">All models</h2>
        <input
          type="search"
          placeholder="Filter…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-48 rounded border bg-transparent px-2 py-1 text-sm"
          style={{ borderColor: "rgb(var(--border))" }}
        />
      </div>
      {isLoading && <p className="text-sm opacity-60">Loading…</p>}
      {error && <p className="text-sm text-red-500">Failed: {String(error)}</p>}
      {!isLoading && data && (
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="text-left">
              <tr className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
                <Th label="Model" k="name" sort={sort} asc={asc} toggle={toggleSort} />
                <Th
                  label="In $/Mtok"
                  k="prompt_usd_per_mtok"
                  sort={sort}
                  asc={asc}
                  toggle={toggleSort}
                  numeric
                />
                <Th
                  label="Out $/Mtok"
                  k="completion_usd_per_mtok"
                  sort={sort}
                  asc={asc}
                  toggle={toggleSort}
                  numeric
                />
                <Th
                  label="Context"
                  k="context_length"
                  sort={sort}
                  asc={asc}
                  toggle={toggleSort}
                  numeric
                />
                <th className="px-2 py-1 text-right">Tools</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((m) => (
                <tr
                  key={m.id}
                  className="cursor-pointer border-b hover:bg-black/5 dark:hover:bg-white/5"
                  style={{ borderColor: "rgb(var(--border))" }}
                  onClick={() => onSelect(m.id)}
                >
                  <td className="px-2 py-1">
                    <div className="font-medium">{m.name}</div>
                    <div className="font-mono text-xs opacity-60">{m.id}</div>
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {fmtUsd(m.prompt_usd_per_mtok)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {fmtUsd(m.completion_usd_per_mtok)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {(m.context_length ?? 0).toLocaleString()}
                  </td>
                  <td className="px-2 py-1 text-right">
                    {m.supports_tools ? "✓" : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 200 && (
            <p className="mt-2 text-xs opacity-60">
              Showing first 200 of {rows.length}. Refine the filter to narrow.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function Th({
  label,
  k,
  sort,
  asc,
  toggle,
  numeric = false,
}: {
  label: string;
  k: SortKey;
  sort: SortKey;
  asc: boolean;
  toggle: (k: SortKey) => void;
  numeric?: boolean;
}) {
  const active = sort === k;
  return (
    <th
      className={`cursor-pointer px-2 py-1 ${numeric ? "text-right" : ""}`}
      onClick={() => toggle(k)}
    >
      <span className={active ? "font-semibold" : "opacity-70"}>
        {label} {active ? (asc ? "↑" : "↓") : ""}
      </span>
    </th>
  );
}
