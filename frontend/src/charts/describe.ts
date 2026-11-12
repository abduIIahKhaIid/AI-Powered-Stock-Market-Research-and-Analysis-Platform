import type { ChartSpec } from "../chat/types";

export const PERIOD_NAMES: Record<string, string> = {
  "5d": "5 days",
  "1mo": "1 month",
  "3mo": "3 months",
  "6mo": "6 months",
  ytd: "year to date",
  "1y": "1 year",
  "2y": "2 years",
  "5y": "5 years",
  "10y": "10 years",
  max: "all available history",
};
export const INTERVAL_NAMES: Record<string, string> = {
  "1d": "daily",
  "1wk": "weekly",
  "1mo": "monthly",
};

/** A short text version of the chart for screen readers and tests. */
export function describeChart(spec: ChartSpec): string {
  const { candles } = spec;
  if (!candles.length) return `No price data for ${spec.symbol}.`;
  const first = candles[0];
  const last = candles[candles.length - 1];
  const high = Math.max(...candles.map((c) => c.high));
  const low = Math.min(...candles.map((c) => c.low));
  const change = ((last.close - first.close) / first.close) * 100;
  const sign = change >= 0 ? "+" : "";
  return (
    `${spec.symbol} ${INTERVAL_NAMES[spec.interval] ?? spec.interval} prices, ` +
    `${first.time.slice(0, 10)} to ${last.time.slice(0, 10)}: close ${first.close} to ${last.close} ` +
    `(${sign}${change.toFixed(2)}%), high ${high}, low ${low}.`
  );
}
