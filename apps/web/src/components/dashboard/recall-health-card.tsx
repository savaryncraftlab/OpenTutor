"use client";

/**
 * `<RecallHealthCard>` — dashboard card showing aggregate FSRS recall
 * health across the user's flashcard reviews (Slice 5 T1).
 *
 * Self-fetches on mount. The card honours the architect+critic ruling
 * that FSRS state is flashcards-only today: the "from flashcard reviews"
 * subline is ALWAYS visible — both in the loaded-data state and the
 * empty state — so the user is never misled into thinking path-room
 * missions are tracked.
 *
 * Empty state (Юрій's case while he has 0 reviews): big number is "—"
 * (em-dash placeholder, never "0%"), subline reads
 * "from flashcard reviews — start a flashcard session to track" in
 * muted gray, NOT a red error tone. No reviews ≠ broken.
 */
import { useEffect, useState } from "react";
import { clsx } from "clsx";

import { getRecallHealth, type RecallHealth } from "@/lib/api/progress";

export interface RecallHealthCardProps {
  /** Override the fetcher (used by tests to inject loaded/empty/error data). */
  fetcher?: () => Promise<RecallHealth>;
  className?: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; data: RecallHealth }
  | { kind: "error"; message: string };

export function RecallHealthCard({ fetcher, className }: RecallHealthCardProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const run = fetcher ?? getRecallHealth;
    run()
      .then((data) => {
        if (!cancelled) setState({ kind: "loaded", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load";
          setState({ kind: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fetcher]);

  return (
    <section
      data-testid="recall-health-card"
      aria-label="Recall health"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-2",
        className,
      )}
    >
      <p className="text-sm font-semibold text-foreground">Recall health</p>
      <RecallHealthBody state={state} />
    </section>
  );
}

function RecallHealthBody({ state }: { state: LoadState }) {
  if (state.kind === "loading") {
    // Honest-default rule (mirrors top-bar streak chip): em-dash
    // placeholder while loading. The subline still asserts the scope
    // so the user reads the same flashcards caveat in every state.
    return (
      <>
        <p
          data-testid="recall-health-card-value"
          className="text-3xl font-semibold tabular-nums text-muted-foreground"
        >
          —
        </p>
        <p
          data-testid="recall-health-card-subline"
          className="text-xs text-muted-foreground"
        >
          from flashcard reviews
        </p>
      </>
    );
  }

  if (state.kind === "error") {
    return (
      <>
        <p
          data-testid="recall-health-card-value"
          className="text-3xl font-semibold tabular-nums text-muted-foreground"
        >
          —
        </p>
        <p
          data-testid="recall-health-card-subline"
          className="text-xs text-muted-foreground"
        >
          from flashcard reviews — couldn&apos;t load right now
        </p>
      </>
    );
  }

  const { total_tracked, average_retrievability, at_risk_count, well_known_count } =
    state.data;
  const empty = total_tracked === 0;

  return (
    <>
      <p
        data-testid="recall-health-card-value"
        className={clsx(
          "text-3xl font-semibold tabular-nums",
          empty ? "text-muted-foreground" : "text-emerald-500",
        )}
      >
        {empty ? "—" : `${Math.round(average_retrievability * 100)}%`}
      </p>
      <p
        data-testid="recall-health-card-subline"
        className="text-xs text-muted-foreground"
      >
        {empty
          ? "from flashcard reviews — start a flashcard session to track"
          : "from flashcard reviews"}
      </p>
      {!empty && (
        <p
          data-testid="recall-health-card-counts"
          className="text-xs text-muted-foreground tabular-nums"
        >
          {at_risk_count} at risk · {well_known_count} well-known
        </p>
      )}
    </>
  );
}
