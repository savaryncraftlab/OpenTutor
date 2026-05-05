"use client";

/**
 * `<StreakCalendarCard>` — dashboard card showing per-day streak status
 * over the last ~30 days (Slice 5 T3).
 *
 * Self-fetches `/api/gamification/streak-calendar` on mount, then renders
 * a 7-row × N-week grid where each cell color-codes the day's status:
 *
 * * `maintained` → emerald (matches `--track-python` token, parity with
 *   `<SparseHeatmap>` so a "filled" day reads identically across cards).
 * * `freeze`     → sky/blue ("blue flame" per ТЗ line 154).
 * * `broken`     → red — past day with no event and no freeze.
 * * `grace`      → amber — today only, when no event/freeze yet exists.
 * * `future`     → muted (defensive; current routes never produce it).
 *
 * The grid layout mirrors `<SparseHeatmap>`'s 7×N pattern (gridAutoFlow:
 * "column", oldest tile top-left, today bottom-right) so the two cards
 * read as siblings rather than competing visualizations. We don't reuse
 * the `<SparseHeatmap>` component directly because it bakes in
 * XP-bucket coloring; this card needs status-driven coloring with the
 * same shape but a different bucket function.
 *
 * Passive posture: a fetch failure renders the calm "couldn't load —
 * try again later" subline instead of bubbling an error toast (the
 * dashboard already mounts other cards with the same posture).
 */

import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";

import {
  getStreakCalendar,
  isGamificationApiError,
  type StreakCalendarResponse,
  type StreakCalendarStatus,
  type StreakCalendarTile,
} from "@/lib/api/gamification";

export interface StreakCalendarCardProps {
  /** Trailing window in days (1..90). Defaults to 30. */
  days?: number;
  className?: string;
  /**
   * Test/storybook hook — if provided, the card skips the fetch and
   * renders this payload directly. Production callers don't pass this.
   */
  initialData?: StreakCalendarResponse | null;
  /** Test/storybook hook — render an explicit error state. */
  initialError?: boolean;
}

/** Calendar layout — 7 rows (days of week) × N cols (weeks). */
const ROWS = 7;

type FetchState =
  | { status: "loading" }
  | { status: "loaded"; data: StreakCalendarResponse }
  | { status: "error" };

/**
 * Map a status to a Tailwind class. We restrict to existing palette
 * tokens (no new colors). Buckets:
 *
 * * `maintained` — emerald, matches the heatmap card's "filled day".
 * * `freeze`     — sky, the "blue flame" surface.
 * * `broken`     — rose at low intensity so a long broken streak
 *   doesn't read as a wall of alarm.
 * * `grace`      — amber, the only "warning"-style color.
 * * `future`     — muted, same as the empty cells in `<SparseHeatmap>`.
 */
function statusClass(status: StreakCalendarStatus): string {
  switch (status) {
    case "maintained":
      return "bg-emerald-500";
    case "freeze":
      return "bg-sky-500";
    case "broken":
      return "bg-rose-500/30";
    case "grace":
      return "bg-amber-400";
    case "future":
    default:
      return "bg-muted/30";
  }
}

/** Pretty-print a status for the per-tile tooltip. */
function statusLabel(status: StreakCalendarStatus): string {
  switch (status) {
    case "maintained":
      return "Maintained";
    case "freeze":
      return "Freeze used";
    case "broken":
      return "Missed";
    case "grace":
      return "Today — still time";
    case "future":
    default:
      return "Upcoming";
  }
}

/** Format `YYYY-MM-DD` → `Apr 12` for the tooltip. */
function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map((s) => Number.parseInt(s, 10));
  const months = [
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
  ];
  if (!m || Number.isNaN(m) || !d || Number.isNaN(d)) return iso;
  return `${months[m - 1] ?? ""} ${d}`;
}

