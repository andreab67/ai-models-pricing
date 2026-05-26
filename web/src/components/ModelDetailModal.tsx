"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fmtUsd, useComparison, useHistory } from "@/lib/api";

const CHANNEL_LABEL: Record<string, string> = {
  openrouter_payg: "OpenRouter PAYG",
  openrouter_byok: "OpenRouter BYOK",
  kilo_pass: "Kilo Pass",
  kilo_byok: "Kilo BYOK",
};

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
  const { data: comparison, isLoading } = useComparison(
    modelId,
    kiloTier,
    kiloStreakMonths,
    kiloAnnual,
  );
  const { data: history } = useHistory(modelId, 30);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!modelId) return null;

  const chartData =
    comparison?.channels.map((c) => ({
      channel: CHANNEL_LABEL[c.channel] ?? c.channel,
      input: c.prompt_usd_per_mtok,
      output: c.completion_usd_per_mtok,
    })) ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="card max-h-[90vh] w-full max-w-3xl overflow-auto rounded-lg p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">
              {comparison?.model.name ?? modelId}
            </h2>
            <p className="font-mono text-xs opacity-60">{modelId}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-black/10 dark:hover:bg-white/10"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {isLoading && <p className="text-sm opacity-60">Loading…</p>}

        {comparison && (
          <>
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <Meta
                label="Context"
                value={(comparison.model.context_length ?? 0).toLocaleString()}
              />
              <Meta
                label="Max out"
                value={(comparison.model.max_completion_tokens ?? 0).toLocaleString()}
              />
              <Meta label="Tools" value={comparison.model.supports_tools ? "yes" : "no"} />
              <Meta label="Vision" value={comparison.model.supports_vision ? "yes" : "no"} />
            </div>

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
                    <tr
                      key={c.channel}
                      className="border-b border-border"
                    >
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
                  <Bar dataKey="input" name="In $/Mtok" fill="#3b82f6" />
                  <Bar dataKey="output" name="Out $/Mtok" fill="#22c55e" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {history && history.length > 1 && (
              <p className="mt-3 text-xs opacity-60">
                {history.length} historical snapshots in the last 30 days · oldest{" "}
                {new Date(history[0].captured_at).toLocaleDateString()} · newest{" "}
                {new Date(history[history.length - 1].captured_at).toLocaleDateString()}
              </p>
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
