import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const downloads = vi.hoisted(() => [] as { filename: string; rows: unknown[][] }[]);
vi.mock("../charts/csv", async (importOriginal) => {
  const original = await importOriginal<typeof import("../charts/csv")>();
  return {
    ...original,
    downloadCsv: (filename: string, rows: unknown[][]) => downloads.push({ filename, rows }),
  };
});

import { toCsv } from "../charts/csv";
import { withFan } from "../charts/scenario";
import type { ComparisonSpec, FundamentalsSpec } from "../chat/types";
import ComparisonTable from "./ComparisonTable";
import DetailChips from "./DetailChips";
import FundamentalsChart from "./FundamentalsChart";

const FUNDAMENTALS: FundamentalsSpec = {
  kind: "fundamentals",
  symbol: "AAPL",
  name: "Apple Inc.",
  freq: "annual",
  rows: [
    {
      end: "2024-09-28",
      revenue: 391e9,
      net_income: 93.7e9,
      eps_diluted: 6.08,
      gross_margin: 46.2,
      operating_margin: 31.5,
      net_margin: 24.0,
      form: "10-K",
      link: "https://www.sec.gov/a/",
    },
    {
      end: "2025-09-27",
      revenue: 416e9,
      net_income: 112e9,
      eps_diluted: 7.46,
      gross_margin: 46.9,
      operating_margin: 32.0,
      net_margin: 26.9,
      form: "10-K",
      link: "https://www.sec.gov/b/",
    },
  ],
  source: "SEC EDGAR company facts (XBRL)",
  as_of: "2025-10-31",
  sources: [
    { label: "10-K for the period ending 2025-09-27", link: "https://www.sec.gov/b/" },
    { label: "10-K for the period ending 2024-09-28", link: "https://www.sec.gov/a/" },
  ],
  assumptions: ["Margins are each item divided by revenue for the same period, times 100."],
};

const COMPARISON: ComparisonSpec = {
  kind: "comparison",
  symbol: "AAPL,MSFT,NVDA",
  symbols: ["AAPL", "MSFT", "NVDA"],
  metrics: [
    { key: "pe", label: "P/E", unit: "x", formula: "price / diluted EPS" },
    { key: "net_margin", label: "Net margin", unit: "%", formula: "net income / revenue x 100" },
    { key: "market_cap", label: "Market cap", unit: "USD", formula: "price x shares" },
  ],
  values: {
    AAPL: { pe: { value: 35.2 }, net_margin: { value: 26.9 }, market_cap: { value: 3.4e12 } },
    MSFT: {
      pe: { value: null, error: "MSFT: no SEC data" },
      net_margin: { value: 36.1 },
      market_cap: { value: 3.8e12 },
    },
    NVDA: { pe: { value: 41.5 }, net_margin: { value: 55.8 }, market_cap: { value: 4.4e12 } },
  },
  source: "SEC EDGAR; latest closing prices",
  as_of: "2026-11-17",
  sources: [{ label: "SEC EDGAR, fiscal year ending 2025-09-27", link: "https://www.sec.gov/b/" }],
  assumptions: ["P/E = price / diluted EPS", "Net margin = net income / revenue x 100"],
};

const firstColumn = (table: HTMLElement) =>
  within(table)
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent);

