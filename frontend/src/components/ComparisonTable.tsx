/**
 * compare_stocks as a sortable table with sources, assumptions and CSV export (SCRUM-37).
 * Each number carries a small bar scaled to its column, which grows in when the table appears.
 */
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, Columns3Icon } from "lucide-react";
import { m } from "motion/react";
import { useState } from "react";
import { formatMetric } from "../charts/fundamentals";
import { formatAsOf } from "../chat/tools";
import type { ComparisonSpec } from "../chat/types";
import { cn } from "../lib/utils";
import { useAnimate } from "../settings/context";
import ChartFrame, { ChartFoot } from "./ChartFrame";
import DetailChips from "./DetailChips";
import ExportCsv from "./ExportCsv";

type Sort = { key: string; dir: "ascending" | "descending" } | null;

function SortMark({ dir }: { dir: "ascending" | "descending" | null }) {
  const Icon =
    dir === "ascending" ? ArrowUpIcon : dir === "descending" ? ArrowDownIcon : ArrowUpDownIcon;
  return (
    <Icon
      className={cn("size-3 shrink-0", dir ? "text-primary" : "opacity-0 group-hover:opacity-60")}
      aria-hidden="true"
    />
  );
}

export default function ComparisonTable({ spec }: { spec: ComparisonSpec }) {
  const [sort, setSort] = useState<Sort>(null);
  const animate = useAnimate();
  const value = (symbol: string, key: string) => spec.values[symbol]?.[key]?.value ?? null;

  const symbols = [...spec.symbols];
  if (sort) {
    symbols.sort((a, b) => {
      if (sort.key === "symbol") {
        return sort.dir === "ascending" ? a.localeCompare(b) : b.localeCompare(a);
      }
      const va = value(a, sort.key);
      const vb = value(b, sort.key);
      if (va === null) return 1; // missing values always last
      if (vb === null) return -1;
      return sort.dir === "ascending" ? va - vb : vb - va;
    });
  }

  // The largest absolute value per metric, to scale the bars.
  const peak: Record<string, number> = {};
  for (const metric of spec.metrics) {
    peak[metric.key] = Math.max(
      0,
      ...spec.symbols.map((symbol) => Math.abs(value(symbol, metric.key) ?? 0)),
    );
  }

  function sortBy(key: string) {
    setSort((current) =>
      current?.key === key && current.dir === "descending"
        ? { key, dir: "ascending" }
        : { key, dir: current?.key === key ? "ascending" : "descending" },
    );
  }

  const ariaSort = (key: string) => (sort?.key === key ? sort.dir : "none");
  const csv = [
    ["symbol", ...spec.metrics.map((m) => `${m.key} (${m.unit})`)],
    ...spec.symbols.map((symbol) => [symbol, ...spec.metrics.map((m) => value(symbol, m.key))]),
  ];

  return (
    <ChartFrame
      title={`Comparison: ${spec.symbols.join(", ")}`}
      icon={<Columns3Icon />}
      subtitle={`${spec.metrics.length} metrics · select a column heading to sort`}
    >
      <div className="mx-4 mb-3 overflow-x-auto rounded-lg border border-border scrollbar-thin">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Metrics per company. Select a column heading to sort.
          </caption>
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr>
              <th scope="col" aria-sort={ariaSort("symbol")} className="px-3 py-2 text-left">
                <button
                  type="button"
                  className="group inline-flex cursor-pointer items-center gap-1 font-medium hover:text-foreground"
                  onClick={() => sortBy("symbol")}
                >
                  Symbol
                  <SortMark dir={sort?.key === "symbol" ? sort.dir : null} />
                </button>
              </th>
              {spec.metrics.map((metric) => (
                <th
                  key={metric.key}
                  scope="col"
                  aria-sort={ariaSort(metric.key)}
                  title={metric.formula}
                  className="px-3 py-2 text-right whitespace-nowrap"
                >
                  <button
                    type="button"
                    className="group ml-auto inline-flex cursor-pointer items-center gap-1 font-medium hover:text-foreground"
                    onClick={() => sortBy(metric.key)}
                  >
                    {metric.label}
                    <SortMark dir={sort?.key === metric.key ? sort.dir : null} />
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.map((symbol, row) => (
              <m.tr
                key={symbol}
                layout={animate ? "position" : false}
                initial={animate ? { opacity: 0, x: -8 } : false}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.35, delay: animate ? row * 0.07 : 0 }}
                className="border-t border-border hover:bg-muted/40"
              >
                <th scope="row" className="px-3 py-2 text-left font-semibold">
                  {symbol}
                </th>
                {spec.metrics.map((metric) => {
                  const cell = spec.values[symbol]?.[metric.key];
                  const number = cell?.value ?? null;
                  const width =
                    number !== null && peak[metric.key] > 0
                      ? (Math.abs(number) / peak[metric.key]) * 100
                      : 0;
                  return (
                    <td
                      key={metric.key}
                      title={cell?.error ?? undefined}
                      className="px-3 py-2 text-right font-mono tabular-nums"
                    >
                      <span className="block">{formatMetric(cell?.value, metric)}</span>
                      <span
                        className="mt-1 ml-auto block h-1 w-16 overflow-hidden rounded-full bg-muted"
                        aria-hidden="true"
                      >
                        <m.span
                          className={cn(
                            "ml-auto block h-full rounded-full",
                            number !== null && number < 0 ? "bg-down/70" : "bg-primary/60",
                          )}
                          initial={animate ? { width: 0 } : false}
                          animate={{ width: `${width}%` }}
                          transition={{
                            duration: 0.9,
                            delay: animate ? 0.2 + row * 0.07 : 0,
                            ease: [0.2, 0.8, 0.2, 1],
                          }}
                        />
                      </span>
                    </td>
                  );
                })}
              </m.tr>
            ))}
          </tbody>
        </table>
      </div>
      <DetailChips sources={spec.sources} assumptions={spec.assumptions}>
        <ExportCsv
          label={`the comparison of ${spec.symbols.join(", ")}`}
          filename={`comparison-${spec.symbols.join("-")}.csv`}
          rows={csv}
        />
      </DetailChips>
      <ChartFoot>
        {spec.source}
        {spec.as_of ? `, as of ${formatAsOf(spec.as_of)}` : ""}.
      </ChartFoot>
    </ChartFrame>
  );
}
