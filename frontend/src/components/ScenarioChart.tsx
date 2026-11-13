/**
 * Projected revenue per scenario (SCRUM-31), drawn with Recharts, with the case table and
 * a text summary for screen readers.
 */
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  caseColor,
  compactUsd,
  describeScenario,
  scenarioRows,
  signedPct,
} from "../charts/scenario";
import { formatAsOf } from "../chat/tools";
import type { ScenarioChartSpec } from "../chat/types";

function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

export default function ScenarioChart({ spec }: { spec: ScenarioChartSpec }) {
  const rows = scenarioRows(spec);
  const title = `${spec.name ?? spec.symbol} (${spec.symbol}), projected revenue`;
  const summary = describeScenario(spec);
  const finalYear = spec.table[0]?.final_year;

  return (
    <figure className="price-chart scenario-chart">
      <figcaption className="chart-title">
        {title}
        <span className="chart-subtitle">
          {spec.series.map((s) => s.name).join(", ")} · {spec.base_year}–{finalYear}
        </span>
      </figcaption>

      <div className="scenario-plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#eef0f3" vertical={false} />
            <XAxis dataKey="year" tick={{ fontSize: 12 }} />
            <YAxis
              tickFormatter={(value: number) => compactUsd(value)}
              tick={{ fontSize: 12 }}
              width={56}
            />
            <Tooltip
              formatter={(value) => [`${compactUsd(Number(value))} USD`]}
              labelFormatter={(label) => `Fiscal year ${label}`}
            />
            <Legend />
            {spec.series.map((series, index) => (
              <Line
                key={series.name}
                type="monotone"
                dataKey={series.name}
                stroke={caseColor(series.name, index)}
                strokeWidth={2}
                strokeDasharray={series.name === "bear" ? "5 4" : undefined}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="visually-hidden">{summary}</p>

      <div className="table-wrap">
        <table className="scenario-table">
          <caption className="visually-hidden">Scenario assumptions and results</caption>
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Revenue growth</th>
              <th scope="col">Net margin</th>
              <th scope="col">Discount rate</th>
              <th scope="col">Revenue {finalYear}</th>
              <th scope="col">EPS {finalYear}</th>
              <th scope="col">Value per share</th>
              <th scope="col">vs price{spec.price ? ` (${spec.price.toFixed(2)})` : ""}</th>
            </tr>
          </thead>
          <tbody>
            {spec.table.map((row, index) => (
              <tr key={row.case}>
                <th scope="row">
                  <span
                    className="case-swatch"
                    style={{ background: caseColor(row.case, index) }}
                    aria-hidden="true"
                  />
                  {row.case}
                </th>
                <td className="num">{pct(row.revenue_growth)}</td>
                <td className="num">{pct(row.net_margin)}</td>
                <td className="num">{pct(row.discount_rate)}</td>
                <td className="num">{compactUsd(row.final_revenue)}</td>
                <td className="num">{row.final_eps.toFixed(2)}</td>
                <td className="num">{row.value_per_share.toFixed(2)}</td>
                <td className="num">{signedPct(row.vs_price_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="chart-foot">
        {spec.source}
        {spec.as_of ? `, price as of ${formatAsOf(spec.as_of)}` : ""}. Values in USD. A projection
        from the listed assumptions, not a forecast.
      </p>
    </figure>
  );
}
