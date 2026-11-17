import type { ComparisonMetric, FundamentalsRow, FundamentalsSpec } from "../chat/types";
import { compactUsd } from "./scenario";

export type FundamentalsView = "income" | "eps" | "margins";

export const VIEWS: { key: FundamentalsView; label: string }[] = [
  { key: "income", label: "Revenue & net income" },
  { key: "eps", label: "EPS" },
  { key: "margins", label: "Margins" },
];

const has = (rows: FundamentalsRow[], keys: (keyof FundamentalsRow)[]) =>
  rows.some((row) => keys.some((key) => typeof row[key] === "number"));

export function availableViews(spec: FundamentalsSpec): FundamentalsView[] {
  const views: FundamentalsView[] = [];
  if (has(spec.rows, ["revenue", "net_income"])) views.push("income");
  if (has(spec.rows, ["eps_diluted"])) views.push("eps");
  if (has(spec.rows, ["gross_margin", "operating_margin", "net_margin"])) views.push("margins");
  return views;
}

/** "FY2025" for annual periods, "2025-06" for quarters. */
export function periodLabel(end: string, freq: string): string {
  return freq === "annual" ? `FY${end.slice(0, 4)}` : end.slice(0, 7);
}

export function describeFundamentals(spec: FundamentalsSpec): string {
  const name = spec.name ? `${spec.name} (${spec.symbol})` : spec.symbol;
  const parts = spec.rows.map((row) => {
    const bits = [
      row.revenue != null ? `revenue ${compactUsd(row.revenue)} USD` : null,
      row.net_income != null ? `net income ${compactUsd(row.net_income)} USD` : null,
      row.eps_diluted != null ? `EPS ${row.eps_diluted.toFixed(2)}` : null,
      row.net_margin != null ? `net margin ${row.net_margin.toFixed(1)}%` : null,
    ].filter(Boolean);
    return `${periodLabel(row.end, spec.freq)}: ${bits.join(", ")}`;
  });
  return `${name} fundamentals. ${parts.join("; ")}.`;
}

export function fundamentalsCsv(spec: FundamentalsSpec): (string | number | null)[][] {
  return [
    [
      "period_end",
      "revenue_usd",
      "net_income_usd",
      "operating_income_usd",
      "eps_diluted",
      "gross_margin_pct",
      "operating_margin_pct",
      "net_margin_pct",
      "form",
      "link",
    ],
    ...spec.rows.map((row) => [
      row.end,
      row.revenue ?? null,
      row.net_income ?? null,
      row.operating_income ?? null,
      row.eps_diluted ?? null,
      row.gross_margin ?? null,
      row.operating_margin ?? null,
      row.net_margin ?? null,
      row.form ?? null,
      row.link ?? null,
    ]),
  ];
}

export function formatMetric(value: number | null | undefined, metric: ComparisonMetric): string {
  if (value === null || value === undefined) return "–";
  if (metric.unit === "%") return `${value.toFixed(1)}%`;
  if (metric.unit === "x") return `${value.toFixed(2)}x`;
  if (metric.unit === "USD" && Math.abs(value) >= 1e6) return `${compactUsd(value)} USD`;
  if (metric.unit === "USD") return value.toFixed(2);
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
