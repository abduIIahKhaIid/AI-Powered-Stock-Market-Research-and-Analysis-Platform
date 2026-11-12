/**
 * Candlestick, volume and indicator chart for one symbol (SCRUM-36), drawn with
 * TradingView Lightweight Charts. The TradingView attribution stays visible (licence).
 */
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { bollinger, macd, rsi, sma, type Series } from "../charts/indicators";
import { formatAsOf } from "../chat/tools";
import { describeChart, INTERVAL_NAMES, PERIOD_NAMES } from "../charts/describe";
import type { Candle, ChartSpec } from "../chat/types";

const PERIODS: { label: string; period: string; interval: string }[] = [
  { label: "1M", period: "1mo", interval: "1d" },
  { label: "3M", period: "3mo", interval: "1d" },
  { label: "6M", period: "6mo", interval: "1d" },
  { label: "1Y", period: "1y", interval: "1d" },
  { label: "5Y", period: "5y", interval: "1wk" },
];

type Indicator = "sma20" | "sma50" | "bollinger" | "rsi" | "macd";
const INDICATORS: { key: Indicator; label: string }[] = [
  { key: "sma20", label: "SMA 20" },
  { key: "sma50", label: "SMA 50" },
  { key: "bollinger", label: "Bollinger" },
  { key: "rsi", label: "RSI 14" },
  { key: "macd", label: "MACD" },
];

const COLORS = {
  up: "#1a7f5a",
  down: "#c0392b",
  volumeUp: "rgba(26, 127, 90, 0.35)",
  volumeDown: "rgba(192, 57, 43, 0.35)",
  sma20: "#2563eb",
  sma50: "#9333ea",
  band: "#8a94a6",
  rsi: "#7c3aed",
  macd: "#2563eb",
  signal: "#d97706",
  grid: "#eef0f3",
  text: "#5d6470",
};

