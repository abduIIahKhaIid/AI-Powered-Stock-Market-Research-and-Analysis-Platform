import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GroundingNote } from "./MessageView";

describe("GroundingNote", () => {
  it("confirms verified figures", () => {
    render(<GroundingNote grounding={{ status: "verified", checked: 3 }} />);
    expect(screen.getByText("Checked: 3 figures match the source data.")).toBeInTheDocument();
  });

  it("names the corrected figure", () => {
    render(<GroundingNote grounding={{ status: "corrected", checked: 1, flagged: ["2.4%"] }} />);
    expect(screen.getByText(/after the assistant corrected 2\.4%/)).toBeInTheDocument();
  });

  it("shows the removal note", () => {
    const note = "1 figure could not be matched to the source data and was removed: 9.9%.";
    render(
      <GroundingNote grounding={{ status: "removed", checked: 2, removed: ["9.9%"], note }} />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(note);
  });

  it("shows nothing when the answer had no figures", () => {
    const { container } = render(
      <GroundingNote grounding={{ status: "no_figures", checked: 0 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
