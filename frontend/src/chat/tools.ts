/** Human-friendly labels and summaries for MCP tools shown in the timeline. */

const LABELS: Record<string, string> = {
  search_symbol: "Find ticker",
  get_quote: "Latest quote",
  get_price_history: "Price history",
  ping: "Connectivity check",
};

export function toolLabel(name: string): string {
  if (LABELS[name]) return LABELS[name];
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

function scalar(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

/** "NVDA · 1mo · 1d" from the tool arguments. */
export function describeArguments(args: Record<string, unknown>): string {
  return Object.values(args ?? {})
    .map(scalar)
    .filter((value): value is string => value !== null)
    .join(" · ");
}

function humanKey(key: string): string {
  return key.replace(/_/g, " ");
}

/** A one-line view of the tool result preview sent by the API. */
export function describePreview(preview: unknown, maxItems = 4): string {
  if (preview === null || preview === undefined) return "";
  if (typeof preview !== "object") return String(preview).slice(0, 160);

  const record = preview as Record<string, unknown>;
  const parts: string[] = [];

  if (typeof record.count === "number" && Array.isArray(record.first)) {
    parts.push(`${record.count} result${record.count === 1 ? "" : "s"}`);
    const names = record.first
      .map((item) => {
        if (item && typeof item === "object") {
          const entry = item as Record<string, unknown>;
          return scalar(entry.symbol) ?? scalar(entry.name);
        }
        return scalar(item);
      })
      .filter((value): value is string => value !== null);
    if (names.length) parts.push(names.join(", "));
    return parts.join(": ");
  }

  for (const [key, value] of Object.entries(record)) {
    if (key === "counts") continue;
    const text = scalar(value);
    if (text !== null) parts.push(`${humanKey(key)}: ${text}`);
    if (parts.length >= maxItems) break;
  }
  const counts = record.counts;
  if (counts && typeof counts === "object") {
    for (const [key, value] of Object.entries(counts as Record<string, unknown>)) {
      if (typeof value === "number") parts.push(`${value} ${humanKey(key)}`);
    }
  }
  return parts.join(" · ");
}

/** Dates as "12 Nov 2026"; date-times also get the time. Unknown text is returned as is. */
export function formatAsOf(value: string | null | undefined): string {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
