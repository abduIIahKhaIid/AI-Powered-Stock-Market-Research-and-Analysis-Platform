/**
 * Indicator series for the price chart (SCRUM-36). Standard definitions:
 * SMA; EMA seeded with the SMA of its first window; Bollinger Bands on population
 * standard deviation; RSI with Wilder smoothing; MACD(12, 26, 9).
 * Each function returns one value per input, null until enough data exists.
 */

export type Series = (number | null)[];

export function sma(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let previous = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = previous;
  for (let i = period; i < values.length; i++) {
    previous = values[i] * k + previous * (1 - k);
    out[i] = previous;
  }
  return out;
}

export function bollinger(
  values: number[],
  period = 20,
  deviations = 2,
): { middle: Series; upper: Series; lower: Series } {
  const middle = sma(values, period);
  const upper: Series = new Array(values.length).fill(null);
  const lower: Series = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const mean = middle[i] as number;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) variance += (values[j] - mean) ** 2;
    const sd = Math.sqrt(variance / period);
    upper[i] = mean + deviations * sd;
    lower[i] = mean - deviations * sd;
  }
  return { middle, upper, lower };
}

export function rsi(values: number[], period = 14): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const change = values[i] - values[i - 1];
    if (change >= 0) gain += change;
    else loss -= change;
  }
  gain /= period;
  loss /= period;
  const value = () => (loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  out[period] = value();
  for (let i = period + 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(change, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-change, 0)) / period;
    out[i] = value();
  }
  return out;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9,
): { macd: Series; signal: Series; histogram: Series } {
  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);
  const line: Series = values.map((_, i) =>
    fastEma[i] !== null && slowEma[i] !== null
      ? (fastEma[i] as number) - (slowEma[i] as number)
      : null,
  );
  const start = line.findIndex((v) => v !== null);
  const signal: Series = new Array(values.length).fill(null);
  if (start !== -1) {
    const tail = ema(line.slice(start) as number[], signalPeriod);
    tail.forEach((v, i) => (signal[start + i] = v));
  }
  const histogram: Series = line.map((v, i) =>
    v !== null && signal[i] !== null ? v - (signal[i] as number) : null,
  );
  return { macd: line, signal, histogram };
}
