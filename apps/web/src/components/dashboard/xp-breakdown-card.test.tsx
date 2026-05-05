/**
 * Tests for `<XpBreakdownCard>` (Slice 5 T2).
 *
 * Covers the five render branches: loading, loaded multi-source, loaded
 * empty (total=0), error, and unknown-source fallback color.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { XpBreakdownCard } from "./xp-breakdown-card";
import type { XpBreakdown } from "@/lib/api/gamification";

const getXpBreakdownMock = vi.fn();
vi.mock("@/lib/api/gamification", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/gamification")>(
      "@/lib/api/gamification",
    );
  return {
    ...actual,
    getXpBreakdown: (...args: unknown[]) => getXpBreakdownMock(...args),
  };
});

function makeBreakdown(overrides: Partial<XpBreakdown> = {}): XpBreakdown {
  return {
    window_days: 7,
    total_xp: 480,
    by_source: [
      { source: "practice_result", xp: 320, count: 32 },
      { source: "room_complete", xp: 100, count: 1 },
      { source: "streak", xp: 60, count: 6 },
    ],
    ...overrides,
  };
}

describe("<XpBreakdownCard>", () => {
  beforeEach(() => {
    getXpBreakdownMock.mockReset();
  });

  it("renders the loading skeleton on initial mount", () => {
    // Pending promise keeps the loading branch mounted for the assertion.
    getXpBreakdownMock.mockReturnValue(new Promise(() => {}));
    render(<XpBreakdownCard />);
    expect(
      screen.getByTestId("xp-breakdown-card-loading"),
    ).toBeInTheDocument();
    // Total number is hidden while loading.
    expect(
      screen.queryByTestId("xp-breakdown-card-total"),
    ).not.toBeInTheDocument();
  });

  it("renders one row per source with color-coded bars on success", async () => {
    getXpBreakdownMock.mockResolvedValue(makeBreakdown());
    render(<XpBreakdownCard />);

    await waitFor(() =>
      expect(screen.getByTestId("xp-breakdown-card-list")).toBeInTheDocument(),
    );

    const rows = screen.getAllByTestId("xp-breakdown-card-row");
    expect(rows).toHaveLength(3);
    // Source order matches the API payload — XP DESC.
    expect(rows[0].getAttribute("data-source")).toBe("practice_result");
    expect(rows[1].getAttribute("data-source")).toBe("room_complete");
    expect(rows[2].getAttribute("data-source")).toBe("streak");

    // Total renders.
    expect(screen.getByTestId("xp-breakdown-card-total")).toHaveTextContent(
      "480 XP",
    );

    // Color tokens come from the inline custom prop. The first bar
    // (practice_result) is emerald; the third (streak) is blue.
    const bars = screen.getAllByTestId("xp-breakdown-card-row-bar");
    expect(bars[0].style.getPropertyValue("--xp-source-color")).toBe("#34D399");
    expect(bars[1].style.getPropertyValue("--xp-source-color")).toBe("#F59E0B");
    expect(bars[2].style.getPropertyValue("--xp-source-color")).toBe("#60A5FA");

    // Top row is full-width (largest XP); subsequent rows are scaled.
    expect(bars[0].style.width).toBe("100%");
    // 100 / 320 = 31.25%
    expect(bars[1].style.width).toBe("31.25%");
  });

  it("renders the calm empty-state copy when total_xp is 0", async () => {
    getXpBreakdownMock.mockResolvedValue(
      makeBreakdown({ total_xp: 0, by_source: [] }),
    );
    render(<XpBreakdownCard />);

    await waitFor(() =>
      expect(
        screen.getByTestId("xp-breakdown-card-empty"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("xp-breakdown-card-empty")).toHaveTextContent(
      "No XP this week — start a session to earn some",
    );
    // The bar list is absent.
    expect(
      screen.queryByTestId("xp-breakdown-card-list"),
    ).not.toBeInTheDocument();
  });

  it("renders the muted error line when the fetch rejects", async () => {
    getXpBreakdownMock.mockRejectedValue({
      status: 500,
      message: "boom",
    });
    render(<XpBreakdownCard />);

    await waitFor(() =>
      expect(
        screen.getByTestId("xp-breakdown-card-error"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("xp-breakdown-card-error")).toHaveTextContent(
      "boom",
    );
  });

  it("falls back to muted gray + prettified label for unknown sources", async () => {
    getXpBreakdownMock.mockResolvedValue(
      makeBreakdown({
        total_xp: 25,
        by_source: [{ source: "future_event_type", xp: 25, count: 1 }],
      }),
    );
    render(<XpBreakdownCard />);

    await waitFor(() =>
      expect(screen.getByTestId("xp-breakdown-card-list")).toBeInTheDocument(),
    );
    const rows = screen.getAllByTestId("xp-breakdown-card-row");
    expect(rows).toHaveLength(1);
    // Pretty label: "Future Event Type".
    expect(rows[0]).toHaveTextContent("Future Event Type");
    // Singular event count.
    expect(rows[0]).toHaveTextContent("1 event");
    const bar = screen.getAllByTestId("xp-breakdown-card-row-bar")[0];
    expect(bar.style.getPropertyValue("--xp-source-color")).toBe("#9CA3AF");
  });
});
