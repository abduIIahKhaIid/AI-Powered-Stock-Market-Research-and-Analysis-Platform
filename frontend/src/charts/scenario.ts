import type { ScenarioChartSpec } from "../chat/types";

export const CASE_COLORS: Record<string, string> = {
  base: "#0d6e4f",
  bull: "#2563eb",
  bear: "#c0392b",
};
const EXTRA_COLORS = ["#9333ea", "#d97706", "#0e7490", "#be185d", "#4d7c0f"];

export function caseColor(name: string, index: number): string {
  return CASE_COLORS[name] ?? EXTRA_COLORS[index % EXTRA_COLORS.length];
}

/** Rows for the line chart: the base year (actual revenue) and one row per projected year. */
export function scenarioRows(spec: ScenarioChartSpec): Record<string, number>[] {
  const years = new Map<number, Record<string, number>>();
  years.set(spec.base_year, { year: spec.base_year });
  for (const series of spec.series) {
    years.get(spec.base_year)![series.name] = spec.base_value;
    for (const point of series.points) {
      const row = years.get(point.year) ?? { year: point.year };
      row[series.name] = point.value;
      years.set(point.year, row);
    }
  }
  return [...years.values()].sort((a, b) => a.year - b.year);
}

/** 412.5B, 1.2T, 950M */
export function compactUsd(value: number): string {
  const abs = Math.abs(value);
  const [divisor, suffix] =
    abs >= 1e12 ? [1e12, "T"] : abs >= 1e9 ? [1e9, "B"] : abs >= 1e6 ? [1e6, "M"] : [1, ""];
  return `${(value / divisor).toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`;
}

export function signedPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function describeScenario(spec: ScenarioChartSpec): string {
  const name = spec.name ? `${spec.name} (${spec.symbol})` : spec.symbol;
  const last = spec.table[0]?.final_year;
  const cases = spec.table
    .map(
      (row) =>
        `${row.case}: revenue ${compactUsd(row.final_revenue)} USD in ${row.final_year}, ` +
        `value per share ${row.value_per_share.toFixed(2)} USD (${signedPct(row.vs_price_pct)} vs price)`,
    )
    .join("; ");
  return `${name} revenue projection from ${spec.base_year} to ${last}. ${cases}.`;
}
