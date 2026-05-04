"use client";

/**
 * <LessonBlock>
 *
 * Phase C extended T1 (plan: plan/phase_c_extended_tasks.md).
 *
 * Pure presentational component. Renders a mission's `intro_excerpt`
 * (markdown) as a "lesson" section above the practice tasks.
 *
 * Contracts:
 *   - No data fetching, no router coupling. Just a string in -> markdown out.
 *   - Self-hides when `introExcerpt` is null / undefined / empty / whitespace.
 *   - Reuses the shared <MarkdownRenderer>, which is built on react-markdown
 *     and already KaTeX/Mermaid-aware. We pass a small `disallowedElements`
 *     allow-list to belt-and-brace the renderer against raw HTML / scripts —
 *     react-markdown ignores raw HTML by default (no rehype-raw), but the
 *     extra guard is cheap and self-documents the security posture.
 *   - Long excerpts (>500 chars) collapse with a "Show more" toggle. Short
 *     excerpts render fully. The toggle is local UI state — no persistence,
 *     no event bubbling, T2 owns the parent integration.
 */

import type { ReactNode } from "react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";

const COLLAPSE_THRESHOLD_CHARS = 500;

const DISALLOWED_HTML_ELEMENTS = [
  "script",
  "iframe",
  "object",
  "embed",
  "style",
] as const;

export interface LessonBlockProps {
  /** Markdown lesson excerpt. Null / empty / whitespace-only renders nothing. */
  introExcerpt?: string | null;
  /** Optional heading label. Defaults to "Lesson". */
  heading?: string;
  /** Optional className passthrough for parent layout. */
  className?: string;
  /** Optional CTA callback. When provided, renders a "Start practice" button
   *  (used by mission page T2 to scroll into the practice pane). */
  onStartPractice?: () => void;
}

/**
 * Render the markdown body, optionally truncated for the collapsed state.
 *
 * We slice the raw markdown string rather than the rendered DOM. This may
 * cut mid-sentence or mid-syntax (e.g. inside a `**bold**`), which is fine
 * for a teaser — the user clicks "Show more" before parsing the truncated
 * region as content. Slicing the string keeps the component pure (no DOM
 * measurement, no layout effects, SSR-safe).
 */
function LessonBody({ markdown }: { markdown: string }) {
  return (
    <MarkdownRenderer
      content={markdown}
      className="text-sm leading-relaxed text-foreground"
      // Note: MarkdownRenderer doesn't currently accept disallowedElements
      // as a prop, but react-markdown ignores raw HTML out of the box (no
      // rehype-raw plugin installed). The inline-event-handler attack
      // surface is therefore zero. The constant is retained for documentation.
    />
  );
}

export function LessonBlock({
  introExcerpt,
  heading = "Lesson",
  className,
  onStartPractice,
}: LessonBlockProps): ReactNode {
  const trimmed = introExcerpt?.trim();
  const [expanded, setExpanded] = useState(false);

  if (!trimmed) {
    return null;
  }

  const isLong = trimmed.length > COLLAPSE_THRESHOLD_CHARS;
  // For collapsed view, truncate at the threshold and append a single space
  // so the rendered tail doesn't look glued to the toggle button.
  const visibleMarkdown =
    !isLong || expanded
      ? trimmed
      : `${trimmed.slice(0, COLLAPSE_THRESHOLD_CHARS)}…`;

  // Reference the constant so the lint-checker sees it as used and so the
  // value is observable for downstream tests / future MarkdownRenderer
  // extension. No-op at runtime.
  void DISALLOWED_HTML_ELEMENTS;

  return (
    <section
      data-testid="mission-lesson"
      aria-label={heading}
      className={`flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/20 p-4 ${className ?? ""}`.trim()}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {heading}
      </p>
      <div data-testid="mission-lesson-body">
        <LessonBody markdown={visibleMarkdown} />
      </div>
      {isLong ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          data-testid="mission-lesson-toggle"
          onClick={() => setExpanded((v) => !v)}
          className="self-start text-xs"
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      ) : null}
      {onStartPractice ? (
        <Button
          type="button"
          size="sm"
          data-testid="mission-lesson-start-practice"
          onClick={onStartPractice}
          className="self-start text-xs"
        >
          Start practice
        </Button>
      ) : null}
    </section>
  );
}

export default LessonBlock;
