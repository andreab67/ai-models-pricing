import * as vscode from "vscode";

interface ModelPricing {
  id: string;
  name: string;
  prompt_usd_per_mtok: number;
  completion_usd_per_mtok: number;
  context_length: number | null;
}

interface RankedModel {
  model: ModelPricing;
  blended_usd_per_mtok: number;
  rank: number;
}

interface KiloProjection {
  bonus_pct: number;
}

let statusBar: vscode.StatusBarItem;
let timer: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext): void {
  statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  statusBar.command = "modelPricing.open";
  statusBar.text = "$(zap) pricing …";
  statusBar.show();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand("modelPricing.refresh", () => refresh()),
    vscode.commands.registerCommand("modelPricing.open", () => openDashboard()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("modelPricing")) scheduleRefresh();
    }),
  );

  scheduleRefresh();
}

export function deactivate(): void {
  if (timer) clearInterval(timer);
}

function config() {
  return vscode.workspace.getConfiguration("modelPricing");
}

function scheduleRefresh(): void {
  if (timer) clearInterval(timer);
  const seconds = Math.max(30, config().get<number>("refreshSeconds", 300));
  void refresh();
  timer = setInterval(() => void refresh(), seconds * 1000);
}

async function refresh(): Promise<void> {
  const cfg = config();
  const base = cfg.get<string>("apiBaseUrl", "");
  const includeDiscount = cfg.get<boolean>("includeKiloDiscount", true);
  const tier = cfg.get<string>("kiloTier", "pro");
  const streak = cfg.get<number>("kiloStreakMonths", 8);

  if (!base) {
    statusBar.text = "$(warning) no API";
    statusBar.tooltip = "Set modelPricing.apiBaseUrl in settings";
    return;
  }

  try {
    const top = await fetchJson<RankedModel[]>(`${base}/models/top?n=1`);
    if (top.length === 0) {
      statusBar.text = "$(zap) no qualifying model";
      return;
    }
    const r = top[0];
    let blended = r.blended_usd_per_mtok;
    let suffix = "";
    if (includeDiscount) {
      const proj = await fetchJson<KiloProjection>(
        `${base}/kilo/projection?tier=${tier}&streak_months=${streak}&annual=false`,
      );
      const discount = proj.bonus_pct / (1 + proj.bonus_pct);
      blended = blended * (1 - discount);
      suffix = ` (Kilo ${tier} m${streak})`;
    }
    statusBar.text = `$(zap) ${r.model.name}: $${blended.toFixed(3)}/Mtok${suffix}`;
    statusBar.tooltip = [
      `#${r.rank} ${r.model.name}`,
      `id: ${r.model.id}`,
      `input:  $${r.model.prompt_usd_per_mtok.toFixed(3)}/Mtok`,
      `output: $${r.model.completion_usd_per_mtok.toFixed(3)}/Mtok`,
      `context: ${(r.model.context_length ?? 0).toLocaleString()}`,
      `click to open dashboard`,
    ].join("\n");
  } catch (err: unknown) {
    statusBar.text = "$(error) pricing offline";
    statusBar.tooltip = err instanceof Error ? err.message : String(err);
  }
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    throw new Error(`${url} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

function openDashboard(): void {
  const base = config().get<string>("apiBaseUrl", "");
  const dashboard = base.replace(/\/api\/?$/, "") || "https://models.andrea-house.com";
  void vscode.env.openExternal(vscode.Uri.parse(dashboard));
}
