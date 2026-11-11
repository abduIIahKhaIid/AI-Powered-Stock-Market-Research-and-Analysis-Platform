import { useEffect, useState } from "react";

type Health = {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  services: Record<string, string>;
};

const REFRESH_MS = 10_000;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as Health;
        if (!cancelled) {
          setHealth(body);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setHealth(null);
          setError(err instanceof Error ? err.message : "Request failed");
        }
      } finally {
        if (!cancelled) setCheckedAt(new Date());
      }
    }

    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main className="page">
      <header>
        <h1>Stock Research Assistant</h1>
        <p className="muted">NASDAQ research with sources on every number. Chat arrives in SCRUM-35.</p>
      </header>

      <section className="card" aria-live="polite">
        <div className="card-head">
          <h2>System status</h2>
          {health && <span className={`pill ${health.status}`}>{health.status}</span>}
          {error && <span className="pill degraded">API unreachable</span>}
        </div>

        {error && <p className="error">Could not reach the API: {error}</p>}

        {health && (
          <table>
            <thead>
              <tr>
                <th>Service</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(health.services).map(([name, value]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td className={value === "ok" ? "ok-text" : "error"}>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <p className="muted small">
          {health && `API v${health.version} (${health.environment}). `}
          {checkedAt && `Last checked ${checkedAt.toLocaleTimeString()}.`}
        </p>
      </section>
    </main>
  );
}
