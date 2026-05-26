"use client";

import { useState } from "react";

import { AccountBalances } from "@/components/AccountBalances";
import { KiloPassCalculator } from "@/components/KiloPassCalculator";
import { ModelDetailModal } from "@/components/ModelDetailModal";
import { ModelTable } from "@/components/ModelTable";
import { PricingTrends } from "@/components/PricingTrends";
import { TopTenRanking } from "@/components/TopTenRanking";

export default function DashboardPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [tier, setTier] = useState("starter");
  const [streakMonths, setStreakMonths] = useState(1);
  const [annual, setAnnual] = useState(false);

  return (
    <div className="space-y-6">
      <AccountBalances />
      <KiloPassCalculator
        tier={tier}
        setTier={setTier}
        streakMonths={streakMonths}
        setStreakMonths={setStreakMonths}
        annual={annual}
        setAnnual={setAnnual}
      />
      <TopTenRanking onSelect={setSelected} />
      <PricingTrends />
      <ModelTable onSelect={setSelected} />
      <ModelDetailModal
        modelId={selected}
        onClose={() => setSelected(null)}
        kiloTier={tier}
        kiloStreakMonths={streakMonths}
        kiloAnnual={annual}
      />
    </div>
  );
}
