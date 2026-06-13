"use client";

import {
  fmtLatency,
  fmtSpeed,
  useSpeedLatest,
  useSpeedRuns,
  type Gateway,
  type ProbeStatus,
  type SpeedProbeResult,
} from "@/lib/api";

function GwBadge({ gw }: { gw: Gateway }) {
  if (gw === "kilo") {
    return (
      <span className="inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-purple-700 text-white mr-1.5">
        KILO
      </span>
    );
  }
  return (
    <span className="inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-sky-600 text-white mr-1.5">
      OPENROUTER
    </span>
  );
}

function StatusCell({ status, error }: { status: ProbeStatus; error: string | null }) {
  const cls =
    status === "ok"
      ? "text-green-400"
      : status === "throttled"
        ? "text-yellow-400"
        : "text-red-400";
  return (
    <span className={cls} title={error ?? undefined}>
      {status}
    </span>
  );
}

function Delta({ d }: { d: number | null }) {
  if (d == null) return <span className="opacity-50">—</span>;
  const cls = d >= 0 ? "text-green-400" : "text-red-400";
  return (
    <span className={cls}>
      {d >= 0 ? "+" : ""}
      {Math.round(d)}
    </span>
  );
}

function sortResults(results: SpeedProbeResult[]): SpeedProbeResult[] {
  return [...results].sort((a, b) => {
    if (a.score_ms != null && b.score_ms != null) return a.score_ms - b.score_ms;
    if (a.score_ms != null) return -1;
    if (b.score_ms != null) return 1;
    return 0;
  });
}

export function SpeedDashboard() {
  const { data: snap, isLoading, error } = useSpeedLatest();
  const { data: runs } = useSpeedRuns(10);

  if (isLoading) return <p className="text-sm opacity-60">Loading…</p>;
  if (error) {
    return (
      <div className="border-l-4 border-red-500 pl-3 py-2 text-sm text-red-400 rounded bg-card">
        No benchmark data yet.{" "}
        <span className="font-mono text-xs">
          kubectl -n model-speed create job --from=cronjob/benchmark benchmark-manual
        </span>
      </div>
    );
  }
  if (!snap) return null;

  const chain = snap.chain && snap.chain.entries.length > 0 ? snap.chain : null;
  const results = sortResults(snap.results);
  const runTs = new Date(snap.generated_at).toLocaleString();

  return (
    <div className="space-y-4">
      {chain ? (
        <section className="card rounded-lg p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">
            Current hermes-vps chain
          </h2>
          <div className="mb-3 flex items-baseline gap-3 flex-wrap">
            <span className="text-xl font-bold">
              <GwBadge gw={chain.entries[0].gateway} />
              {chain.entries[0].model_id}
            </span>
            <span className="text-xs text-muted">
              {chain.entries[0].score_ms.toFixed(0)} ms · TTFT{" "}
              {chain.entries[0].ttft_ms.toFixed(0)} ms ·{" "}
              {Math.round(chain.entries[0].tokens_per_sec)} tok/s
            </span>
          </div>
          <div className="flex flex-wrap gap-2 mb-3">
            {chain.entries.map((e) => (
              <span
                key={`${e.gateway}:${e.model_id}`}
                className="border border-border rounded-full px-3 py-1 text-xs"
              >
                <span className="text-muted mr-1">#{e.rank}</span>
                <GwBadge gw={e.gateway} />
                {e.model_id}
                <span className="text-muted ml-1.5">{e.score_ms.toFixed(0)} ms</span>
              </span>
            ))}
          </div>
          <p className="text-xs text-muted">
            Generated {new Date(chain.generated_at).toLocaleString()} · run #{chain.run_id}
          </p>
        </section>
      ) : (
        <div className="border-l-4 border-yellow-500 pl-3 py-2 text-sm text-yellow-400 rounded bg-card">
          No chain published yet — no reliable models passed the last 3-run reliability gate.
        </div>
      )}

      <section className="card rounded-lg p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">
          Run #{snap.run_id} · {runTs}
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted">
                <th className="pb-2 text-left pr-2 w-16"></th>
                <th className="pb-2 text-left pr-4">Model</th>
                <th className="pb-2 text-left pr-4">Status</th>
                <th className="pb-2 text-right pr-4">TTFT</th>
                <th className="pb-2 text-right pr-4">tok/s</th>
                <th className="pb-2 text-right pr-4">Adv</th>
                <th className="pb-2 text-right pr-4">Δ</th>
                <th className="pb-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="py-1.5 pr-2 whitespace-nowrap">
                    <GwBadge gw={r.gateway} />
                  </td>
                  <td className="py-1.5 pr-4 font-mono text-xs">{r.model_id}</td>
                  <td className="py-1.5 pr-4 text-xs">
                    <StatusCell status={r.status} error={r.error} />
                  </td>
                  <td className="py-1.5 pr-4 text-right font-mono text-xs opacity-70">
                    {fmtLatency(r.ttft_ms)}
                  </td>
                  <td className="py-1.5 pr-4 text-right font-mono text-xs opacity-70">
                    {fmtSpeed(r.tokens_per_sec)}
                  </td>
                  <td className="py-1.5 pr-4 text-right font-mono text-xs opacity-70">
                    {r.advertised_tokens_per_sec != null
                      ? `${Math.round(r.advertised_tokens_per_sec)}`
                      : "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-right font-mono text-xs">
                    <Delta d={r.tokens_per_sec_delta} />
                  </td>
                  <td className="py-1.5 text-right font-mono text-xs font-semibold">
                    {r.score_ms != null ? `${r.score_ms.toFixed(0)} ms` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted">
          Score = TTFT + projected time for 500 output tokens (lower is better). tok/s is measured
          live; Adv is OpenRouter&apos;s advertised throughput; Δ is measured − advertised (green =
          faster than claimed). Models with any failure in the last 3 runs are excluded from the
          chain.
        </p>
      </section>

      {runs && runs.length > 0 && (
        <section className="card rounded-lg p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">
            Recent runs
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted">
                <th className="pb-2 text-left pr-4">Run</th>
                <th className="pb-2 text-left pr-4">Started</th>
                <th className="pb-2 text-right pr-4">OK</th>
                <th className="pb-2 text-right pr-4">Throttled</th>
                <th className="pb-2 text-right">Errors</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="py-1 pr-4 font-mono text-xs">#{r.id}</td>
                  <td className="py-1 pr-4 text-xs opacity-70">
                    {new Date(r.started_at).toLocaleString()}
                  </td>
                  <td className="py-1 pr-4 text-right font-mono text-xs text-green-400">
                    {r.ok_count}
                  </td>
                  <td className="py-1 pr-4 text-right font-mono text-xs text-yellow-400">
                    {r.throttled_count}
                  </td>
                  <td className="py-1 text-right font-mono text-xs text-red-400">
                    {r.error_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
