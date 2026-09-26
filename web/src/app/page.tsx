"use client";

import { useState } from "react";

import { AccountBalances } from "@/components/AccountBalances";
import { KiloPassCalculator } from "@/components/KiloPassCalculator";
import { ModelDetailModal } from "@/components/ModelDetailModal";
import { TopTenRanking } from "@/components/TopTenRanking";

export default function DashboardPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [tier, setTier] = useState("starter");
  // Start at the steady-state streak (the month the bonus reaches its 40% cap
  // in kilo_plans.yaml). Month 1 is a one-off 50% welcome bonus and would
  // overstate the recurring Kilo Pass discount; users can still pick it.
  const [streakMonths, setStreakMonths] = useState(8);
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
