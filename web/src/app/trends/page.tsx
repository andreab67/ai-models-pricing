"use client";

import { useState } from "react";

import { ModelDetailModal } from "@/components/ModelDetailModal";
import { ModelTable } from "@/components/ModelTable";

export default function AllModelsPage() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <ModelTable onSelect={setSelected} />
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