export function StreakCalendarCard({
  days = 30,
  className,
  initialData,
  initialError,
}: StreakCalendarCardProps = {}) {
  const [state, setState] = useState<FetchState>(() => {
    if (initialError) return { status: "error" };
    if (initialData) return { status: "loaded", data: initialData };
    return { status: "loading" };
  });

  useEffect(() => {
    // Test/storybook injected explicit state — skip the fetch.
    if (initialData || initialError) return;

    let cancelled = false;
    getStreakCalendar(days)
      .then((data) => {
        if (!cancelled) setState({ status: "loaded", data });
      })
      .catch((err) => {
        // Best-effort — log to console for ops triage but don't toast.
        // The card has its own quiet error state.
        if (isGamificationApiError(err)) {
          console.warn("streak-calendar fetch failed", err.status, err.message);
        }
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [days, initialData, initialError]);

  // Derive the column count from the actual tile count so a 14-day or
  // 90-day window both render correctly. ceil(N/7) gives the smallest
  // 7-row grid that holds every tile.
  const cols = useMemo(() => {
    if (state.status !== "loaded") return Math.ceil(days / ROWS);
    return Math.ceil(state.data.days.length / ROWS) || 1;
  }, [state, days]);

  const totalDays =
    state.status === "loaded"
      ? state.data.days.length
      : Math.max(1, Math.min(days, 90));
  const padding = Math.max(0, ROWS * cols - totalDays);

  return (
    <section
      data-testid="streak-calendar-card"
      aria-label="Streak calendar"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-3",
        className,
      )}
    >
      <Header state={state} />

      {state.status === "loading" && (
        <div
          data-testid="streak-calendar-card-skeleton"
          aria-hidden="true"
          className="h-24 w-full animate-pulse rounded-md bg-muted/30"
        />
      )}

      {state.status === "error" && (
        <p
          data-testid="streak-calendar-card-error"
          className="text-xs text-muted-foreground"
        >
          Couldn't load the calendar. Try again later.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          <div
            data-testid="streak-calendar-card-grid"
            role="img"
            aria-label={`Streak status for the last ${state.data.days.length} days`}
            className="w-full overflow-hidden"
          >
            <div
              className="grid gap-[2px]"
              style={{
                gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
                gridTemplateRows: `repeat(${ROWS}, minmax(0, 1fr))`,
                gridAutoFlow: "column",
              }}
            >
              {Array.from({ length: padding }).map((_, i) => (
                <span
                  key={`pad-${i}`}
                  aria-hidden="true"
                  className="aspect-square rounded-[2px] bg-muted/30"
                />
              ))}
              {state.data.days.map((tile) => (
                <CalendarTile key={tile.date} tile={tile} />
              ))}
            </div>
          </div>

          <p
            data-testid="streak-calendar-card-footer"
            className="text-xs text-muted-foreground tabular-nums"
          >
            <span aria-hidden="true">🔥 </span>
            freeze tokens left this week:{" "}
            <span className="font-semibold text-foreground">
              {state.data.freezes_left_this_week}
            </span>
            {" / 3"}
          </p>
        </>
      )}
    </section>
  );
}

/** Card title — "Streak — N days" once loaded; placeholder otherwise. */
function Header({ state }: { state: FetchState }) {
  const streak =
    state.status === "loaded" ? state.data.current_streak : null;
  const label =
    streak === null
      ? "Streak"
      : `Streak — ${streak} ${streak === 1 ? "day" : "days"}`;
  return (
    <div className="flex items-center justify-between gap-3">
      <p
        data-testid="streak-calendar-card-title"
        className="text-sm font-semibold text-foreground"
      >
        {label}
      </p>
      <p className="text-xs text-muted-foreground">today is bottom-right</p>
    </div>
  );
}

/** Single calendar tile with a tooltip via the native `title` attribute. */
function CalendarTile({ tile }: { tile: StreakCalendarTile }) {
  const cls = statusClass(tile.status);
  const tooltip = `${shortDate(tile.date)} — ${statusLabel(tile.status)}`;
  return (
    <span
      data-testid={`streak-calendar-tile-${tile.date}`}
      data-status={tile.status}
      title={tooltip}
      className={`aspect-square rounded-[2px] ${cls}`}
    />
  );
}
