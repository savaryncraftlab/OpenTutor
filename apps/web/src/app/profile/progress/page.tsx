"use client";

/**
 * `/profile/progress` — Slice 5 T5 aggregate page.
 *
 * Pins the four Slice 5 progress widgets in a calm 1/2/3-col grid:
 *   - <StreakCalendarCard> (T3): per-day streak status heatmap
 *   - <XpBreakdownCard>    (T2): where your XP comes from
 *   - <RecallHealthCard>   (T1): aggregate FSRS recall metric
 *   - <RecallForecastCard> (T4): "coming back today/this week"
 *
 * Separate from the home dashboard which is action-focused. This page
 * is the user's "progress dashboard" — answers "am I improving?" in one
 * surface. Uses the shared `<PageShell>` primitive (Visual Shell P1.5)
 * for desktop width parity with TopBar and the rest of the routed pages.
 */
// TODO(slice-5-followup): cards self-fetch on mount; dashboard + this
// page double-fetch when user visits both. Add SWR or shared cache
// when Phase B exit reveals usage patterns.
import { PageShell } from "@/components/layout/page-shell";
import { RecallHealthCard } from "@/components/dashboard/recall-health-card";
import { XpBreakdownCard } from "@/components/dashboard/xp-breakdown-card";
import { StreakCalendarCard } from "@/components/dashboard/streak-calendar-card";
import { RecallForecastCard } from "@/components/dashboard/recall-forecast-card";

export default function ProgressPage() {
  return (
    <PageShell data-testid="profile-progress-page" className="pt-8 pb-24">
      <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl mb-6">
        Your progress
      </h1>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <StreakCalendarCard />
        <XpBreakdownCard />
        <RecallHealthCard />
        <RecallForecastCard />
      </div>
    </PageShell>
  );
}