describe("FundamentalsChart", () => {
  it("switches between revenue, EPS and margin views and lists the data", () => {
    render(<FundamentalsChart spec={FUNDAMENTALS} />);
    expect(screen.getByText("Apple Inc. (AAPL), annual fundamentals")).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "Chart" });
    const buttons = within(views).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Revenue & net income", "EPS", "Margins"]);
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(buttons[2]);
    expect(buttons[2]).toHaveAttribute("aria-pressed", "true");
    const table = screen.getByRole("table");
    expect(firstColumn(table)).toEqual(["FY2024", "FY2025"]);
    expect(within(table).getByRole("row", { name: /FY2025/ })).toHaveTextContent("416B");
    expect(within(table).getByRole("row", { name: /FY2025/ })).toHaveTextContent("26.9%");
  });

  it("opens its sources and assumptions from the chips", () => {
    render(<FundamentalsChart spec={FUNDAMENTALS} />);
    const sources = screen.getByRole("button", { name: "Sources (2)" });
    expect(sources).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(sources);
    expect(sources).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Sources" });
    expect(
      within(list).getByRole("link", { name: "10-K for the period ending 2025-09-27" }),
    ).toHaveAttribute("href", "https://www.sec.gov/b/");
    fireEvent.click(screen.getByRole("button", { name: "Assumptions (1)" }));
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
    expect(screen.getByRole("list", { name: "Assumptions" })).toHaveTextContent(
      "Margins are each item",
    );
  });

  it("exports CSV only after approval", () => {
    downloads.length = 0;
    render(<FundamentalsChart spec={FUNDAMENTALS} />);
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    const card = screen.getByRole("region", { name: "Approval needed" });
    expect(card).toHaveTextContent("Export AAPL fundamentals as CSV");
    expect(card).toHaveTextContent("Instant, built in your browser (2 rows). No cost.");
    expect(downloads).toHaveLength(0);
    fireEvent.click(
      within(card).getByRole("button", { name: "Approve: export AAPL fundamentals as CSV" }),
    );
    expect(downloads[0].filename).toBe("AAPL-fundamentals.csv");
    expect(downloads[0].rows[0][0]).toBe("period_end");
    expect(downloads[0].rows[2]).toContain(416e9);
    expect(screen.getByRole("status")).toHaveTextContent("Exported AAPL-fundamentals.csv.");
  });
});

describe("ComparisonTable", () => {
  it("sorts by a column, keeps missing values last and marks the sort", () => {
    render(<ComparisonTable spec={COMPARISON} />);
    const table = screen.getByRole("table");
    expect(firstColumn(table)).toEqual(["AAPL", "MSFT", "NVDA"]);
    const pe = within(table).getByRole("button", { name: /^P\/E/ });
    fireEvent.click(pe);
    expect(firstColumn(table)).toEqual(["NVDA", "AAPL", "MSFT"]);
    expect(pe.closest("th")).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(pe);
    expect(firstColumn(table)).toEqual(["AAPL", "NVDA", "MSFT"]);
    expect(pe.closest("th")).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(within(table).getByRole("button", { name: "Symbol" }));
    expect(firstColumn(table)).toEqual(["NVDA", "MSFT", "AAPL"]);
  });

  it("formats each unit and explains missing cells", () => {
    render(<ComparisonTable spec={COMPARISON} />);
    const msft = screen.getByRole("row", { name: /MSFT/ });
    expect(msft).toHaveTextContent("–");
    expect(within(msft).getByTitle("MSFT: no SEC data")).toBeInTheDocument();
    const aapl = screen.getByRole("row", { name: /AAPL/ });
    expect(aapl).toHaveTextContent("35.20x");
    expect(aapl).toHaveTextContent("26.9%");
    expect(aapl).toHaveTextContent("3.4T USD");
    expect(screen.getByRole("button", { name: "Assumptions (2)" })).toBeEnabled();
  });

  it("asks before exporting and can be denied", () => {
    downloads.length = 0;
    render(<ComparisonTable spec={COMPARISON} />);
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: /^Deny: export the comparison/ }));
    expect(downloads).toHaveLength(0);
    expect(screen.getByRole("status")).toHaveTextContent("Not exported.");
  });
});

describe("helpers", () => {
  it("quotes CSV cells where needed", () => {
    expect(
      toCsv([
        ["a", "b,c"],
        [1, 'say "hi"'],
        [null, undefined],
      ]),
    ).toBe('a,"b,c"\n1,"say ""hi"""\n,\n');
  });

  it("disables a chip with nothing behind it", () => {
    render(<DetailChips sources={[{ label: "Yahoo" }]} assumptions={[]} />);
    expect(screen.getByRole("button", { name: "Assumptions (0)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sources (1)" })).toBeEnabled();
  });

  it("builds the scenario fan from bear to bull", () => {
    expect(
      withFan([
        { year: 2026, base: 2, bear: 1, bull: 3 },
        { year: 2027, base: 2 },
      ]),
    ).toEqual([
      { year: 2026, base: 2, bear: 1, bull: 3, range: [1, 3] },
      { year: 2027, base: 2 },
    ]);
  });
});
