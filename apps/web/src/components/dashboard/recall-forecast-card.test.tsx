/**
 * Tests for `<RecallForecastCard>` (Slice 5 T4).
 *
 * Four states from the spec:
 *   1. Loaded with mixed bucket data (today/this-week/next-week populated).
 *   2. Today-due variant — exercises the urgency pill mapping.
 *   3. Loaded empty — must show "from flashcard reviews — nothing scheduled".
 *   4. Error — must surface the retry control.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RecallForecastCard } from "./recall-forecast-card";
import type { RecallForecast } from "@/lib/api/progress";

const getRecallForecastMock = vi.fn();
vi.mock("@/lib/api/progress", async () => ({
  getRecallForecast: (...args: unknown[]) => getRecallForecastMock(...args),
}));

function makeForecast(overrides: Partial<RecallForecast> = {}): RecallForecast {
  return {
    today_due: 0,
    this_week_due: 0,
    next_week_due: 0,
    expected_forgotten: 0,
    urgency: "none",
    recommendation: "No review needed right now",
    scope: "flashcards",
    ...overrides,
  };
}

describe("<RecallForecastCard>", () => {
  beforeEach(() => {
    getRecallForecastMock.mockReset();
  });

  it("renders today/this-week/next-week numbers when data loads", async () => {
    getRecallForecastMock.mockResolvedValue(
      makeForecast({
        today_due: 3,
        this_week_due: 12,
        next_week_due: 8,
        urgency: "low",
        recommendation: "A few items due — consider a quick review",
      }),
    );
    render(<RecallForecastCard />);

    await waitFor(() => {
      expect(screen.getByTestId("recall-forecast-card-today")).toHaveTextContent(
        "3",
      );
    });
    expect(
      screen.getByTestId("recall-forecast-card-breakdown"),
    ).toHaveTextContent("12 this week · 8 next week");
    expect(screen.getByTestId("recall-forecast-card-scope")).toHaveTextContent(
      "from flashcard reviews",
    );
    // Subline must NOT include the empty-state suffix when data exists.
    expect(
      screen.getByTestId("recall-forecast-card-scope").textContent,
    ).not.toContain("nothing scheduled");
  });

  it("renders the amber urgency pill mapping for normal/high urgency", async () => {
    getRecallForecastMock.mockResolvedValue(
      makeForecast({
        today_due: 12,
        this_week_due: 47,
        next_week_due: 0,
        urgency: "normal",
        recommendation: "Good time for a review — enough cards for a full session",
      }),
    );
    render(<RecallForecastCard />);

    await waitFor(() => {
      expect(screen.getByTestId("recall-forecast-card-today")).toHaveTextContent(
        "12",
      );
    });
    const pill = screen.getByTestId("recall-forecast-card-urgency");
    expect(pill.getAttribute("data-urgency")).toBe("normal");
    // Amber palette is the spec mapping for normal/high — assert via class.
    expect(pill.className).toMatch(/amber/);
    expect(pill).toHaveTextContent(
      "Good time for a review — enough cards for a full session",
    );
  });

  it("shows the empty-state subline when nothing is due today/this-week", async () => {
    getRecallForecastMock.mockResolvedValue(
      makeForecast({
        today_due: 0,
        this_week_due: 0,
        next_week_due: 0,
        urgency: "none",
        recommendation: "No review needed right now",
      }),
    );
    render(<RecallForecastCard />);

    await waitFor(() => {
      expect(screen.getByTestId("recall-forecast-card-scope")).toBeInTheDocument();
    });
    // Empty-state hard-required by spec acceptance.
    expect(screen.getByTestId("recall-forecast-card-scope")).toHaveTextContent(
      "from flashcard reviews — nothing scheduled",
    );
    expect(screen.getByTestId("recall-forecast-card-today")).toHaveTextContent(
      "0",
    );
  });

  it("shows the error state with retry button when the request fails", async () => {
    getRecallForecastMock.mockRejectedValue(new Error("boom"));
    render(<RecallForecastCard />);

    await waitFor(() => {
      expect(
        screen.getByTestId("recall-forecast-card-error"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("recall-forecast-card-retry"),
    ).toBeInTheDocument();
  });
});
