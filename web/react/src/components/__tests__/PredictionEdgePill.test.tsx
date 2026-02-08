import { render, screen } from "@testing-library/react";
import PredictionEdgePill from "../PredictionEdgePill";

describe("PredictionEdgePill", () => {
  it("renders strong_yes stance with edge", () => {
    render(
      <PredictionEdgePill
        stance="strong_yes"
        edge={0.12}
        swarmProb={0.72}
        marketProb={0.60}
        confidence={0.85}
      />
    );
    const pill = screen.getByTestId("prediction-edge-pill");
    expect(pill).toBeInTheDocument();
    expect(pill.textContent).toContain("Strong YES");
    expect(pill.textContent).toContain("12.0%");
  });

  it("renders weak_no stance", () => {
    render(
      <PredictionEdgePill
        stance="weak_no"
        edge={-0.05}
        swarmProb={0.45}
        marketProb={0.50}
        confidence={0.6}
      />
    );
    const pill = screen.getByTestId("prediction-edge-pill");
    expect(pill.textContent).toContain("Weak NO");
  });

  it("renders neutral stance", () => {
    render(
      <PredictionEdgePill
        stance="neutral"
        edge={0.01}
        swarmProb={0.51}
        marketProb={0.50}
        confidence={0.5}
      />
    );
    const pill = screen.getByTestId("prediction-edge-pill");
    expect(pill.textContent).toContain("Neutral");
  });

  it("renders edge bar when showBar is true", () => {
    render(
      <PredictionEdgePill
        stance="strong_yes"
        edge={0.15}
        swarmProb={0.75}
        marketProb={0.60}
        confidence={0.9}
        showBar
      />
    );
    const pill = screen.getByTestId("prediction-edge-pill");
    expect(pill.textContent).toContain("Mkt 60%");
    expect(pill.textContent).toContain("Swarm 75%");
  });

  it("does not render edge bar by default", () => {
    render(
      <PredictionEdgePill
        stance="strong_yes"
        edge={0.15}
        swarmProb={0.75}
        marketProb={0.60}
        confidence={0.9}
      />
    );
    const pill = screen.getByTestId("prediction-edge-pill");
    expect(pill.textContent).not.toContain("Mkt ");
  });
});
