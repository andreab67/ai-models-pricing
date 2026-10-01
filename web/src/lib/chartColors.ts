// Blue has no app-defined semantic token (only a coincidental match with
// Tailwind's default blue-500), so it stays a plain hex constant.
export const CHART_BLUE = "#3b82f6";

// Green must track the --accent design token (globals.css) rather than
// hardcode its current value, so it stays in sync with the rest of the UI
// (TopTenRanking, ModelTable, etc.) if --accent is ever
// re-themed — same rgb(var(--...)) pattern already used for grid/axis colors
// in the charts that consume this constant.
export const CHART_GREEN = "rgb(var(--accent))";
