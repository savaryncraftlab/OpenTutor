/**
 * Tests for <StreakCalendarCard> (Slice 5 T3).
 *
 * Covers loading / loaded mixed-status / no-data / error paths plus the
 * footer freeze-counter copy. The card self-fetches via
 * `getStreakCalendar` — we mock that module so every test deterministically
 * picks a state without hitting the network.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getStreakCalendarMock = vi.fn();

vi.mock("@/lib/api/gamification", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/gamification")
  >("@/lib/api/gamification");
  return {
    ...actual,
    getStreakCalendar: () => getStreakCalendarMock(),
  };
});

import { StreakCalendarCard } from "./streak-calendar-card";

describe("<StreakCalendarCard>", () => {
  beforeEach(() => {
    getStreakCalendarMock.mockReset();
  });

  it("renders loading skeleton while the fetch is in flight", async () => {
    // Never-resolving promise so the loading state sticks for the assertion.
    getStreakCalendarMock.mockReturnValue(new Promise(() => {}));
    render(<StreakCalendarCard />);

    expect(screen.getByTestId("streak-calendar-card")).toBeInTheDocument();
    expect(
      screen.getByTestId("streak-calendar-card-skeleton"),
    ).toBeInTheDocument();
    // No grid yet — only skeleton.
    expect(
      screen.queryByTestId("streak-calendar-card-grid"),
    ).not.toBeInTheDocument();
  });

  it("renders mixed-status tiles + streak title + footer counter on success", async () => {
    getStreakCalendarMock.mockResolvedValue({
      today: "2026-04-22",
      current_streak: 3,
      freezes_left_this_week: 2,
      days: [
        { date: "2026-04-20", status: "broken" },
        { date: "2026-04-21", status: "freeze" },
        { date: "2026-04-22", status: "maintained" },
      ],
    });
    render(<StreakCalendarCard />);

    await waitFor(() =>
      expect(screen.getByTestId("streak-calendar-card-grid")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("streak-calendar-card-title")).toHaveTextContent(
      "Streak — 3 days",
    );
    // Each status renders with its own data-status attribute so the
    // bucket function's behaviour is observable from the DOM.
    expect(
      screen.getByTestId("streak-calendar-tile-2026-04-22"),
    ).toHaveAttribute("data-status", "maintained");
    expect(
      screen.getByTestId("streak-calendar-tile-2026-04-21"),
    ).toHaveAttribute("data-status", "freeze");
    expect(
      screen.getByTestId("streak-calendar-tile-2026-04-20"),
    ).toHaveAttribute("data-status", "broken");
    expect(screen.getByTestId("streak-calendar-card-footer")).toHaveTextContent(
      "freeze tokens left this week: 2 / 3",
    );
  });

  it("renders the no-data state (all broken + grace today) for a fresh account", async () => {
    getStreakCalendarMock.mockResolvedValue({
      today: "2026-04-22",
      current_streak: 0,
      freezes_left_this_week: 3,
      days: [
        { date: "2026-04-20", status: "broken" },
        { date: "2026-04-21", status: "broken" },
        { date: "2026-04-22", status: "grace" },
      ],
    });
    render(<StreakCalendarCard />);

    await waitFor(() =>
      expect(screen.getByTestId("streak-calendar-card-title")).toHaveTextContent(
        "Streak — 0 days",
      ),
    );
    expect(
      screen.getByTestId("streak-calendar-tile-2026-04-22"),
    ).toHaveAttribute("data-status", "grace");
    expect(screen.getByTestId("streak-calendar-card-footer")).toHaveTextContent(
      "3 / 3",
    );
  });

  it("renders the calm error subline when the fetch rejects", async () => {
    getStreakCalendarMock.mockRejectedValue({
      status: 500,
      message: "boom",
    });
    render(<StreakCalendarCard />);

    await waitFor(() =>
      expect(
        screen.getByTestId("streak-calendar-card-error"),
      ).toBeInTheDocument(),
    );
    // No grid in error state.
    expect(
      screen.queryByTestId("streak-calendar-card-grid"),
    ).not.toBeInTheDocument();
  });

  it("uses the singular 'day' grammar when current_streak === 1", async () => {
    getStreakCalendarMock.mockResolvedValue({
      today: "2026-04-22",
      current_streak: 1,
      freezes_left_this_week: 3,
      days: [{ date: "2026-04-22", status: "maintained" }],
    });
    render(<StreakCalendarCard />);

    await waitFor(() =>
      expect(
        screen.getByTestId("streak-calendar-card-title"),
      ).toHaveTextContent("Streak — 1 day"),
    );
  });
});
