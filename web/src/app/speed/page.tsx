import { SpeedDashboard } from "@/components/SpeedDashboard";

export const metadata = {
  title: "Speed — andrea-house",
  description: "Real-time free-model speed benchmark across Kilo and OpenRouter",
};

export default function SpeedPage() {
  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">model-speed</h1>
        <p className="mt-1 text-sm text-muted">
          Fastest free model · Kilo × OpenRouter · auto-refresh 60 s · chain feeds hermes-vps
        </p>
      </div>
      <SpeedDashboard />
    </>
  );
}
