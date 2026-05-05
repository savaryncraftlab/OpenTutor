/**
 * Gamification dashboard client (Phase 16c Bundle C — Subagent A).
 *
 * Single read-only endpoint:
 *
 *   GET /api/gamification/dashboard → GamificationDashboard
 *
 * The endpoint always returns 200 with the full shape; for new accounts
 * counters are zero and arrays are empty. We use the shared
 * ``buildSecureRequestInit()`` so auth/CSRF parity matches the rest of
 * the API surface, but bypass the retry/toast ``request()`` wrapper:
 * gamification is a passive widget — a transient 5xx should bubble up to
 * the widget so it can render its own quiet fallback rather than firing
 * a global toast on dashboard load.
 */
import { API_BASE, buildSecureRequestInit } from "./client";

export type HeatmapTile = { date: string; xp: number };

export interface ActivePathSummary {
  path_id: string;
  slug: string;
  title: string;
  rooms_total: number;
  rooms_completed: number;
}

export interface GamificationDashboard {
  xp_total: number;
  level_tier: string;
  level_name: string;
  level_progress_pct: number;
  /**
   * XP needed to reach the next tier (0 when at the cap).
   * Phase 16c Bundle B — Subagent B added the field for the dashboard
   * level-ring card; backend (Subagent A) emits it on every payload.
   */
  xp_to_next_level: number;
  streak_days: number;
  streak_freezes_left: number;
  daily_goal_xp: number;
  daily_xp_earned: number;
  heatmap: HeatmapTile[];
  active_paths: ActivePathSummary[];
}

export interface GamificationApiError {
  status: number;
  message: string;
}

/** True if the thrown value is shaped like a `GamificationApiError`. */
export function isGamificationApiError(
  err: unknown,
): err is GamificationApiError {
  return (
    typeof err === "object" &&
    err !== null &&
    "status" in err &&
    typeof (err as { status: unknown }).status === "number" &&
    "message" in err
  );
}

interface ErrorBodyShape {
  detail?: unknown;
  message?: unknown;
}

function describeError(body: ErrorBodyShape, fallback: string): string {
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.message === "string") return body.message;
  return fallback;
}

/** `GET /api/gamification/dashboard` — full snapshot for the widget. */
export async function getGamificationDashboard(): Promise<GamificationDashboard> {
  const init = buildSecureRequestInit({ method: "GET" });
  const res = await fetch(`${API_BASE}/gamification/dashboard`, init);

  if (res.ok) {
    return (await res.json()) as GamificationDashboard;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const fallback = res.statusText || `HTTP ${res.status}`;
  const err: GamificationApiError = {
    status: res.status,
    message: describeError(body, fallback),
  };
  throw err;
}

/**
 * One row of the XP-breakdown card payload (Slice 5 T2).
 *
 * `source` matches the wire string in `xp_events.source` — known values
 * are `"practice_result"`, `"room_complete"`, `"hacking_room_complete"`,
 * `"streak"`, `"manual"`, plus whatever future awarders add. The card
 * uses `source` for color-token lookup and falls back to muted gray for
 * unknown sources.
 */
export interface XpBreakdownEntry {
  source: string;
  xp: number;
  count: number;
}

/** Response shape for `GET /api/gamification/xp-breakdown` (Slice 5 T2). */
export interface XpBreakdown {
  window_days: number;
  total_xp: number;
  by_source: XpBreakdownEntry[];
}

/**
 * `GET /api/gamification/xp-breakdown?days={days}` — per-source XP
 * breakdown over the trailing window (default 7d). Same passive-fetch
 * posture as `getGamificationDashboard`: bypass the global toast wrapper
 * so a transient 5xx renders inline instead of firing a global error.
 */
export async function getXpBreakdown(days = 7): Promise<XpBreakdown> {
  const init = buildSecureRequestInit({ method: "GET" });
  const url = `${API_BASE}/gamification/xp-breakdown?days=${encodeURIComponent(days)}`;
  const res = await fetch(url, init);

  if (res.ok) {
    return (await res.json()) as XpBreakdown;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const fallback = res.statusText || `HTTP ${res.status}`;
  const err: GamificationApiError = {
    status: res.status,
    message: describeError(body, fallback),
  };
  throw err;
}

/**
 * Per-day status on the streak calendar (Slice 5 T3).
 *
 * Backend pinky-promises this is one of the listed string literals — the
 * pydantic schema enforces it via regex. We model it as a TS union so
 * `status === "maintained"` narrows correctly inside the card component.
 */
export type StreakCalendarStatus =
  | "maintained"
  | "freeze"
  | "broken"
  | "grace"
  | "future";

export interface StreakCalendarTile {
  /** ISO date string (`YYYY-MM-DD`) in UTC. */
  date: string;
  status: StreakCalendarStatus;
}

export interface StreakCalendarResponse {
  /** ISO date string (`YYYY-MM-DD`) — right edge of the window. */
  today: string;
  current_streak: number;
  freezes_left_this_week: number;
  /** Oldest → newest; `today` is always the last entry. */
  days: StreakCalendarTile[];
}

/**
 * `GET /api/gamification/streak-calendar?days={days}` — per-day status
 * calendar for the trailing window (default 30 server-side, max 90).
 * Same passive-fetch posture as `getGamificationDashboard`: bypass the
 * global toast wrapper so a transient 5xx renders inline.
 */
export async function getStreakCalendar(
  days?: number,
): Promise<StreakCalendarResponse> {
  const init = buildSecureRequestInit({ method: "GET" });
  const query = days !== undefined ? `?days=${encodeURIComponent(days)}` : "";
  const res = await fetch(
    `${API_BASE}/gamification/streak-calendar${query}`,
    init,
  );

  if (res.ok) {
    return (await res.json()) as StreakCalendarResponse;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const fallback = res.statusText || `HTTP ${res.status}`;
  const err: GamificationApiError = {
    status: res.status,
    message: describeError(body, fallback),
  };
  throw err;
}

/**
 * Badge catalog entry returned by `GET /api/gamification/badges`
 * (Phase 16c Bundle C — Subagent A backend, Subagent B frontend).
 *
 * Locked badges still surface `key/title/description/hint` so the UI
 * can render a muted preview tile without round-tripping a separate
 * "definition" endpoint. `unlocked_at` is `null` for locked badges
 * and ISO-8601 UTC for unlocked ones.
 */
export interface BadgeOut {
  key: string;
  title: string;
  description: string;
  hint: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

/** Response shape for `GET /api/gamification/badges`. */
export interface BadgesResponse {
  unlocked: BadgeOut[];
  locked: BadgeOut[];
}

/**
 * `GET /api/gamification/badges` — full badge catalog split into
 * unlocked / locked buckets. Same passive-fetch posture as
 * `getGamificationDashboard`: bypass the global toast wrapper so a
 * transient 5xx renders inline instead of firing a global error.
 */
export async function getBadges(): Promise<BadgesResponse> {
  const init = buildSecureRequestInit({ method: "GET" });
  const res = await fetch(`${API_BASE}/gamification/badges`, init);

  if (res.ok) {
    return (await res.json()) as BadgesResponse;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const fallback = res.statusText || `HTTP ${res.status}`;
  const err: GamificationApiError = {
    status: res.status,
    message: describeError(body, fallback),
  };
  throw err;
}
