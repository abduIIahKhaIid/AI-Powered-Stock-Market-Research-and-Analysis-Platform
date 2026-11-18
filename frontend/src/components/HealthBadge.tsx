import { useEffect, useState } from "react";
import { cn } from "../lib/utils";

type Health = { status: "ok" | "degraded"; services: Record<string, string> };

const REFRESH_MS = 30_000;

/** Small API status line for the sidebar footer. */
export default function HealthBadge() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as Health;
        if (!cancelled) {
          setHealth(body);
          setUnreachable(false);
        }
      } catch {
        if (!cancelled) {
          setHealth(null);
          setUnreachable(true);
        }
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!health && !unreachable) return null;
  const down = health
    ? Object.entries(health.services)
        .filter(([, value]) => value !== "ok")
        .map(([name]) => name)
    : [];
  const state = unreachable ? "down" : health?.status === "ok" ? "ok" : "degraded";
  const text = unreachable
    ? "API unreachable"
    : state === "ok"
      ? "All services up"
      : `Degraded: ${down.join(", ") || "check /health"}`;

  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
      <span className="relative flex size-2" aria-hidden="true">
        {state === "ok" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-up opacity-50" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            state === "ok" && "bg-up",
            state === "degraded" && "bg-warning",
            state === "down" && "bg-down",
          )}
        />
      </span>
      {text}
    </p>
  );
}
