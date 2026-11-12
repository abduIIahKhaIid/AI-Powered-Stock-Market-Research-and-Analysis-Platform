import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { scanColumns } from "../jobs/scan";
import type { SavedAnalysis } from "../jobs/types";

const JOB_ID = "a".repeat(32);

const SAVED: SavedAnalysis[] = [
  {
    id: JOB_ID,
    kind: "indicator_scan",
    title: "Indicator scan",
    summary: "rsi_14, macd for AAPL, IBM (6mo)",
    conversation_id: null,
    created_at: "2026-11-12T09:00:00+00:00",
    finished_at: "2026-11-12T09:00:20+00:00",
    files: [{ name: "indicator_scan.csv", bytes: 2048, media_type: "text/csv" }],
  },
];

const RESULT = {
  job: { id: JOB_ID, kind: "indicator_scan", params: {}, finished_at: SAVED[0].finished_at },
  result: {
    symbols: ["AAPL", "IBM"],
    indicators: ["rsi_14", "macd"],
    period: "6mo",
    rows: {
      AAPL: {
        last_close: 231.456,
        last_bar: "2026-11-11T00:00:00",
        latest: { rsi_14: { rsi_14: 61.237 }, macd: { macd: 1.5, signal: 1.2, histogram: 0.3 } },
        signals: ["RSI 14 is between 30 and 70"],
      },
      IBM: { error: "IBM is not listed on NASDAQ." },
    },
    sources: [{ source: "Yahoo Finance (yfinance)", as_of: "2026-11-11" }],
  },
};

function mockApi(routes: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const match = Object.keys(routes).find((path) => url.includes(path));
    if (match) return routes[match]();
    return Response.json({ status: "ok", services: { api: "ok" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Saved analyses", () => {
  it("lists saved analyses and reopens one with its table, files and source", async () => {
    mockApi({
      "/api/analyses": () => Response.json(SAVED),
      [`/api/jobs/${JOB_ID}/result`]: () => Response.json(RESULT),
    });
    render(<App />);

    const list = await screen.findByRole("region", { name: "Saved analyses" });
    fireEvent.click(within(list).getByRole("button", { name: /Indicator scan/ }));

    const dialog = await screen.findByRole("dialog", { name: "Indicator scan" });
    const table = await within(dialog).findByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual([
      "Symbol",
      "Last close",
      "rsi_14",
      "macd: macd",
      "macd: signal",
      "macd: histogram",
      "Signals",
    ]);
    const aapl = within(table).getByRole("row", { name: /AAPL/ });
    expect(aapl).toHaveTextContent("231.46");
    expect(aapl).toHaveTextContent("61.24");
    expect(within(table).getByRole("row", { name: /IBM/ })).toHaveTextContent(
      "IBM is not listed on NASDAQ.",
    );

    const download = within(dialog).getByRole("link", { name: "Download indicator_scan.csv" });
    expect(download).toHaveAttribute("href", `/api/jobs/${JOB_ID}/files/indicator_scan.csv`);
    expect(dialog).toHaveTextContent("(2.0 KB)");
    expect(dialog).toHaveTextContent("Source: Yahoo Finance (yfinance), as of 2026-11-11");
    expect(dialog).toHaveTextContent("not financial advice");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("explains an empty list and a missing result", async () => {
    mockApi({
      "/api/analyses": () => Response.json(SAVED),
      [`/api/jobs/${JOB_ID}/result`]: () =>
        Response.json({ detail: "The saved result file is missing." }, { status: 410 }),
    });
    render(<App />);
    const list = await screen.findByRole("region", { name: "Saved analyses" });
    fireEvent.click(within(list).getByRole("button", { name: /Indicator scan/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The saved result file is missing.");
    fireEvent.click(screen.getByRole("button", { name: "Close analysis" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says when there is nothing saved yet or the list cannot load", async () => {
    mockApi({ "/api/analyses": () => Response.json([]) });
    const { unmount } = render(<App />);
    expect(await screen.findByText("Finished scans are kept here.")).toBeInTheDocument();
    unmount();

    mockApi({ "/api/analyses": () => new Response("down", { status: 503 }) });
    render(<App />);
    expect(await screen.findByText("Saved analyses could not be loaded.")).toBeInTheDocument();
  });

  it("names one-series indicators plainly and multi-series ones by series", () => {
    const columns = scanColumns({
      A: { latest: { sma_50: { sma_50: 1 }, bbands: { upper: 2, lower: 1 } } },
    });
    expect(columns.map((c) => c.label)).toEqual(["sma_50", "bbands: upper", "bbands: lower"]);
  });
});
