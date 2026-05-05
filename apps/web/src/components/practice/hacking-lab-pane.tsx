"use client";

/**
 * `<HackingLabPane>` — mission-page Hacking-track wrapper.
 *
 * Mirrors `<PythonPane>` shape: wraps `<TaskRenderer>` (which already
 * dispatches `lab_exercise` tasks to `<LabExerciseBlock>`) inside
 * `<PracticeShell>` with `variant="hacking"`. The shell renders the
 * Hacking caption + accent; the inner `<LabExerciseBlock>` mounts the
 * Open-Lab CTA + `target_url` display + proof inputs (payload, flag,
 * optional localhost screenshot URL) and owns submit + grading.
 *
 * Why a sibling pane (and not a tweak to `<HackingPane>`)
 * -------------------------------------------------------
 * `<HackingPane>` (sibling file) is the Slice 3 *shape* contract — a
 * single hardcoded iframe + free-text proof input — pinned by Phase A
 * tests as the forward shape for Phase 12 verification API. Repurposing
 * it would break those tests AND lose the sandbox iframe shape that
 * Phase 12 wants to land into. `<HackingLabPane>` is the live mission
 * surface for hacking tracks today: it routes through the same
 * `<TaskRenderer>` + `<LabExerciseBlock>` path that already grades
 * lab proofs end-to-end via `/quiz/submit` (§34.6 T2).
 *
 * Acceptance per ТЗ §3 Slice 3 item #3 ("Hacking mission → Juice Shop
 * iframe + proof pane"): `<LabExerciseBlock>` ships the iframe-deeplink
 * "Open Lab" button + on-page `target_url` display + the three proof
 * inputs already, so the surface is live.
 */

import { useState } from "react";
import { TaskRenderer } from "@/components/path/RoomTaskList";
import type { RoomTask } from "@/lib/api/paths";
import { PracticeShell } from "./practice-shell";

export interface HackingLabPaneProps {
  task: RoomTask;
  /** Whether the user's last submission was correct — drives the
   *  shell's explain-rail initial state. */
  correct?: boolean;
  /** Bumped by the parent when the underlying `<TaskRenderer>` reports
   *  a correct submission. */
  onCorrect?: () => void;
  /** Advance to the next task — when provided, the shell renders an
   *  inline "Next task" CTA after the user attempts the current task. */
  onAdvance?: () => void;
}

export function HackingLabPane({
  task,
  correct = false,
  onCorrect,
  onAdvance,
}: HackingLabPaneProps) {
  // Attempt latch — flips true after the underlying renderer reports
  // any submit verdict (correct OR incorrect). Mission page passes
  // `key={task.id}` so a task switch remounts the pane and the latch
  // resets to false automatically.
  const [attempted, setAttempted] = useState(false);
  // The shell submit is hidden for the hacking variant: `<LabExerciseBlock>`
  // owns its own primary "Submit proof" CTA + result rendering. The shell
  // still hosts the explain rail + Next-task CTA so cross-variant
  // affordances stay consistent.
  return (
    <PracticeShell
      problemId={task.id}
      variant="hacking"
      question={task.question}
      surface={
        <TaskRenderer
          // Force a fresh renderer instance on task switch so the
          // child block's local result/selected state never bleeds
          // across tasks.
          key={task.id}
          task={task}
          onCorrect={onCorrect ?? (() => undefined)}
          onAttempt={() => setAttempted(true)}
        />
      }
      correct={correct}
      onSubmit={() => undefined}
      hideSubmit
      onAdvance={onAdvance}
      canAdvance={attempted}
    />
  );
}

export default HackingLabPane;
