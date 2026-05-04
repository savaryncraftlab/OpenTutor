import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextReviewChip } from "./next-review-chip";

describe("NextReviewChip", () => {
  it("renders nothing when intervalDays is 0 (FSRS stability=0 edge case)", () => {
    const { container } = render(<NextReviewChip intervalDays={0} />);
    // Self-hide guard — see component's architect-plan note. The chip
    // must NEVER render "Returns in 0 days".
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("next-review-chip")).not.toBeInTheDocument();
  });

  it("renders 'Returns in 2 days' when only intervalDays is provided", () => {
    render(<NextReviewChip intervalDays={2} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 2 days");
  });

  it("renders 'Returns Mon 18 May' for a near-term date (interval ≤ 7d)", () => {
    // 2026-05-18 is a Monday (UTC). intervalDays = 14 falls outside the
    // near-term threshold (7d), so we use 5 to exercise the weekday path.
    render(
      <NextReviewChip intervalDays={5} nextReviewAt="2026-05-18T00:00:00Z" />,
    );
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns Mon 18 May");
  });

  it("falls back to day-count when interval is > 7d even with a date", () => {
    // 14d horizon — weekday is no longer load-bearing, day count is more
    // legible.
    render(
      <NextReviewChip intervalDays={14} nextReviewAt="2026-05-18T00:00:00Z" />,
    );
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 14 days");
  });

  it("hides on null/undefined intervalDays (tracker failure path)", () => {
    const { container } = render(<NextReviewChip intervalDays={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("uses singular 'day' for intervalDays=1", () => {
    render(<NextReviewChip intervalDays={1} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 1 day");
    expect(chip).not.toHaveTextContent("days");
  });

  // Phase C T5 — first-correct-rep branch.
  it("renders 'First time seeing this!' when isFirstReview=true with intervalDays>0", () => {
    render(<NextReviewChip intervalDays={2} isFirstReview={true} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("First time seeing this!");
    // Schedule context still surfaces so the user knows when it returns.
    expect(chip).toHaveTextContent("Returns in 2 days");
    // The data attribute lets snapshot/style tests inspect the variant.
    expect(chip).toHaveAttribute("data-first-review", "true");
  });

  it("uses standard schedule label when isFirstReview=false (non-first rep)", () => {
    render(<NextReviewChip intervalDays={2} isFirstReview={false} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 2 days");
    // Must NOT regress into the celebration text on the normal path.
    expect(chip).not.toHaveTextContent("First time seeing this!");
    expect(chip).not.toHaveAttribute("data-first-review");
  });

  it("self-hides when isFirstReview=true but intervalDays=0 (cap takes precedence)", () => {
    // Stability-rounds-to-0 edge case. We refuse to celebrate a
    // malformed schedule even when the first-rep flag is set.
    const { container } = render(
      <NextReviewChip intervalDays={0} isFirstReview={true} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("uses standard schedule label when isFirstReview=null (legacy/tracker-failure path)", () => {
    // Backwards-compat: an older API response or a tracker failure
    // leaves the field null; we render the existing branch unchanged.
    render(
      <NextReviewChip
        intervalDays={2}
        nextReviewAt="2026-05-18T00:00:00Z"
        isFirstReview={null}
      />,
    );
    const chip = screen.getByTestId("next-review-chip");
    // 2026-05-18 is a Monday; intervalDays=2 falls in the near-term
    // weekday-format branch.
    expect(chip).toHaveTextContent("Returns Mon 18 May");
    expect(chip).not.toHaveTextContent("First time seeing this!");
  });
});
