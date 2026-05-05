"use client";

/**
 * `<RecallForecastCard>` — Slice 5 T4 dashboard card.
 *
 * Compact "coming back this week" card that surfaces user-aggregate
 * FSRS forecast from `GET /api/progress/recall-forecast`:
 *   - Big number: today_due
 *   - Sub-line: "{this_week} this week · {next_week} next week"
 *   - Footer urgency pill: green (none/low) / amber (normal/high) /
 *     red (critical), text from `recommendation`
 *
 * Scope honesty: every state surfaces "from flashcard reviews" since
 * path-room missions carry no FSRS state. Empty state appends
 * "— nothing scheduled" to that subline so a new account doesn't
 * read like a broken card.
 *
 * Self-fetches on mount (mirrors `<BadgeShelf>` shape) — the dashboard
 * host just drops `<RecallForecastCard />` next to `<RecallHealthCard>`.
 */

import { useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import {
  getRecallForecast,
  type RecallForecast,
  type RecallForecastUrgency,
} from "@/lib/api/progress";

/** Map urgency → semantic pill color. T4 spec mapping:
 *  - none / low      → emerald (calm)
 *  - normal / high   → amber (attention)
 *  - critical        → red (act now)
 */
function urgencyPillClasses(urgency: RecallForecastUrgency): string {
  switch (urgency) {
    case "critical":
      return "bg-red-500/20 text-red-600 dark:text-red-400";
    case "normal":
    case "high":
      return "bg-amber-500/20 text-amber-700 dark:text-amber-400";
    case "none":
    case "low":
    default:
      return "bg-emerald-500/20 text-emerald-700 dark:text-emerald-400";
  }
}

export function RecallForecastCard() {
  const [data, setData] = useState<RecallForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    let cancelled = false;
    getRecallForecast(7)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load forecast. Retry?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cancel = load();
    return cancel;
  }, [load]);

  const isEmpty =
    !loading &&
    !error &&
    data !== null &&
    data.today_due === 0 &&
    data.this_week_due === 0;

  return (
    <section
      data-testid="recall-forecast-card"
      aria-label="Recall forecast"
      className="rounded-2xl border border-border bg-card p-5 card-shadow flex flex-col gap-3"
    >
      <p className="text-sm font-semibold text-foreground">
        Coming back this week
      </p>

      {loading && (
        <div
          data-testid="recall-forecast-card-skeleton"
          className="flex flex-col gap-2"
        >
          <div className="h-9 w-16 rounded bg-muted/40 animate-pulse" />
          <div className="h-3 w-40 rounded bg-muted/40 animate-pulse" />
        </div>
      )}

      {!loading && error && (
        <div
          role="alert"
          data-testid="recall-forecast-card-error"
          className="rounded-xl border border-border bg-card p-3 text-xs text-muted-foreground"
        >
          <p>{error}</p>
          <button
            type="button"
            data-testid="recall-forecast-card-retry"
            onClick={load}
            className="mt-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground hover:bg-emerald-500/20 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div className="flex items-baseline gap-2">
            <span
              data-testid="recall-forecast-card-today"
              className="text-3xl font-semibold text-foreground tabular-nums"
            >
              {data.today_due}
            </span>
            <span className="text-xs text-muted-foreground">due today</span>
          </div>

          <p
            data-testid="recall-forecast-card-breakdown"
            className="text-xs text-muted-foreground tabular-nums"
          >
            {data.this_week_due} this week · {data.next_week_due} next week
          </p>

          <p
            data-testid="recall-forecast-card-scope"
            className="text-[11px] text-muted-foreground"
          >
            {isEmpty
              ? "from flashcard reviews — nothing scheduled"
              : "from flashcard reviews"}
          </p>

          <div className="flex items-center justify-between gap-2 pt-1">
            <span
              data-testid="recall-forecast-card-urgency"
              data-urgency={data.urgency}
              className={clsx(
                "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                urgencyPillClasses(data.urgency),
              )}
            >
              {data.recommendation}
            </span>
          </div>
        </>
      )}
    </section>
  );
}
