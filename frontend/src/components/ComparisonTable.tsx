/** compare_stocks as a sortable table with sources, assumptions and CSV export (SCRUM-37). */
import { useState } from "react";
import { formatMetric } from "../charts/fundamentals";
import { formatAsOf } from "../chat/tools";
import type { ComparisonSpec } from "../chat/types";
import DetailChips from "./DetailChips";
import ExportCsv from "./ExportCsv";

type Sort = { key: string; dir: "ascending" | "descending" } | null;

export default function ComparisonTable({ spec }: { spec: ComparisonSpec }) {
  const [sort, setSort] = useState<Sort>(null);
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
    <figure className="price-chart comparison-table">
      <figcaption className="chart-title">Comparison: {spec.symbols.join(", ")}</figcaption>
      <div className="table-wrap">
        <table className="scenario-table">
          <caption className="visually-hidden">
            Metrics per company. Select a column heading to sort.
          </caption>
          <thead>
            <tr>
              <th scope="col" aria-sort={ariaSort("symbol")}>
                <button type="button" className="sort-button" onClick={() => sortBy("symbol")}>
                  Symbol
                </button>
              </th>
              {spec.metrics.map((metric) => (
                <th
                  key={metric.key}
                  scope="col"
                  aria-sort={ariaSort(metric.key)}
                  title={metric.formula}
                >
                  <button type="button" className="sort-button" onClick={() => sortBy(metric.key)}>
                    {metric.label}
                    <span className="sort-mark" aria-hidden="true">
                      {sort?.key === metric.key ? (sort.dir === "ascending" ? " ▲" : " ▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.map((symbol) => (
              <tr key={symbol}>
                <th scope="row">{symbol}</th>
                {spec.metrics.map((metric) => {
                  const cell = spec.values[symbol]?.[metric.key];
                  return (
                    <td key={metric.key} className="num" title={cell?.error ?? undefined}>
                      {formatMetric(cell?.value, metric)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DetailChips sources={spec.sources} assumptions={spec.assumptions} />
      <ExportCsv
        label={`the comparison of ${spec.symbols.join(", ")}`}
        filename={`comparison-${spec.symbols.join("-")}.csv`}
        rows={csv}
      />
      <p className="chart-foot">
        {spec.source}
        {spec.as_of ? `, as of ${formatAsOf(spec.as_of)}` : ""}.
      </p>
    </figure>
  );
}
