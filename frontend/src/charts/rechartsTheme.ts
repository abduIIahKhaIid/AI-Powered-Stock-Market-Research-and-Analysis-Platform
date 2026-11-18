/** Shared Recharts styling: tooltip card, axis ticks and the entry animation. */
import type { CSSProperties } from "react";
import { chartPalette } from "./theme";

export const TOOLTIP_STYLE: CSSProperties = {
  background: "var(--popover)",
  color: "var(--popover-foreground)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  boxShadow: "0 8px 24px rgb(0 0 0 / 0.12)",
  fontSize: 12,
  padding: "8px 10px",
};

export function axisStyle(theme: "light" | "dark") {
  const colors = chartPalette(theme);
  return {
    grid: colors.grid,
    tick: { fontSize: 11, fill: colors.text },
    cursor: { fill: theme === "dark" ? "rgb(255 255 255 / 0.04)" : "rgb(0 0 0 / 0.035)" },
  };
}

/** Props that make a Recharts series grow in; `order` staggers series one after another. */
export function entry(animate: boolean, order = 0) {
  return {
    isAnimationActive: animate,
    animationBegin: order * 180,
    animationDuration: 1100,
    animationEasing: "ease-out" as const,
  };
}
