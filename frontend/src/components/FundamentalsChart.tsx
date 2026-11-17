/** Revenue, net income, EPS and margins per fiscal period (SCRUM-37), drawn with Recharts. */
import { useState } from "react";
import {
  Bar,
  BarChart,
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
  availableViews,
  describeFundamentals,
  fundamentalsCsv,
  periodLabel,
  VIEWS,
  type FundamentalsView,
} from "../charts/fundamentals";
import { compactUsd } from "../charts/scenario";
import { formatAsOf } from "../chat/tools";
import type { FundamentalsSpec } from "../chat/types";
import DetailChips from "./DetailChips";
import ExportCsv from "./ExportCsv";

const COLORS = {
  revenue: "#2563eb",
  net: "#0d6e4f",
  eps: "#9333ea",
  gross: "#2563eb",
  op: "#d97706",
};

export default function FundamentalsChart({ spec }: { spec: FundamentalsSpec }) {
  const views = availableViews(spec);
  const [view, setView] = useState<FundamentalsView>(views[0] ?? "income");
  const rows = spec.rows.map((row) => ({ ...row, period: periodLabel(row.end, spec.freq) }));
  const title = `${spec.name ?? spec.symbol} (${spec.symbol}), ${spec.freq === "annual" ? "annual" : "quarterly"} fundamentals`;
  const usd = (value: unknown) => [`${compactUsd(Number(value))} USD`];

  return (
    <figure className="price-chart fundamentals-chart">
      <div className="chart-head">
        <figcaption className="chart-title">{title}</figcaption>
        {views.length > 1 && (
          <div className="chart-periods" role="group" aria-label="Chart">
            {VIEWS.filter((v) => views.includes(v.key)).map((v) => (
              <button
                key={v.key}
                type="button"
                className="chip"
                aria-pressed={view === v.key}
                onClick={() => setView(v.key)}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="scenario-plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height={240}>
          {view === "margins" ? (
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis unit="%" tick={{ fontSize: 12 }} width={48} />
              <Tooltip
                formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
              />
              <Legend />
              <Line
                dataKey="gross_margin"
                name="Gross margin"
                stroke={COLORS.gross}
                dot
                isAnimationActive={false}
              />
              <Line
                dataKey="operating_margin"
                name="Operating margin"
                stroke={COLORS.op}
                dot
                isAnimationActive={false}
              />
              <Line
                dataKey="net_margin"
                name="Net margin"
                stroke={COLORS.net}
                dot
                isAnimationActive={false}
              />
            </LineChart>
          ) : view === "eps" ? (
            <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} width={48} />
              <Tooltip formatter={(value) => [`${Number(value).toFixed(2)} USD`, "Diluted EPS"]} />
              <Bar
                dataKey="eps_diluted"
                name="Diluted EPS"
                fill={COLORS.eps}
                isAnimationActive={false}
              />
            </BarChart>
          ) : (
            <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis
                tickFormatter={(value: number) => compactUsd(value)}
                tick={{ fontSize: 12 }}
                width={56}
              />
              <Tooltip formatter={(value, name) => [usd(value)[0], String(name)]} />
              <Legend />
              <Bar
                dataKey="revenue"
                name="Revenue"
                fill={COLORS.revenue}
                isAnimationActive={false}
              />
              <Bar
                dataKey="net_income"
                name="Net income"
                fill={COLORS.net}
                isAnimationActive={false}
              />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <p className="visually-hidden">{describeFundamentals(spec)}</p>

      <details className="chart-data">
        <summary>Data table</summary>
        <div className="table-wrap">
          <table className="scenario-table">
            <thead>
              <tr>
                <th scope="col">Period</th>
                <th scope="col">Revenue</th>
                <th scope="col">Net income</th>
                <th scope="col">EPS</th>
                <th scope="col">Gross margin</th>
                <th scope="col">Net margin</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.end}>
                  <th scope="row">{row.period}</th>
                  <td className="num">{row.revenue != null ? compactUsd(row.revenue) : "–"}</td>
                  <td className="num">
                    {row.net_income != null ? compactUsd(row.net_income) : "–"}
                  </td>
                  <td className="num">
                    {row.eps_diluted != null ? row.eps_diluted.toFixed(2) : "–"}
                  </td>
                  <td className="num">
                    {row.gross_margin != null ? `${row.gross_margin.toFixed(1)}%` : "–"}
                  </td>
                  <td className="num">
                    {row.net_margin != null ? `${row.net_margin.toFixed(1)}%` : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <DetailChips sources={spec.sources} assumptions={spec.assumptions} />
      <ExportCsv
        label={`${spec.symbol} fundamentals`}
        filename={`${spec.symbol}-fundamentals.csv`}
        rows={fundamentalsCsv(spec)}
      />
      <p className="chart-foot">
        {spec.source}
        {spec.as_of ? `, latest filing ${formatAsOf(spec.as_of)}` : ""}. Values in USD.
      </p>
    </figure>
  );
}
