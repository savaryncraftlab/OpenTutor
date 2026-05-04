"use client";

/**
 * `<NextReviewChip>` — Phase C SRS visibility chip.
 *
 * Surfaces the FSRS schedule decision after each successful submit so the
 * learner SEES that a card was scheduled forward (instead of the silent
 * "answer disappears, mystery interval grows in the DB" behaviour the
 * pre-Phase-C UI had — see `plan/phase_c_lesson_practice_recall_design.md`
 * §1 for the pain analysis).
 *
 * Self-hide rules (architect plan §5 risks):
 *   - `intervalDays <= 0` → render nothing. FSRS init failures and the
 *     "stability == 0" edge case (tracker.py:178) would otherwise produce
 *     "Returns in 0 days" which is nonsense.
 *   - Both inputs null/undefined → render nothing. A tracker exception
 *     in the backend leaves the fields null; we'd rather show silence
 *     than a half-rendered chip.
 *
 * Display rules:
 *   - With `nextReviewAt` AND `intervalDays > 0` AND interval ≤ 7d:
 *     "Returns Mon 18 May" — the weekday makes the schedule legible
 *     without the user having to count days.
 *   - Otherwise (interval > 7d OR no date): "Returns in N days".
 *
 * Pure presentational. No API calls, no state.
 */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const NEAR_TERM_THRESHOLD_DAYS = 7;

export interface NextReviewChipProps {
  intervalDays?: number | null;
  /** ISO 8601 datetime string (e.g. ``"2026-05-18T00:00:00Z"``). */
  nextReviewAt?: string | null;
  /**
   * Phase C T5 — when true AND `intervalDays > 0`, the chip switches to
   * a celebratory "First time seeing this!" branch (dopaminergic novelty
   * signal on the user's first correct rep of a card). Falsy/null falls
   * back to the standard schedule label. The self-hide guard
   * (`intervalDays <= 0`) takes precedence so the cap-on-empty case
   * cannot accidentally render the celebration text.
   */
  isFirstReview?: boolean | null;
  className?: string;
}

/** Format a Date as e.g. ``"Mon 18 May"``. Pure (no locale-specific
 *  surprises), avoids `Intl.DateTimeFormat` so the test snapshot is
 *  stable across CI environments. */
function formatWeekdayDate(date: Date): string {
  const wd = WEEKDAYS[date.getUTCDay()];
  const day = date.getUTCDate();
  const month = MONTHS[date.getUTCMonth()];
  return `${wd} ${day} ${month}`;
}

export function NextReviewChip({
  intervalDays,
  nextReviewAt,
  isFirstReview,
  className,
}: NextReviewChipProps) {
  // Architect-plan §5 risk-row 3 — FSRS edge case where stability rounds
  // to 0. The chip must hide rather than print "Returns in 0 days".
  // This guard runs BEFORE the first-review branch so the cap-on-empty
  // case cannot leak the celebration text on a malformed schedule.
  if (intervalDays === null || intervalDays === undefined || intervalDays <= 0) {
    return null;
  }

  // Phase C T5 — first-correct-rep branch. The dopaminergic intent: on
  // the *very first* time a learner answers a card correctly, surface
  // novelty ("you haven't seen this before") instead of the usual
  // schedule line. We still include the interval so the user knows the
  // card will return; the celebration text just leads.
  let label: string;
  if (isFirstReview === true) {
    label = `First time seeing this! Returns in ${intervalDays} ${intervalDays === 1 ? "day" : "days"}`;
  } else if (nextReviewAt && intervalDays <= NEAR_TERM_THRESHOLD_DAYS) {
    // Near-term schedules render the weekday/date so "Returns Mon 18 May"
    // is more legible than "Returns in 14 days". Far-out (> 7 days) keeps
    // the day count — the weekday gives no extra signal at that horizon.
    const parsed = new Date(nextReviewAt);
    if (!Number.isNaN(parsed.getTime())) {
      label = `Returns ${formatWeekdayDate(parsed)}`;
    } else {
      // Malformed date string — graceful fallback to interval.
      label = `Returns in ${intervalDays} ${intervalDays === 1 ? "day" : "days"}`;
    }
  } else {
    label = `Returns in ${intervalDays} ${intervalDays === 1 ? "day" : "days"}`;
  }

  // First-review state gets a subtle green tint so the visual matches
  // the celebratory copy without screaming. Falls back to the muted
  // chrome-on-grey treatment for the regular schedule branch.
  const styleClasses =
    isFirstReview === true
      ? "border-emerald-300/60 bg-emerald-50 text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-950/40 dark:text-emerald-200"
      : "border-border/60 bg-muted/40 text-muted-foreground";

  return (
    <span
      data-testid="next-review-chip"
      data-first-review={isFirstReview === true ? "true" : undefined}
      className={`inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-medium ${styleClasses} ${className ?? ""}`.trim()}
    >
      {label}
    </span>
  );
}

export default NextReviewChip;
