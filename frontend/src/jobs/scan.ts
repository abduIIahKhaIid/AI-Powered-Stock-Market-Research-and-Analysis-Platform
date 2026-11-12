import type { ScanResult, ScanRow } from "./types";

export interface ScanColumn {
  indicator: string;
  series: string;
  label: string;
}

export function isScanResult(value: unknown): value is ScanResult {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ScanResult>;
  return Array.isArray(candidate.symbols) && typeof candidate.rows === "object";
}

/** One column per indicator series, e.g. "rsi_14" or "macd: signal". */
export function scanColumns(rows: Record<string, ScanRow>): ScanColumn[] {
  const series = new Map<string, Set<string>>();
  for (const row of Object.values(rows)) {
    for (const [indicator, values] of Object.entries(row.latest ?? {})) {
      const names = series.get(indicator) ?? new Set<string>();
      Object.keys(values).forEach((name) => names.add(name));
      series.set(indicator, names);
    }
  }
  return [...series.entries()].flatMap(([indicator, names]) =>
    [...names].map((name) => ({
      indicator,
      series: name,
      label: names.size === 1 ? indicator : `${indicator}: ${name}`,
    })),
  );
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
}