function toTime(value: string): Time {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value as Time;
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

function line(candles: Candle[], values: Series) {
  return candles.flatMap((candle, i) =>
    values[i] === null ? [] : [{ time: toTime(candle.time), value: values[i] as number }],
  );
}

interface Props {
  spec: ChartSpec;
  /** Injected in tests; defaults to window.fetch. */
  fetchPrices?: (symbol: string, period: string, interval: string) => Promise<ChartSpec>;
}

async function defaultFetchPrices(symbol: string, period: string, interval: string) {
  const query = new URLSearchParams({ period, interval });
  const response = await fetch(`/api/prices/${encodeURIComponent(symbol)}?${query}`);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Could not load prices (HTTP ${response.status}).`);
  }
  return (await response.json()) as ChartSpec;
}

export default function PriceChart({ spec: initial, fetchPrices = defaultFetchPrices }: Props) {
  const [spec, setSpec] = useState(initial);
  const [shown, setShown] = useState<Set<Indicator>>(() => {
    const requested = (initial.indicators ?? []).filter((key): key is Indicator =>
      INDICATORS.some((indicator) => indicator.key === key),
    );
    return new Set<Indicator>(requested.length ? requested : ["sma20"]);
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);

  const closes = useMemo(() => spec.candles.map((c) => c.close), [spec]);

  useEffect(() => {
    const element = container.current;
    if (!element || !spec.candles.length) return;
    const intraday = !/^\d{4}-\d{2}-\d{2}$/.test(spec.candles[0].time);
    const chart: IChartApi = createChart(element, {
      autoSize: true,
      height: 320 + (shown.has("rsi") ? 110 : 0) + (shown.has("macd") ? 110 : 0),
      layout: {
        background: { color: "#ffffff" },
        textColor: COLORS.text,
        attributionLogo: true,
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      borderVisible: false,
    });
    candles.setData(
      spec.candles.map((c) => ({
        time: toTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    // Keep the candles above the volume bars.
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.25 } });
    volume.setData(
      spec.candles.map((c) => ({
        time: toTime(c.time),
        value: c.volume,
        color: c.close >= c.open ? COLORS.volumeUp : COLORS.volumeDown,
      })),
    );

    const overlay = { lineWidth: 2 as const, lastValueVisible: false, priceLineVisible: false };
    if (shown.has("sma20")) {
      chart
        .addSeries(LineSeries, { ...overlay, color: COLORS.sma20 })
        .setData(line(spec.candles, sma(closes, 20)));
    }
    if (shown.has("sma50")) {
      chart
        .addSeries(LineSeries, { ...overlay, color: COLORS.sma50 })
        .setData(line(spec.candles, sma(closes, 50)));
    }
    if (shown.has("bollinger")) {
      const bands = bollinger(closes);
      for (const band of [bands.upper, bands.middle, bands.lower]) {
        chart
          .addSeries(LineSeries, { ...overlay, lineWidth: 1, color: COLORS.band })
          .setData(line(spec.candles, band));
      }
    }

    let pane = 1;
    if (shown.has("rsi")) {
      const rsiSeries = chart.addSeries(LineSeries, { ...overlay, color: COLORS.rsi }, pane);
      rsiSeries.setData(line(spec.candles, rsi(closes)));
      rsiSeries.createPriceLine({
        price: 70,
        color: COLORS.down,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: "",
      });
      rsiSeries.createPriceLine({
        price: 30,
        color: COLORS.up,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: "",
      });
      pane += 1;
    }
    if (shown.has("macd")) {
      const result = macd(closes);
      chart
        .addSeries(HistogramSeries, { lastValueVisible: false, priceLineVisible: false }, pane)
        .setData(
          spec.candles.flatMap((c, i) =>
            result.histogram[i] === null
              ? []
              : [
                  {
                    time: toTime(c.time),
                    value: result.histogram[i] as number,
                    color:
                      (result.histogram[i] as number) >= 0 ? COLORS.volumeUp : COLORS.volumeDown,
                  },
                ],
          ),
        );
      chart
        .addSeries(LineSeries, { ...overlay, color: COLORS.macd }, pane)
        .setData(line(spec.candles, result.macd));
      chart
        .addSeries(LineSeries, { ...overlay, color: COLORS.signal }, pane)
        .setData(line(spec.candles, result.signal));
    }
    const panes = chart.panes();
    if (panes.length > 1) {
      panes[0].setStretchFactor(3);
      panes.slice(1).forEach((p) => p.setStretchFactor(1));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [spec, shown, closes]);

  async function choosePeriod(period: string, interval: string) {
    if (period === spec.period && interval === spec.interval) return;
    setLoading(true);
    setError(null);
    try {
      setSpec(await fetchPrices(spec.symbol, period, interval));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load prices.");
    } finally {
      setLoading(false);
    }
  }

  function toggle(key: Indicator) {
    setShown((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const title = `${spec.name ? `${spec.name} (${spec.symbol})` : spec.symbol}, ${
    INTERVAL_NAMES[spec.interval] ?? spec.interval
  }, ${PERIOD_NAMES[spec.period] ?? spec.period}`;
  const summary = describeChart(spec);

  return (
    <figure className="price-chart" aria-busy={loading}>
      <div className="chart-head">
        <figcaption className="chart-title">{title}</figcaption>
        <div className="chart-periods" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="chip"
              aria-pressed={p.period === spec.period && p.interval === spec.interval}
              disabled={loading}
              onClick={() => choosePeriod(p.period, p.interval)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-indicators" role="group" aria-label="Indicators">
        {INDICATORS.map((indicator) => (
          <button
            key={indicator.key}
            type="button"
            className="chip"
            aria-pressed={shown.has(indicator.key)}
            onClick={() => toggle(indicator.key)}
          >
            {indicator.label}
          </button>
        ))}
      </div>
      {error && (
        <p className="chart-error" role="alert">
          {error}
        </p>
      )}
      <div className="chart-canvas" ref={container} role="img" aria-label={summary} />
      <p className="visually-hidden">{summary}</p>
      <p className="chart-foot">
        {spec.source ?? "Price data"}
        {spec.as_of ? `, as of ${formatAsOf(spec.as_of)}` : ""}
        {spec.adjusted ? "" : ". Prices not adjusted for splits or dividends"}. Chart by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
          TradingView
        </a>
        .
      </p>
    </figure>
  );
}
