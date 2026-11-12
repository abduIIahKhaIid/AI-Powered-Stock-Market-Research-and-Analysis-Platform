import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartSpec } from "../chat/types";

const calls = vi.hoisted(() => ({ charts: [] as { series: unknown[][]; options: unknown }[] }));

vi.mock("lightweight-charts", () => {
  const series = () => ({
    setData: vi.fn(),
    createPriceLine: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
  });
  return {
    CandlestickSeries: "Candlestick",
    HistogramSeries: "Histogram",
    LineSeries: "Line",
    createChart: (_element: HTMLElement, options: unknown) => {
      const record = { series: [] as unknown[][], options };
      calls.charts.push(record);
      return {
        addSeries: (type: unknown, opts: unknown, pane?: number) => {
          record.series.push([type, pane ?? 0, opts]);
          return series();
        },
        priceScale: () => ({ applyOptions: vi.fn() }),
        panes: () => [{ setStretchFactor: vi.fn() }],
        timeScale: () => ({ fitContent: vi.fn() }),
        remove: vi.fn(),
      };
    },
  };
});

import { describeChart } from "../charts/describe";
import PriceChart from "./PriceChart";

const candles = Array.from({ length: 30 }, (_, i) => ({
  time: `2026-10-${String(i + 1).padStart(2, "0")}`,
  open: 100 + i,
  high: 102 + i,
  low: 99 + i,
  close: 101 + i,
  volume: 1000 + i,
}));
const spec: ChartSpec = {
  kind: "price",
  symbol: "AAPL",
  name: "Apple Inc.",
  period: "1mo",
  interval: "1d",
  adjusted: false,
  candles,
  source: "Yahoo Finance via yfinance",
  as_of: "2026-10-30",
};

const lastChart = () => calls.charts[calls.charts.length - 1];

describe("PriceChart", () => {
  beforeEach(() => {
    calls.charts.length = 0;
  });

  it("draws candles, volume and the default SMA 20 with attribution", () => {
    render(<PriceChart spec={spec} />);
    const types = lastChart().series.map(([type]) => type);
    expect(types).toEqual(["Candlestick", "Histogram", "Line"]);
    expect(lastChart().options).toMatchObject({ layout: { attributionLogo: true } });
    expect(screen.getByText("Apple Inc. (AAPL), daily, 1 month")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TradingView" })).toHaveAttribute(
      "href",
      "https://www.tradingview.com/",
    );
    expect(screen.getByText(/not adjusted for splits/)).toBeInTheDocument();
  });

  it("puts RSI and MACD in their own panes when switched on", () => {
    render(<PriceChart spec={spec} />);
    fireEvent.click(screen.getByRole("button", { name: "RSI 14" }));
    fireEvent.click(screen.getByRole("button", { name: "MACD" }));
    const panes = lastChart().series.map(([type, pane]) => `${type}@${pane}`);
    expect(panes).toContain("Line@1");
    expect(panes).toContain("Histogram@2");
    expect(screen.getByRole("button", { name: "RSI 14" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches on the indicators the model asked for", () => {
    render(<PriceChart spec={{ ...spec, indicators: ["rsi", "macd", "unknown"] }} />);
    expect(screen.getByRole("button", { name: "RSI 14" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "MACD" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "SMA 20" })).toHaveAttribute("aria-pressed", "false");
    const panes = lastChart().series.map(([type, pane]) => `${type}@${pane}`);
    expect(panes).toContain("Line@1");
  });

  it("loads another period and shows errors from the API", async () => {
    const fetchPrices = vi
      .fn()
      .mockResolvedValueOnce({ ...spec, period: "1y" })
      .mockRejectedValueOnce(new Error("'XYZ' is not listed on NASDAQ."));
    render(<PriceChart spec={spec} fetchPrices={fetchPrices} />);

    fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "1Y" })).toHaveAttribute("aria-pressed", "true"),
    );
    expect(fetchPrices).toHaveBeenCalledWith("AAPL", "1y", "1d");

    fireEvent.click(screen.getByRole("button", { name: "5Y" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not listed on NASDAQ");
    expect(fetchPrices).toHaveBeenLastCalledWith("AAPL", "5y", "1wk");
  });

  it("describes the chart in text", () => {
    expect(describeChart(spec)).toBe(
      "AAPL daily prices, 2026-10-01 to 2026-10-30: close 101 to 130 (+28.71%), high 131, low 99.",
    );
  });
});
