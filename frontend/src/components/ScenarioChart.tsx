/**
 * Projected revenue per scenario (SCRUM-31), drawn with Recharts, with the case table and
 * a text summary for screen readers. The lines draw in one case after another.
 */
import { TrendingUpIcon } from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { axisStyle, entry, TOOLTIP_STYLE } from "../charts/rechartsTheme";
import {
  caseColor,
  compactUsd,
  describeScenario,
  scenarioRows,
  signedPct,
  withFan,
} from "../charts/scenario";
import { formatAsOf } from "../chat/tools";
import type { ScenarioChartSpec } from "../chat/types";
import { cn } from "../lib/utils";
import { useAnimate, useSettings } from "../settings/context";
import ChartFrame, { ChartFoot } from "./ChartFrame";
import DetailChips from "./DetailChips";

function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

export default function ScenarioChart({ spec }: { spec: ScenarioChartSpec }) {
  const animate = useAnimate();
  const { resolvedTheme } = useSettings();
  const axis = axisStyle(resolvedTheme);
  const rows = scenarioRows(spec);
  const title = `${spec.name ?? spec.symbol} (${spec.symbol}), projected revenue`;
  const summary = describeScenario(spec);
  const finalYear = spec.table[0]?.final_year;
  const gradient = `fan-${spec.symbol}`;

  return (
    <ChartFrame
      title={title}
      icon={<TrendingUpIcon />}
      subtitle={`${spec.series.map((s) => s.name).join(", ")} · ${spec.base_year}–${finalYear}`}
    >
      <div className="px-2" aria-hidden="true">
        <ResponsiveContainer width="100%" height={270}>
          <ComposedChart data={withFan(rows)} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={axis.grid} vertical={false} />
            <XAxis dataKey="year" tick={axis.tick} axisLine={false} tickLine={false} />
            <YAxis
              tickFormatter={(value: number) => compactUsd(value)}
              tick={axis.tick}
              axisLine={false}
              tickLine={false}
              width={56}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name) => [`${compactUsd(Number(value))} USD`, String(name)]}
              labelFormatter={(label) => `Fiscal year ${label}`}
            />
            <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
            {rows.some((row) => "bear" in row && "bull" in row) && (
              <Area
                dataKey="range"
                name="bear to bull"
                stroke="none"
                fill={`url(#${gradient})`}
                legendType="none"
                tooltipType="none"
                {...entry(animate)}
              />
            )}
            {spec.series.map((series, index) => (
              <Line
                key={series.name}
                type="monotone"
                dataKey={series.name}
                stroke={caseColor(series.name, index)}
                strokeWidth={2.5}
                strokeDasharray={series.name === "bear" ? "5 4" : undefined}
                dot={{ r: 3, strokeWidth: 0, fill: caseColor(series.name, index) }}
                activeDot={{ r: 5 }}
                {...entry(animate, index + 1)}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="sr-only">{summary}</p>

      <div className="mx-4 my-3 overflow-x-auto rounded-lg border border-border scrollbar-thin">
        <table className="w-full text-sm">
          <caption className="sr-only">Scenario assumptions and results</caption>
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium [&>th]:whitespace-nowrap">
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
              <tr
                key={row.case}
                className={cn(
                  "border-t border-border [&>td]:px-3 [&>td]:py-2 [&>td]:text-right [&>td]:font-mono [&>td]:tabular-nums",
                  animate && "animate-fade-up",
                )}
                style={animate ? { animationDelay: `${300 + index * 120}ms` } : undefined}
              >
                <th
                  scope="row"
                  className="px-3 py-2 text-left font-medium whitespace-nowrap capitalize"
                >
                  <span
                    className="mr-2 inline-block size-2.5 rounded-full align-middle"
                    style={{ background: caseColor(row.case, index) }}
                    aria-hidden="true"
                  />
                  {row.case}
                </th>
                <td>{pct(row.revenue_growth)}</td>
                <td>{pct(row.net_margin)}</td>
                <td>{pct(row.discount_rate)}</td>
                <td>{compactUsd(row.final_revenue)}</td>
                <td>{row.final_eps.toFixed(2)}</td>
                <td className="font-semibold">{row.value_per_share.toFixed(2)}</td>
                <td
                  className={cn(
                    row.vs_price_pct !== null && row.vs_price_pct > 0 && "text-up",
                    row.vs_price_pct !== null && row.vs_price_pct < 0 && "text-down",
                  )}
                >
                  {signedPct(row.vs_price_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <DetailChips sources={spec.sources} assumptions={spec.assumptions} />
      <ChartFoot>
        {spec.source}
        {spec.as_of ? `, price as of ${formatAsOf(spec.as_of)}` : ""}. Values in USD. A projection
        from the listed assumptions, not a forecast.
      </ChartFoot>
    </ChartFrame>
  );
}
