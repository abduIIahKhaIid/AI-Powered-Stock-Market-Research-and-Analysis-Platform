import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { compactUsd, describeScenario, scenarioRows, signedPct } from "../charts/scenario";
import { applyEvent, newAssistantMessage } from "../chat/reducer";
import type { ChartSpec, ScenarioChartSpec } from "../chat/types";
import ScenarioChart from "./ScenarioChart";

const SPEC: ScenarioChartSpec = {
  kind: "scenario",
  symbol: "AAPL",
  name: "Apple Inc.",
  metric: "revenue",
  unit: "USD",
  base_year: 2024,
  base_value: 400e9,
  series: [
    {
      name: "base",
      points: [
        { year: 2025, value: 421e9 },
        { year: 2026, value: 443e9 },
      ],
    },
    {
      name: "bull",
      points: [
        { year: 2025, value: 433e9 },
        { year: 2026, value: 469e9 },
      ],
    },
    {
      name: "bear",
      points: [
        { year: 2025, value: 409e9 },
        { year: 2026, value: 418e9 },
      ],
    },
  ],
  table: [
    row("base", 5.26, 25, 9, 443e9, 7.38, 121.4, 13.4),
    row("bull", 8.26, 27, 8, 469e9, 8.44, 165.25, 54.3),
    row("bear", 2.26, 23, 10, 418e9, 6.41, 88.1, -17.7),
  ],
  price: 107.1,
  source: "SEC EDGAR; Yahoo Finance",
  as_of: "2026-11-13",
};

function row(
  name: string,
  growth: number,
  margin: number,
  discount: number,
  revenue: number,
  eps: number,
  value: number,
  vs: number,
) {
  return {
    case: name,
    revenue_growth: growth,
    net_margin: margin,
    discount_rate: discount,
    final_year: 2026,
    final_revenue: revenue,
    final_eps: eps,
    value_per_share: value,
    vs_price_pct: vs,
  };
}

describe("ScenarioChart", () => {
  it("shows the case table, the source and a text summary", () => {
    render(<ScenarioChart spec={SPEC} />);
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((c) => c.textContent);
    expect(headers).toEqual([
      "Case",
      "Revenue growth",
      "Net margin",
      "Discount rate",
      "Revenue 2026",
      "EPS 2026",
      "Value per share",
      "vs price (107.10)",
    ]);
    const bull = within(table).getByRole("row", { name: /bull/ });
    expect(bull).toHaveTextContent("8.3%");
    expect(bull).toHaveTextContent("469B");
    expect(bull).toHaveTextContent("165.25");
    expect(bull).toHaveTextContent("+54.3%");
    expect(within(table).getByRole("row", { name: /bear/ })).toHaveTextContent("-17.7%");
    expect(screen.getByText(/SEC EDGAR; Yahoo Finance, price as of/)).toBeInTheDocument();
    expect(screen.getByText(/not a forecast/)).toBeInTheDocument();
    expect(screen.getByText(describeScenario(SPEC))).toHaveClass("visually-hidden");
  });

  it("builds chart rows that start from the actual revenue", () => {
    expect(scenarioRows(SPEC)).toEqual([
      { year: 2024, base: 400e9, bull: 400e9, bear: 400e9 },
      { year: 2025, base: 421e9, bull: 433e9, bear: 409e9 },
      { year: 2026, base: 443e9, bull: 469e9, bear: 418e9 },
    ]);
    expect([compactUsd(1.25e12), compactUsd(950e6), signedPct(null), signedPct(3)]).toEqual([
      "1.3T",
      "950M",
      "–",
      "+3.0%",
    ]);
  });

  it("keeps a price chart and a scenario chart for the same symbol", () => {
    const price = { kind: "price", symbol: "AAPL", candles: [] } as unknown as ChartSpec;
    let message = newAssistantMessage("m", "simple");
    message = applyEvent(message, { type: "chart", data: price });
    message = applyEvent(message, { type: "chart", data: SPEC });
    message = applyEvent(message, { type: "chart", data: { ...SPEC, base_value: 1 } });
    expect(message.charts?.map((c) => c.kind)).toEqual(["price", "scenario"]);
  });
});
