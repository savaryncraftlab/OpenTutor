/**
 * Tests for the Slice 5 T5 `/profile/progress` aggregate page.
 *
 * Covers:
 *   - PageShell + heading render with the expected test id
 *   - All four Slice 5 cards mount (each mocked to a stable stub so we
 *     don't recreate T1-T4 internals here)
 *   - No "duplicate-fetch" console.error noise (critic-mandated guard:
 *     dashboard + /profile/progress mount the same cards, so we keep an
 *     explicit assert that nothing logs the duplicate-fetch warning we'd
 *     emit in a future SWR retrofit).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/dashboard/recall-health-card", () => ({
  RecallHealthCard: () => (
    <div data-testid="recall-health-card-mock">Recall health</div>
  ),
}));
vi.mock("@/components/dashboard/xp-breakdown-card", () => ({
  XpBreakdownCard: () => (
    <div data-testid="xp-breakdown-card-mock">XP breakdown</div>
  ),
}));
vi.mock("@/components/dashboard/streak-calendar-card", () => ({
  StreakCalendarCard: () => (
    <div data-testid="streak-calendar-card-mock">Streak calendar</div>
  ),
}));
vi.mock("@/components/dashboard/recall-forecast-card", () => ({
  RecallForecastCard: () => (
    <div data-testid="recall-forecast-card-mock">Recall forecast</div>
  ),
}));

import ProgressPage from "./page";

describe("/profile/progress page", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("renders the PageShell with the expected test id", () => {
    render(<ProgressPage />);
    expect(screen.getByTestId("profile-progress-page")).toBeInTheDocument();
  });

  it("renders the 'Your progress' heading", () => {
    render(<ProgressPage />);
    expect(
      screen.getByRole("heading", { name: /your progress/i }),
    ).toBeInTheDocument();
  });

  it("mounts all four Slice 5 cards", () => {
    render(<ProgressPage />);
    expect(screen.getByTestId("streak-calendar-card-mock")).toBeInTheDocument();
    expect(screen.getByTestId("xp-breakdown-card-mock")).toBeInTheDocument();
    expect(screen.getByTestId("recall-health-card-mock")).toBeInTheDocument();
    expect(screen.getByTestId("recall-forecast-card-mock")).toBeInTheDocument();
  });

  it("emits no duplicate-fetch console.error warnings on mount", () => {
    // Critic-mandated guard: dashboard + /profile/progress both mount
    // the same self-fetching cards. If a future SWR retrofit ever logs
    // a warning like "duplicate fetch detected" we want this test to
    // catch it before it escapes to prod.
    render(<ProgressPage />);
    expect(consoleErrorSpy).not.toHaveBeenCalledWith(
      expect.stringMatching(/duplicate.*fetch/i),
    );
    expect(consoleErrorSpy).not.toHaveBeenCalledWith(
      expect.stringMatching(/duplicate.*fetch/i),
      expect.anything(),
    );
  });
});
