import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

function mockFetch(response: Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(() => response));
}

describe("App system status", () => {
  it("shows every service from /api/health", async () => {
    mockFetch(
      Promise.resolve(
        new Response(
          JSON.stringify({
            status: "ok",
            version: "0.1.0",
            environment: "test",
            services: { api: "ok", postgres: "ok", redis: "ok", mcp_server: "ok" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<App />);

    expect(await screen.findByText("postgres")).toBeInTheDocument();
    expect(screen.getByText("mcp_server")).toBeInTheDocument();
    expect(screen.getByText(/API v0\.1\.0/)).toBeInTheDocument();
  });

  it("shows an error when the API cannot be reached", async () => {
    mockFetch(Promise.reject(new Error("Network down")));

    render(<App />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(screen.getByText(/Network down/)).toBeInTheDocument();
  });
});
