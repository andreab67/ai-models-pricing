"use client";

import { useState } from "react";

import { AccountBalances } from "@/components/AccountBalances";
import { ModelDetailModal } from "@/components/ModelDetailModal";
import { TopTenRanking } from "@/components/TopTenRanking";

export default function DashboardPage() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <AccountBalances />
      <TopTenRanking onSelect={setSelected} />
      {/* Kilo assumptions omitted: the API uses KILO_TIER at the steady-state streak. */}
      <ModelDetailModal modelId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
