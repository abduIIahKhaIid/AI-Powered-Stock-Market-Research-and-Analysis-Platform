/**
 * Candlestick, volume and indicator chart for one symbol (SCRUM-36), drawn with
 * TradingView Lightweight Charts. The TradingView attribution stays visible (licence).
 *
 * When a new price series arrives the candles are drawn in from left to right (the price
 * scale is fixed for the run, so the chart does not jump), and the last price counts up.
 */
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { ArrowDownRightIcon, ArrowUpRightIcon, CandlestickChartIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../auth/session";
import { describeChart, INTERVAL_NAMES, PERIOD_NAMES } from "../charts/describe";
import { bollinger, macd, rsi, sma, type Series } from "../charts/indicators";
import { chartPalette, easeOutCubic } from "../charts/theme";
import { formatAsOf } from "../chat/tools";
import type { Candle, ChartSpec } from "../chat/types";
import { useCountUp } from "../lib/useCountUp";
import { cn } from "../lib/utils";
import { useAnimate, useSettings } from "../settings/context";
import ChartFrame, { ChartFoot } from "./ChartFrame";
import DetailChips from "./DetailChips";
import { Badge } from "./ui/badge";
import { Chip } from "./ui/chip";

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

function toTime(value: string): Time {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value as Time;
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

/** A data point plus the index of the candle it belongs to (for the draw-in animation). */
type Indexed<T> = { index: number; point: T };

function line(candles: Candle[], values: Series): Indexed<{ time: Time; value: number }>[] {
  return candles.flatMap((candle, i) =>
    values[i] === null
      ? []
      : [{ index: i, point: { time: toTime(candle.time), value: values[i] as number } }],
  );
}

/** One series of the chart with all of its data, drawn up to a candle index. */
interface Track {
  series: ISeriesApi<SeriesType>;
  data: Indexed<unknown>[];
  min: number;
  max: number;
}

function range(values: number[]): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return { min, max };
}

interface Props {
  spec: ChartSpec;
  /** Injected in tests; defaults to window.fetch. */
  fetchPrices?: (symbol: string, period: string, interval: string) => Promise<ChartSpec>;
}

async function defaultFetchPrices(symbol: string, period: string, interval: string) {
  const query = new URLSearchParams({ period, interval });
  const response = await apiFetch(`/api/prices/${encodeURIComponent(symbol)}?${query}`);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Could not load prices (HTTP ${response.status}).`);
  }
  return (await response.json()) as ChartSpec;
}

interface Hover {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

function price(value: number): string {
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
  const [hover, setHover] = useState<Hover | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const animatedFor = useRef<ChartSpec | null>(null);
  const animate = useAnimate();
  const { resolvedTheme } = useSettings();

  const closes = useMemo(() => spec.candles.map((c) => c.close), [spec]);
  const first = spec.candles[0];
  const last = spec.candles[spec.candles.length - 1];
  const change = first && last ? ((last.close - first.close) / first.close) * 100 : 0;
  const shownPrice = useCountUp(last?.close ?? 0, animate);

  useEffect(() => {
    const element = container.current;
    if (!element || !spec.candles.length) return;
    const colors = chartPalette(resolvedTheme);
    const intraday = !/^\d{4}-\d{2}-\d{2}$/.test(spec.candles[0].time);
    const chart: IChartApi = createChart(element, {
      autoSize: true,
      height: 320 + (shown.has("rsi") ? 110 : 0) + (shown.has("macd") ? 110 : 0),
      layout: {
        background: { color: "transparent" },
        textColor: colors.text,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        attributionLogo: true,
        panes: { separatorColor: colors.grid },
      },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      crosshair: {
        vertLine: { color: colors.crosshair, labelBackgroundColor: colors.sma20 },
        horzLine: { color: colors.crosshair, labelBackgroundColor: colors.sma20 },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday },
    });
    const tracks: Track[] = [];

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      borderVisible: false,
    });
    tracks.push({
      series: candles,
      data: spec.candles.map((c, index) => ({
        index,
        point: { time: toTime(c.time), open: c.open, high: c.high, low: c.low, close: c.close },
      })),
      min: Math.min(...spec.candles.map((c) => c.low)),
      max: Math.max(...spec.candles.map((c) => c.high)),
    });

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    // Keep the candles above the volume bars.
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.25 } });
    tracks.push({
      series: volume,
      data: spec.candles.map((c, index) => ({
        index,
        point: {
          time: toTime(c.time),
          value: c.volume,
          color: c.close >= c.open ? colors.volumeUp : colors.volumeDown,
        },
      })),
      min: 0,
      max: Math.max(...spec.candles.map((c) => c.volume)),
    });

    const overlay = { lineWidth: 2 as const, lastValueVisible: false, priceLineVisible: false };
    const addLine = (data: Indexed<{ time: Time; value: number }>[], series: Track["series"]) => {
      tracks.push({ series, data, ...range(data.map((d) => d.point.value)) });
    };
    if (shown.has("sma20")) {
      addLine(
        line(spec.candles, sma(closes, 20)),
        chart.addSeries(LineSeries, { ...overlay, color: colors.sma20 }),
      );
    }
    if (shown.has("sma50")) {
      addLine(
        line(spec.candles, sma(closes, 50)),
        chart.addSeries(LineSeries, { ...overlay, color: colors.sma50 }),
      );
    }
    if (shown.has("bollinger")) {
      const bands = bollinger(closes);
      for (const band of [bands.upper, bands.middle, bands.lower]) {
        addLine(
          line(spec.candles, band),
          chart.addSeries(LineSeries, { ...overlay, lineWidth: 1, color: colors.band }),
        );
      }
    }

    let pane = 1;
    if (shown.has("rsi")) {
      const rsiSeries = chart.addSeries(LineSeries, { ...overlay, color: colors.rsi }, pane);
      tracks.push({ series: rsiSeries, data: line(spec.candles, rsi(closes)), min: 0, max: 100 });
      for (const [level, color] of [
        [70, colors.down],
        [30, colors.up],
      ] as const) {
        rsiSeries.createPriceLine({
          price: level,
          color,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: "",
        });
      }
      pane += 1;
    }
    if (shown.has("macd")) {
      const result = macd(closes);
      const histogram = spec.candles.flatMap((c, i) =>
        result.histogram[i] === null
          ? []
          : [
              {
                index: i,
                point: {
                  time: toTime(c.time),
                  value: result.histogram[i] as number,
                  color: (result.histogram[i] as number) >= 0 ? colors.volumeUp : colors.volumeDown,
                },
              },
            ],
      );
      const all = [...result.macd, ...result.signal, ...result.histogram].filter(
        (v): v is number => v !== null,
      );
      const bounds = range(all);
      tracks.push({
        series: chart.addSeries(
          HistogramSeries,
          { lastValueVisible: false, priceLineVisible: false },
          pane,
        ),
        data: histogram,
        ...bounds,
      });
      tracks.push({
        series: chart.addSeries(LineSeries, { ...overlay, color: colors.macd }, pane),
        data: line(spec.candles, result.macd),
        ...bounds,
      });
      tracks.push({
        series: chart.addSeries(LineSeries, { ...overlay, color: colors.signal }, pane),
        data: line(spec.candles, result.signal),
        ...bounds,
      });
    }
    const panes = chart.panes();
    if (panes.length > 1) {
      panes[0].setStretchFactor(3);
      panes.slice(1).forEach((p) => p.setStretchFactor(1));
    }

    const drawUpTo = (count: number) => {
      for (const track of tracks) {
        track.series.setData(
          track.data.filter((d) => d.index < count).map((d) => d.point) as never[],
        );
      }
    };

    // Show the OHLC values of the candle under the cursor in the header.
    const onMove: Parameters<IChartApi["subscribeCrosshairMove"]>[0] = (param) => {
      const bar = param.seriesData?.get(candles) as
        { open: number; high: number; low: number; close: number } | undefined;
      if (!param.time || !bar || !("open" in bar)) {
        setHover(null);
        return;
      }
      const index = spec.candles.findIndex(
        (c) => JSON.stringify(toTime(c.time)) === JSON.stringify(param.time),
      );
      setHover({
        time: index >= 0 ? spec.candles[index].time : String(param.time),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      });
    };
    chart.subscribeCrosshairMove?.(onMove);

    // Draw in only when the data is new, not when an indicator is toggled or the theme changes.
    const total = spec.candles.length;
    // (Marked as drawn only at the end, so a re-run that cancels the animation starts it again.)
    const drawIn = animate && total > 1 && animatedFor.current !== spec;
    let frame = 0;
    if (drawIn) {
      const fixed = (track: Track) => (): AutoscaleInfo => ({
        priceRange: { minValue: track.min, maxValue: track.max },
      });
      tracks.forEach((track) =>
        track.series.applyOptions?.({ autoscaleInfoProvider: fixed(track) }),
      );
      const visible = () =>
        chart.timeScale().setVisibleLogicalRange?.({ from: -0.5, to: total - 0.5 });
      drawUpTo(1);
      visible();
      const duration = Math.min(1500, 700 + total * 3);
      const start = performance.now();
      let drawn = 1;
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        const count = Math.max(1, Math.ceil(easeOutCubic(t) * total));
        if (count !== drawn) {
          drawn = count;
          drawUpTo(count);
          visible();
        }
        if (t < 1) {
          frame = requestAnimationFrame(tick);
        } else {
          animatedFor.current = spec;
          tracks.forEach((track) =>
            track.series.applyOptions?.({
              autoscaleInfoProvider: (base: () => AutoscaleInfo) => base(),
            }),
          );
          chart.timeScale().fitContent();
        }
      };
      frame = requestAnimationFrame(tick);
    } else {
      animatedFor.current = spec;
      drawUpTo(total);
      chart.timeScale().fitContent();
    }

    return () => {
      cancelAnimationFrame(frame);
      chart.unsubscribeCrosshairMove?.(onMove);
      chart.remove();
    };
  }, [spec, shown, closes, animate, resolvedTheme]);

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
  const up = change >= 0;

  return (
    <ChartFrame
      title={title}
      icon={<CandlestickChartIcon />}
      busy={loading}
      subtitle={
        last ? (
          hover ? (
            <span className="font-mono tabular-nums">
              {hover.time.slice(0, 10)} · O {price(hover.open)} · H {price(hover.high)} · L{" "}
              {price(hover.low)} · C {price(hover.close)}
            </span>
          ) : (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono text-base font-semibold whitespace-nowrap text-foreground tabular-nums">
                {price(shownPrice)} <span className="text-xs font-normal">USD</span>
              </span>
              <Badge variant={up ? "up" : "down"}>
                {up ? (
                  <ArrowUpRightIcon aria-hidden="true" />
                ) : (
                  <ArrowDownRightIcon aria-hidden="true" />
                )}
                {`${up ? "+" : ""}${change.toFixed(2)}%`}
              </Badge>
              <span>over the period</span>
            </span>
          )
        ) : undefined
      }
      actions={
        <div
          className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
          role="group"
          aria-label="Period"
        >
          {PERIODS.map((p) => {
            const selected = p.period === spec.period && p.interval === spec.interval;
            return (
              <button
                key={p.label}
                type="button"
                aria-pressed={selected}
                disabled={loading}
                onClick={() => choosePeriod(p.period, p.interval)}
                className={cn(
                  "h-7 cursor-pointer rounded-md px-2.5 text-xs font-semibold transition-all disabled:cursor-wait",
                  selected
                    ? "bg-card text-foreground shadow-sm ring-1 ring-border/60"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {p.label}
              </button>
            );
          })}
        </div>
      }
    >
      <div className="flex flex-wrap gap-1.5 px-4 pb-2" role="group" aria-label="Indicators">
        {INDICATORS.map((indicator) => (
          <Chip
            key={indicator.key}
            aria-pressed={shown.has(indicator.key)}
            onClick={() => toggle(indicator.key)}
          >
            {indicator.label}
          </Chip>
        ))}
      </div>
      {error && (
        <p className="mx-4 mb-2 rounded-md bg-down/10 px-3 py-2 text-xs text-down" role="alert">
          {error}
        </p>
      )}
      <div
        className={cn("tv-chart relative px-2 transition-opacity", loading && "opacity-50")}
        ref={container}
        role="img"
        aria-label={summary}
      />
      <p className="sr-only">{summary}</p>
      <DetailChips sources={spec.sources} assumptions={spec.assumptions} />
      <ChartFoot>
        {spec.source ?? "Price data"}
        {spec.as_of ? `, as of ${formatAsOf(spec.as_of)}` : ""}
        {spec.adjusted ? "" : ". Prices not adjusted for splits or dividends"}. Chart by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
          TradingView
        </a>
        .
      </ChartFoot>
    </ChartFrame>
  );
}
