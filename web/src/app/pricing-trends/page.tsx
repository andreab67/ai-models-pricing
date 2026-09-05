"use client";

import { KiloPassCalculator } from "@/components/KiloPassCalculator";
import { PricingTrends } from "@/components/PricingTrends";

export default function PricingTrendsPage() {
  return (
    <div className="space-y-6">
      <KiloPassCalculator />
      <PricingTrends />
    </div>
  );
}
