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
  const [pageSize, setPageSize] = useState<number | null>(25);
  const [page, setPage] = useState(0);

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

  const totalPages = pageSize === null ? 1 : Math.ceil(rows.length / pageSize);
  const visibleRows = pageSize === null ? rows : rows.slice(page * pageSize, (page + 1) * pageSize);

  const toggleSort = (k: SortKey) => {
    if (sort === k) setAsc((v) => !v);
    else {
      setSort(k);
      setAsc(true);
    }
    setPage(0);
  };

  const changePageSize = (v: number | null) => {
    setPageSize(v);
    setPage(0);
  };

  return (
    <section className="card rounded-lg p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">All models</h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 text-xs" role="group" aria-label="Page size">
            {([25, 50, 100, null] as (number | null)[]).map((v) => (
              <button
                key={v ?? "all"}
                type="button"
                onClick={() => changePageSize(v)}
                className={`rounded px-2 py-0.5 ${pageSize === v ? "bg-blue-600 text-white" : "bg-border text-fg/80 hover:bg-border/70"}`}
              >
                {v ?? "All"}
              </button>
            ))}
          </div>
          <input
            type="search"
            placeholder="Filter…"
            aria-label="Filter models"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(0); }}
            className="w-48 rounded border border-border bg-card text-fg px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
        </div>
      </div>
      {isLoading && <p className="text-sm opacity-60">Loading…</p>}
      {error && <p className="text-sm text-red-500">Failed: {String(error)}</p>}
      {!isLoading && data && (
        <div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left">
                <tr className="border-b border-border">
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
                {visibleRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-2 py-6 text-center text-sm text-muted">
                      No models match &ldquo;{query}&rdquo;
                    </td>
                  </tr>
                ) : (
                  visibleRows.map((m) => (
                    <tr
                      key={m.id}
                      tabIndex={0}
                      className="cursor-pointer border-b border-border hover:bg-black/5 dark:hover:bg-white/5 focus:outline-none focus-visible:bg-accent/10"
                      onClick={() => onSelect(m.id)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(m.id))}
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
                        {m.context_length ? m.context_length.toLocaleString() : "—"}
                      </td>
                      <td className="px-2 py-1 text-right">
                        <span aria-label={m.supports_tools ? "Supported" : "Not supported"}>
                          {m.supports_tools ? "✓" : "—"}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {pageSize !== null && totalPages > 1 && (
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>{rows.length} models · page {page + 1} of {totalPages}</span>
              <div className="flex gap-1">
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  className="rounded px-2 py-0.5 bg-border text-fg/80 hover:bg-border/70 disabled:opacity-30"
                >
                  ← Prev
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded px-2 py-0.5 bg-border text-fg/80 hover:bg-border/70 disabled:opacity-30"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
          {pageSize === null && (
            <p className="mt-2 text-xs opacity-60">{rows.length} models</p>
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
