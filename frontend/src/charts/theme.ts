/** Concrete colors for the canvas charts (Lightweight Charts cannot read CSS variables). */
export interface ChartPalette {
  up: string;
  down: string;
  volumeUp: string;
  volumeDown: string;
  sma20: string;
  sma50: string;
  band: string;
  rsi: string;
  macd: string;
  signal: string;
  grid: string;
  text: string;
  crosshair: string;
}

const LIGHT: ChartPalette = {
  up: "#10b981",
  down: "#ef4444",
  volumeUp: "rgba(16, 185, 129, 0.32)",
  volumeDown: "rgba(239, 68, 68, 0.32)",
  sma20: "#6366f1",
  sma50: "#a855f7",
  band: "#94a3b8",
  rsi: "#8b5cf6",
  macd: "#6366f1",
  signal: "#f59e0b",
  grid: "#eef0f4",
  text: "#6b7280",
  crosshair: "#9ca3af",
};

const DARK: ChartPalette = {
  ...LIGHT,
  up: "#34d399",
  down: "#f87171",
  volumeUp: "rgba(52, 211, 153, 0.3)",
  volumeDown: "rgba(248, 113, 113, 0.3)",
  sma20: "#818cf8",
  sma50: "#c084fc",
  band: "#64748b",
  macd: "#818cf8",
  grid: "#262a35",
  text: "#9ca3af",
  crosshair: "#6b7280",
};

export function chartPalette(theme: "light" | "dark"): ChartPalette {
  return theme === "dark" ? DARK : LIGHT;
}

/** Ease-out cubic: quick start, gentle landing. */
export function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3;
}
