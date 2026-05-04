import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { LessonBlock } from "./lesson-block";

const COLLAPSE_THRESHOLD = 500;

describe("LessonBlock", () => {
  it("renders nothing when introExcerpt is null", () => {
    const { container } = render(<LessonBlock introExcerpt={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("mission-lesson")).toBeNull();
  });

  it("renders nothing when introExcerpt is undefined", () => {
    const { container } = render(<LessonBlock />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for empty string", () => {
    const { container } = render(<LessonBlock introExcerpt="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for whitespace-only string", () => {
    // JSX attribute strings do NOT process \n / \t escapes — pass via {} so
    // the actual whitespace characters reach the component.
    const { container } = render(<LessonBlock introExcerpt={"   \n\t  "} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders short excerpt fully expanded with no toggle", () => {
    render(<LessonBlock introExcerpt="A short lesson excerpt." />);

    expect(screen.getByTestId("mission-lesson")).toBeInTheDocument();
    expect(screen.getByText(/A short lesson excerpt\./)).toBeInTheDocument();
    expect(screen.queryByTestId("mission-lesson-toggle")).toBeNull();
  });

  it("renders the default 'Lesson' heading", () => {
    render(<LessonBlock introExcerpt="hello" />);
    const section = screen.getByTestId("mission-lesson");
    expect(section).toHaveAttribute("aria-label", "Lesson");
    expect(within(section).getByText("Lesson")).toBeInTheDocument();
  });

  it("respects a custom heading prop", () => {
    render(<LessonBlock introExcerpt="hello" heading="Quick Refresher" />);
    const section = screen.getByTestId("mission-lesson");
    expect(section).toHaveAttribute("aria-label", "Quick Refresher");
    expect(within(section).getByText("Quick Refresher")).toBeInTheDocument();
  });

  it("collapses excerpts longer than 500 chars and expands on click", () => {
    // Build a markdown string of plain text well above the threshold.
    const longText = "word ".repeat(150).trim(); // ~750 chars
    expect(longText.length).toBeGreaterThan(COLLAPSE_THRESHOLD);

    render(<LessonBlock introExcerpt={longText} />);

    const toggle = screen.getByTestId("mission-lesson-toggle");
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveTextContent("Show more");

    // Collapsed body ends with the ellipsis we appended.
    const body = screen.getByTestId("mission-lesson-body");
    expect(body.textContent ?? "").toContain("…");
    // And it is shorter than the full text.
    expect((body.textContent ?? "").length).toBeLessThan(longText.length);

    fireEvent.click(toggle);

    // After expanding, the toggle flips and the body grows.
    expect(toggle).toHaveTextContent("Show less");
    const expandedBody = screen.getByTestId("mission-lesson-body");
    expect(expandedBody.textContent ?? "").not.toContain("…");
  });

  it("renders markdown bold as <strong>", () => {
    render(<LessonBlock introExcerpt="This is **bold** text." />);
    const body = screen.getByTestId("mission-lesson-body");
    const strong = body.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe("bold");
  });

  it("renders markdown headings (## Topic) as <h2>", () => {
    // Pass via {} so the \n is an actual newline (JSX attribute strings
    // do not process escape sequences).
    render(<LessonBlock introExcerpt={"## Loops\n\nReturns nothing."} />);
    const body = screen.getByTestId("mission-lesson-body");
    const h2 = body.querySelector("h2");
    expect(h2).not.toBeNull();
    expect(h2?.textContent).toBe("Loops");
  });

  it("renders inline code as <code>", () => {
    render(<LessonBlock introExcerpt="Use `print()` to log." />);
    const body = screen.getByTestId("mission-lesson-body");
    const code = body.querySelector("code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toBe("print()");
  });

  it("does NOT render embedded <script> tags", () => {
    // react-markdown ignores raw HTML when no rehype-raw plugin is loaded,
    // so a literal <script> string in the markdown becomes plain text and
    // never reaches the DOM as an executable element.
    const malicious =
      "Hello\n\n<script>window.__pwned=true</script>\n\nWorld";
    const { container } = render(<LessonBlock introExcerpt={malicious} />);

    expect(container.querySelector("script")).toBeNull();
    // And the global side effect must not have fired.
    expect(
      (globalThis as Record<string, unknown>).__pwned,
    ).toBeUndefined();
  });

  it("does NOT render <iframe> tags", () => {
    const malicious =
      "Watch:\n\n<iframe src='https://evil.example'></iframe>";
    const { container } = render(<LessonBlock introExcerpt={malicious} />);
    expect(container.querySelector("iframe")).toBeNull();
  });
});
