"use client";

/**
 * `<XpBreakdownCard>` — dashboard card showing XP earned per source over
 * the trailing 7-day window (Slice 5 T2).
 *
 * Layout:
 *   - Title "XP this week" + total number on the right.
 *   - Horizontal bar list, one row per source, ordered XP DESC. Each
 *     row has a color-coded fill keyed off the source string (per
 *     ТЗ §8 design tokens), the source label, and an XP/event count.
 *   - Empty state (total=0): calm "No XP this week — start a session
 *     to earn some" copy. NO bars, NO red, NO shaming.
 *   - Loading: skeleton with three muted bars.
 *   - Error: muted "Couldn't load XP breakdown" line. Same posture as
 *     `<DailyGoalCard>` — passive widget, never blocks the dashboard.
 *
 * Self-fetches on mount via `getXpBreakdown(days)` (default 7) so the
 * dashboard payload doesn't grow. Same network posture as
 * `<BadgeShelf>` (which also self-fetches).
 */
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import {
  getXpBreakdown,
  isGamificationApiError,
  type XpBreakdown,
  type XpBreakdownEntry,
} from "@/lib/api/gamification";

export interface XpBreakdownCardProps {
  /** Trailing window in days (forwarded to the API). Default 7. */
  days?: number;
  className?: string;
}

// ТЗ §8 design tokens — map known source strings to a CSS color
// variable and a human label. Unknown sources fall through to the
// muted-gray default so a future awarder doesn't crash the card.
//
// Source-key matching uses ``casefold`` semantics so a backend rename
// from ``"Practice_Result"`` to ``"practice_result"`` doesn't ghost a
// row off the chart. We store keys lowercase here and lowercase the
// incoming source before lookup.
const SOURCE_STYLE: Record<string, { color: string; label: string }> = {
  practice_result: { color: "#34D399", label: "Practice" }, // emerald, --track-python
  room_complete: { color: "#F59E0B", label: "Room completion" }, // amber, --track-hacking
  hacking_room_complete: {
    color: "#F59E0B",
    label: "Hacking room",
  }, // amber too — bonus track
  streak: { color: "#60A5FA", label: "Streak" }, // blue, --track-english
  manual: { color: "#9CA3AF", label: "Manual" }, // muted gray
};
const FALLBACK_STYLE = { color: "#9CA3AF", label: "Other" };

function styleFor(source: string): { color: string; label: string } {
  const key = source.toLowerCase();
  if (key in SOURCE_STYLE) {
    return SOURCE_STYLE[key];
  }
  return { color: FALLBACK_STYLE.color, label: prettifyUnknownSource(source) };
}

/** Convert an unknown source string into a readable label. */
function prettifyUnknownSource(source: string): string {
  if (!source) return FALLBACK_STYLE.label;
  return source
    .split("_")
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : ""))
    .filter(Boolean)
    .join(" ");
}

/** Width of one bar as a percentage of the card's row max. */
function barWidthPct(entryXp: number, maxXp: number): number {
  if (maxXp <= 0) return 0;
  const pct = (entryXp / maxXp) * 100;
  if (Number.isNaN(pct)) return 0;
  if (pct < 0) return 0;
  if (pct > 100) return 100;
  return pct;
}

export function XpBreakdownCard({ days = 7, className }: XpBreakdownCardProps) {
  const [data, setData] = useState<XpBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getXpBreakdown(days)
      .then((breakdown) => {
        if (cancelled) return;
        setData(breakdown);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = isGamificationApiError(err)
          ? err.message
          : "Couldn't load XP breakdown";
        setError(message);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  return (
    <section
      data-testid="xp-breakdown-card"
      aria-label="XP this week"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-3",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-foreground">XP this week</p>
        {data && !error && (
          <p
            data-testid="xp-breakdown-card-total"
            className="text-sm font-semibold tabular-nums text-foreground"
          >
            {data.total_xp.toLocaleString()} XP
          </p>
        )}
      </div>

      {loading && (
        <div
          data-testid="xp-breakdown-card-loading"
          className="flex flex-col gap-2"
        >
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-3 w-full animate-pulse rounded-full bg-muted/40"
            />
          ))}
        </div>
      )}

      {!loading && error && (
        <p
          data-testid="xp-breakdown-card-error"
          className="text-xs text-muted-foreground"
        >
          {error}
        </p>
      )}

      {!loading && !error && data && data.total_xp === 0 && (
        <p
          data-testid="xp-breakdown-card-empty"
          className="text-xs text-muted-foreground"
        >
          No XP this week — start a session to earn some
        </p>
      )}

      {!loading && !error && data && data.total_xp > 0 && (
        <ul
          data-testid="xp-breakdown-card-list"
          className="flex flex-col gap-2"
        >
          {data.by_source.map((entry) => (
            <BreakdownRow
              key={entry.source}
              entry={entry}
              maxXp={data.by_source[0]?.xp ?? entry.xp}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

interface BreakdownRowProps {
  entry: XpBreakdownEntry;
  maxXp: number;
}

function BreakdownRow({ entry, maxXp }: BreakdownRowProps) {
  const style = styleFor(entry.source);
  const pct = barWidthPct(entry.xp, maxXp);
  return (
    <li
      data-testid="xp-breakdown-card-row"
      data-source={entry.source}
      className="flex flex-col gap-1"
    >
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-foreground">{style.label}</span>
        <span
          className="tabular-nums text-muted-foreground"
          data-testid="xp-breakdown-card-row-meta"
        >
          {entry.xp.toLocaleString()} XP · {entry.count.toLocaleString()}{" "}
          {entry.count === 1 ? "event" : "events"}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={maxXp}
        aria-valuenow={entry.xp}
        aria-label={`${style.label} XP`}
        className="h-2 w-full overflow-hidden rounded-full bg-muted/30"
      >
        <div
          data-testid="xp-breakdown-card-row-bar"
          style={
            {
              width: `${pct}%`,
              // CSS variable for testability — assertions read the
              // ``--xp-source-color`` custom prop without parsing the
              // inline style mash.
              "--xp-source-color": style.color,
              backgroundColor: "var(--xp-source-color)",
            } as React.CSSProperties
          }
          className="h-full rounded-full transition-[width] duration-[var(--thm-dur-slow)] ease-[var(--thm-ease-out)]"
        />
      </div>
    </li>
  );
}
