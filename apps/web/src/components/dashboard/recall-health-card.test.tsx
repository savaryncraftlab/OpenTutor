/**
 * Tests for <RecallHealthCard> (Slice 5 T1).
 *
 * Critic-mandated assertion: in BOTH the loaded-data state and the
 * empty `total_tracked === 0` state, the card MUST surface
 * "from flashcard reviews" — the metric is flashcard-scoped today and
 * the user must never be misled into thinking path-room missions are
 * counted. Both branches assert the subline text explicitly.
 */
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { RecallHealthCard } from "./recall-health-card";
import type { RecallHealth } from "@/lib/api/progress";

function loaded(data: RecallHealth) {
  return () => Promise.resolve(data);
}

describe("<RecallHealthCard>", () => {
  it("renders big % number, subline, and counts when data present", async () => {
    render(
      <RecallHealthCard
        fetcher={loaded({
          total_tracked: 14,
          average_retrievability: 0.87,
          at_risk_count: 3,
          well_known_count: 8,
          scope: "flashcards",
        })}
      />,
    );

    const value = await screen.findByTestId("recall-health-card-value");
    expect(value).toHaveTextContent("87%");

    // Critic-mandated: "from flashcard reviews" is present in the
    // loaded-data branch.
    const subline = screen.getByTestId("recall-health-card-subline");
    expect(subline).toHaveTextContent("from flashcard reviews");
    expect(screen.getByText(/from flashcard reviews/i)).toBeInTheDocument();

    expect(screen.getByTestId("recall-health-card-counts")).toHaveTextContent(
      "3 at risk · 8 well-known",
    );
  });

  it("renders empty state with em-dash and flashcards subline when total_tracked is 0", async () => {
    render(
      <RecallHealthCard
        fetcher={loaded({
          total_tracked: 0,
          average_retrievability: 0,
          at_risk_count: 0,
          well_known_count: 0,
          scope: "flashcards",
        })}
      />,
    );

    const value = await screen.findByTestId("recall-health-card-value");
    expect(value).toHaveTextContent("—");

    // Critic-mandated: explicitly assert "from flashcard reviews" is
    // visible AND the start-a-flashcard-session hint is present in the
    // empty state.
    const subline = screen.getByTestId("recall-health-card-subline");
    expect(subline).toHaveTextContent("from flashcard reviews");
    expect(subline).toHaveTextContent("start a flashcard session");
    expect(screen.getByText(/from flashcard reviews/i)).toBeInTheDocument();

    // No counts row in the empty state — keeps the empty card calm.
    expect(
      screen.queryByTestId("recall-health-card-counts"),
    ).not.toBeInTheDocument();
  });

  it("rounds the average_retrievability to a whole percentage", async () => {
    render(
      <RecallHealthCard
        fetcher={loaded({
          total_tracked: 5,
          average_retrievability: 0.726,
          at_risk_count: 1,
          well_known_count: 2,
          scope: "flashcards",
        })}
      />,
    );

    const value = await screen.findByTestId("recall-health-card-value");
    expect(value).toHaveTextContent("73%");
  });

  it("falls back to em-dash and the flashcards subline on fetch error", async () => {
    render(
      <RecallHealthCard
        fetcher={() => Promise.reject(new Error("boom"))}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("recall-health-card-value"),
      ).toHaveTextContent("—");
    });
    expect(screen.getByTestId("recall-health-card-subline")).toHaveTextContent(
      "from flashcard reviews",
    );
  });
});
