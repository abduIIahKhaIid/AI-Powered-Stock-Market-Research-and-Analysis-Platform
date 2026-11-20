/**
 * Revenue, net income, EPS and margins per fiscal period (SCRUM-37), drawn with Recharts.
 * Bars grow up from the axis and lines draw in when the chart appears or the view changes.
 */
import { BarChart3Icon, ChevronRightIcon } from "lucide-react";
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
import { axisStyle, entry, TOOLTIP_STYLE } from "../charts/rechartsTheme";
import { compactUsd } from "../charts/scenario";
import { formatAsOf } from "../chat/tools";
import type { FundamentalsSpec } from "../chat/types";
import { cn } from "../lib/utils";
import { useAnimate, useSettings } from "../settings/context";
import ChartFrame, { ChartFoot } from "./ChartFrame";
import DetailChips from "./DetailChips";
import ExportCsv from "./ExportCsv";

const COLORS = {
  revenue: "#6366f1",
  net: "#10b981",
  eps: "#a855f7",
  gross: "#6366f1",
  op: "#f59e0b",
};

export default function FundamentalsChart({ spec }: { spec: FundamentalsSpec }) {
  const views = availableViews(spec);
  const [view, setView] = useState<FundamentalsView>(views[0] ?? "income");
  const animate = useAnimate();
  const { resolvedTheme } = useSettings();
  const axis = axisStyle(resolvedTheme);
  const rows = spec.rows.map((row) => ({ ...row, period: periodLabel(row.end, spec.freq) }));
  const title = `${spec.name ?? spec.symbol} (${spec.symbol}), ${spec.freq === "annual" ? "annual" : "quarterly"} fundamentals`;
  const usd = (value: unknown) => `${compactUsd(Number(value))} USD`;
  const common = {
    data: rows,
    margin: { top: 8, right: 16, bottom: 0, left: 4 },
  };
  const xAxis = <XAxis dataKey="period" tick={axis.tick} axisLine={false} tickLine={false} />;

  return (
    <ChartFrame
      title={title}
      icon={<BarChart3Icon />}
      subtitle={`${rows.length} ${spec.freq === "annual" ? "fiscal years" : "quarters"} from SEC filings`}
      actions={
        views.length > 1 && (
          <div
            className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
            role="group"
            aria-label="Chart"
          >
            {VIEWS.filter((v) => views.includes(v.key)).map((v) => (
              <button
                key={v.key}
                type="button"
                aria-pressed={view === v.key}
                onClick={() => setView(v.key)}
                className={cn(
                  "h-7 cursor-pointer rounded-md px-2.5 text-xs font-medium transition-all",
                  view === v.key
                    ? "bg-card text-foreground shadow-sm ring-1 ring-border/60"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {v.label}
              </button>
            ))}
          </div>
        )
      }
    >
      {/* The key replays the entry animation when the view changes. */}
      <div className="px-2" aria-hidden="true" key={view}>
        <ResponsiveContainer width="100%" height={250}>
          {view === "margins" ? (
            <LineChart {...common}>
              <CartesianGrid stroke={axis.grid} vertical={false} />
              {xAxis}
              <YAxis unit="%" tick={axis.tick} axisLine={false} tickLine={false} width={48} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
              />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              {(
                [
                  ["gross_margin", "Gross margin", COLORS.gross],
                  ["operating_margin", "Operating margin", COLORS.op],
                  ["net_margin", "Net margin", COLORS.net],
                ] as const
              ).map(([key, name, color], index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={name}
                  stroke={color}
                  strokeWidth={2.5}
                  dot={{ r: 3, strokeWidth: 0, fill: color }}
                  activeDot={{ r: 5 }}
                  {...entry(animate, index)}
                />
              ))}
            </LineChart>
          ) : view === "eps" ? (
            <BarChart {...common}>
              <CartesianGrid stroke={axis.grid} vertical={false} />
              {xAxis}
              <YAxis tick={axis.tick} axisLine={false} tickLine={false} width={48} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                cursor={axis.cursor}
                formatter={(value) => [`${Number(value).toFixed(2)} USD`, "Diluted EPS"]}
              />
              <Bar
                dataKey="eps_diluted"
                name="Diluted EPS"
                fill={COLORS.eps}
                radius={[6, 6, 0, 0]}
                maxBarSize={48}
                {...entry(animate)}
              />
            </BarChart>
          ) : (
            <BarChart {...common}>
              <CartesianGrid stroke={axis.grid} vertical={false} />
              {xAxis}
              <YAxis
                tickFormatter={(value: number) => compactUsd(value)}
                tick={axis.tick}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                cursor={axis.cursor}
                formatter={(value, name) => [usd(value), String(name)]}
              />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar
                dataKey="revenue"
                name="Revenue"
                fill={COLORS.revenue}
                radius={[6, 6, 0, 0]}
                maxBarSize={44}
                {...entry(animate)}
              />
              <Bar
                dataKey="net_income"
                name="Net income"
                fill={COLORS.net}
                radius={[6, 6, 0, 0]}
                maxBarSize={44}
                {...entry(animate, 1)}
              />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <p className="sr-only">{describeFundamentals(spec)}</p>

      <details className="group mx-4 my-3 rounded-lg border border-border">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
          <ChevronRightIcon
            className="size-3.5 transition-transform group-open:rotate-90"
            aria-hidden="true"
          />
          Data table
        </summary>
        <div className="overflow-x-auto border-t border-border scrollbar-thin">
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-xs text-muted-foreground">
              <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium">
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
                <tr
                  key={row.end}
                  className="border-t border-border [&>td]:px-3 [&>td]:py-1.5 [&>td]:text-right [&>td]:font-mono [&>td]:tabular-nums"
                >
                  <th scope="row" className="px-3 py-1.5 text-left font-medium">
                    {row.period}
                  </th>
                  <td>{row.revenue != null ? compactUsd(row.revenue) : "–"}</td>
                  <td>{row.net_income != null ? compactUsd(row.net_income) : "–"}</td>
                  <td>{row.eps_diluted != null ? row.eps_diluted.toFixed(2) : "–"}</td>
                  <td>{row.gross_margin != null ? `${row.gross_margin.toFixed(1)}%` : "–"}</td>
                  <td>{row.net_margin != null ? `${row.net_margin.toFixed(1)}%` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <DetailChips sources={spec.sources} assumptions={spec.assumptions}>
        <ExportCsv
          label={`${spec.symbol} fundamentals`}
          filename={`${spec.symbol}-fundamentals.csv`}
          rows={fundamentalsCsv(spec)}
        />
      </DetailChips>
      <ChartFoot>
        {spec.source}
        {spec.as_of ? `, latest filing ${formatAsOf(spec.as_of)}` : ""}. Values in USD.
      </ChartFoot>
    </ChartFrame>
  );
}
