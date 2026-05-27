"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fmtUsd, useActivity, useComparison, useHistory } from "@/lib/api";

const CHANNEL_LABEL: Record<string, string> = {
  openrouter_payg: "OpenRouter PAYG",
  openrouter_byok: "OpenRouter BYOK",
  kilo_pass: "Kilo Pass",
  kilo_byok: "Kilo BYOK",
};

const CHART_BLUE = "#3b82f6";
const CHART_GREEN = "#22c55e";

interface Props {
  modelId: string | null;
  onClose: () => void;
  kiloTier: string;
  kiloStreakMonths: number;
  kiloAnnual: boolean;
}

export function ModelDetailModal({
  modelId,
  onClose,
  kiloTier,
  kiloStreakMonths,
  kiloAnnual,
}: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const { data: comparison, isLoading } = useComparison(
    modelId,
    kiloTier,
    kiloStreakMonths,
    kiloAnnual,
  );
  const { data: history } = useHistory(modelId, 30);
  const { data: activity } = useActivity();
  const myUsage = activity?.items.find((i) => i.model_id === modelId);

  // Focus close button when modal opens; restore focus on close
  useEffect(() => {
    if (!modelId) return;
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => prev?.focus();
  }, [modelId]);

  // Escape + focus trap
  useEffect(() => {
    if (!modelId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modelId, onClose]);

  if (!modelId) return null;

  const chartData =
    comparison?.channels.map((c) => ({
      channel: CHANNEL_LABEL[c.channel] ?? c.channel,
      input: c.prompt_usd_per_mtok,
      output: c.completion_usd_per_mtok,
    })) ?? [];

  const isFreeModel = chartData.length > 0 && chartData.every((d) => d.input === 0 && d.output === 0);

  const fmtTokens = (n: number | null | undefined) =>
    n ? n.toLocaleString() : "—";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="card max-h-[90vh] w-full max-w-3xl overflow-auto rounded-lg p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <h2 id="modal-title" className="text-lg font-semibold">
              {comparison?.model.name ?? modelId}
            </h2>
            <p className="font-mono text-xs opacity-60">{modelId}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-black/10 dark:hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {isLoading && <p className="text-sm opacity-60">Loading…</p>}

        {comparison && (
          <>
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <Meta label="Context" value={fmtTokens(comparison.model.context_length)} />
              <Meta label="Max out" value={fmtTokens(comparison.model.max_completion_tokens)} />
              <Meta label="Tools" value={comparison.model.supports_tools ? "yes" : "no"} />
              <Meta label="Vision" value={comparison.model.supports_vision ? "yes" : "no"} />
            </div>

            {myUsage && (
              <>
                <h3 className="mt-4 mb-2 text-sm font-semibold uppercase opacity-70">
                  Your usage (last 30 days)
                </h3>
                <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                  <Meta label="Spent" value={fmtUsd(myUsage.cost_usd)} />
                  <Meta label="Requests" value={myUsage.requests.toLocaleString()} />
                  <Meta label="In tokens" value={`${(myUsage.prompt_tokens / 1000).toFixed(1)}k`} />
                  <Meta label="Out tokens" value={`${(myUsage.completion_tokens / 1000).toFixed(1)}k`} />
                </div>
              </>
            )}

            <h3 className="mt-4 mb-2 text-sm font-semibold uppercase opacity-70">
              Channel comparison
            </h3>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-2 py-1 text-left">Channel</th>
                    <th className="px-2 py-1 text-right">In $/Mtok</th>
                    <th className="px-2 py-1 text-right">Out $/Mtok</th>
                    <th className="px-2 py-1 text-left">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.channels.map((c) => (
                    <tr key={c.channel} className="border-b border-border">
                      <td className="px-2 py-1">{CHANNEL_LABEL[c.channel]}</td>
                      <td className="px-2 py-1 text-right font-mono">
                        {fmtUsd(c.prompt_usd_per_mtok)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">
                        {fmtUsd(c.completion_usd_per_mtok)}
                      </td>
                      <td className="px-2 py-1 text-xs opacity-70">{c.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!isFreeModel && (
              <div className="mt-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
                    <XAxis dataKey="channel" stroke="rgb(var(--muted))" fontSize={11} />
                    <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                    <Tooltip
                      contentStyle={{
                        background: "rgb(var(--card))",
                        border: "1px solid rgb(var(--border))",
                        color: "rgb(var(--fg))",
                      }}
                    />
                    <Legend />
                    <Bar dataKey="input" name="In $/Mtok" fill={CHART_BLUE} />
                    <Bar dataKey="output" name="Out $/Mtok" fill={CHART_GREEN} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {history && history.length > 1 && (
              <>
                <h3 className="mt-4 mb-2 text-sm font-semibold uppercase opacity-70">
                  30-day price history ({history.length} snapshots)
                </h3>
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={history.map((h, i) => ({
                        date: `${i === 0 ? "Start" : i === history.length - 1 ? "Now" : ""}`,
                        input: h.prompt_usd_per_mtok,
                        output: h.completion_usd_per_mtok,
                      }))}
                    >
                      <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="date"
                        stroke="rgb(var(--muted))"
                        fontSize={11}
                        allowDuplicatedCategory={false}
                      />
                      <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                      <Tooltip
                        contentStyle={{
                          background: "rgb(var(--card))",
                          border: "1px solid rgb(var(--border))",
                          color: "rgb(var(--fg))",
                        }}
                        formatter={(v: number) => fmtUsd(v)}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line
                        type="monotone"
                        dataKey="input"
                        name="In $/Mtok"
                        stroke={CHART_BLUE}
                        dot={false}
                        strokeWidth={1.5}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="output"
                        name="Out $/Mtok"
                        stroke={CHART_GREEN}
                        dot={false}
                        strokeWidth={1.5}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border px-2 py-1">
      <div className="text-xs opacity-60">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}
