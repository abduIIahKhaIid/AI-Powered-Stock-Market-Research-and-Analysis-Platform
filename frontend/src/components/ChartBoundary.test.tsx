import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { applyEvent, newAssistantMessage } from "../chat/reducer";
import type { AssistantMessage, ChartSpec } from "../chat/types";
import ChartBoundary from "./ChartBoundary";
import MessageView from "./MessageView";

function Broken(): never {
  throw new TypeError("Cannot read properties of undefined (reading 'map')");
}

describe("one broken chart does not blank the app", () => {
  it("replaces a chart that throws with a note", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <div>
        <p>The answer</p>
        <ChartBoundary name="price chart">
          <Broken />
        </ChartBoundary>
      </div>,
    );
    expect(screen.getByText("The answer")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("The price chart could not be shown.");
    error.mockRestore();
  });

  it("skips chart kinds it does not know", () => {
    const message = applyEvent(newAssistantMessage("m", "simple"), {
      type: "chart",
      data: { kind: "heatmap", symbol: "AAPL" } as unknown as ChartSpec,
    });
    expect(message.charts).toBeUndefined();
  });

  it("keeps the answer when a price chart arrives without candles", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const message: AssistantMessage = {
      ...newAssistantMessage("m", "simple"),
      state: "done",
      text: "AAPL closed at 231.50 USD.",
      charts: [{ kind: "price", symbol: "AAPL" } as unknown as ChartSpec],
    };
    render(<MessageView message={message} />);
    expect(screen.getByText("AAPL closed at 231.50 USD.")).toBeInTheDocument();
    expect(await screen.findByRole("note")).toHaveTextContent("price chart could not be shown");
    error.mockRestore();
  });
});
