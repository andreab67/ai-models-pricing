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
      <ModelDetailModal
        modelId={selected}
        onClose={() => setSelected(null)}
        kiloTier="starter"
        kiloStreakMonths={1}
        kiloAnnual={false}
      />
    </div>
  );
}
