"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Expand, Send } from "@/components/Icon";
import { ArtifactCard } from "@/components/ArtifactCard";
import { type TurnSummary, api, describeFailure } from "@/lib/api";
import { resultsOf } from "@/lib/citations";

/**
 * The Analysis tab — **a layout prototype, and nothing in it runs.**
 *
 * ## What this is for
 *
 * The composer is real: it types, it grows, it submits. Everything below it is
 * an empty box. The point is to settle the shape of this surface before there
 * is an executor to fill it, so that the day results are real the argument is
 * about the results rather than about where they go.
 *
 * The one line above the grid says so on screen. §14.5 is explicit that an
 * empty region must announce its emptiness rather than imply a capability —
 * *"a Run Log with sample rows implies traceability that does not exist, and P3
 * is not a promise to treat casually"* — so the boxes are dashed outlines with
 * their own name on them, never a drawn chart with invented numbers.
 *
 * ## Why the tab is called Analysis and not Canvas
 *
 * **D-014** removed the free whiteboard from this product and replaced it with
 * the Findings Board; §16 lists it as a non-goal. What is built here is not a
 * whiteboard — the system lays the results out, nobody drags them — so the
 * conflict is with the *word*, not the thing. That is still worth avoiding: a
 * tab labelled Canvas invites the next person to add dragging, layering and
 * z-order, and to feel they are completing it. `Analysis` is what §9.2 already
 * calls this: *one exploration session over one Dataset + SchemaContract*.
 *
 * ## There was a second door here, and it was removed
 *
 * `Add a step` sat beside `Ask` at the same weight, and the reason it did was
 * **INV-1** (every Step the copilot creates must also be creatable manually,
 * identical but for `origin`) and **P2** (the product must be 100% useful
 * without AI). D-047 argued that a page designed around one door cannot be
 * given a second one later without being rebuilt, and put it there on the first
 * sketch for exactly that reason.
 *
 * **D-049 revoked both, at the owner's direction.** The prompt is the only door
 * now. The objection was made twice with its costs and overruled twice; the
 * full accounting is in the ADR, including the part that costs most — R-18's
 * ceiling was P2, and it went with it.
 *
 * What survives is the shape of this file: the composer is a band with a field
 * and one action, and a second action would still fit beside the first. That is
 * the whole of what D-047's argument bought, and it is not nothing.
 *
 * ## Why the grid preserves order
 *
 * Masonry packs tighter and was rejected for it. It fills gaps by pulling later
 * items up into earlier columns, so result 7 can appear above result 5 — and
 * §14.1 states the mental model as *"every step is recorded, and I can go back
 * to any of them"*. Order is content here, not styling.
 *
 * Instead: twelve columns, and each result declares its own span. Sizes still
 * vary — that was the requirement — but rows never reorder. The ragged bottom
 * edge of a row is correct here, and is the opposite of the call made for the
 * preview grid a day earlier: there you scan *down* a column of like values, so
 * uneven rows break the scan; here each figure is its own object.
 */

//: What a placeholder stands in for, and how much room that kind of result
//: wants. Spans are out of twelve; heights are the box's minimum.
//:
/**
 * The kinds this board draws (§11.4.1).
 *
 * `column_cards` and `stat_panel` are dead ends by design: their shape follows
 * a column's logical type, and five layouts do not fit one rectangle. The
 * Profile tab draws them.
 */
const DRAWN = new Set(["table", "report", "matrix", "chart_spec"]);

export function AnalysisBoard({ datasetId }: { datasetId: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  /**
   * Every result this dataset has produced, newest first.
   *
   * Read from the server rather than kept from the last answer: the same
   * turns are on the workspace's canvas, and two surfaces that each remember
   * their own half of a conversation disagree the first time one of them is
   * reloaded.
   *
   * **Newest first, and that is the same rule the canvas follows, not the
   * opposite one.** Both put the newest result nearest the composer; the
   * composer is at the foot there and at the head here, so the order flips
   * with it.
   */
  const load = useCallback(async () => {
    const history = await api.history(datasetId);
    setTurns(history.turns);
  }, [datasetId]);

  useEffect(() => {
    void load().catch((cause) => setError(describeFailure(cause)));
  }, [load]);

  const cards = turns.flatMap((entry) =>
    resultsOf(entry.steps).filter((step) => DRAWN.has(step.output_kind)),
  );

  /**
   * What the newest question produced, when it produced nothing to draw.
   *
   * **Not the panel coming back.** A question that ran out of steps, hit a
   * rate limit, or answered with a profile the canvas does not draw would
   * otherwise leave this surface exactly as it was — the busy line vanishes
   * and nothing replaces it, which is indistinguishable from never having
   * asked. §14.5 and P6: say which kind of nothing this is.
   */
  const newest = turns[0] ?? null;
  const silent =
    newest !== null &&
    resultsOf(newest.steps).filter((step) => DRAWN.has(step.output_kind)).length === 0
      ? (newest.stopped ??
        "That question was answered in words rather than in a chart. " +
          "The answer is in the full-screen workspace.")
      : null;

  // Grows with what is typed instead of scrolling inside itself. Reset to
  // `auto` first, or the height only ever ratchets upward as text is deleted.
  useEffect(() => {
    const element = box.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [question]);

  async function ask() {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setAsked(text);
    try {
      await api.ask(datasetId, text);
      await load();
    } catch (cause) {
      setError(describeFailure(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="analysis">
      {/* Sticky, so it stays reachable however far the stack grows — and at the
          top rather than at the foot, because a bar pinned to the bottom of the
          window reads as a chat composer, and §14.1 names the mental model as
          the thing this product is *not*: "I am working with data", not "I am
          chatting with an AI about data". */}
      <div className="composer">
        <textarea
          ref={box}
          className="ask"
          rows={1}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          // Enter sends; Shift+Enter is a newline. The field grows, so the
          // second one has to exist.
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void ask();
            }
          }}
          placeholder="Ask a question about this data…"
          aria-label="Ask a question about this data"
          disabled={busy}
        />
        <div className="composer-actions">
          <button
            type="button"
            className="icon-button"
            aria-label="Ask"
            onClick={() => void ask()}
            disabled={busy || question.trim() === ""}
          >
            <Send size={18} />
          </button>
        </div>
      </div>

      {/* A turn is up to seven model calls, so this is seconds and not
          milliseconds. Saying which question is in flight matters more here
          than a spinner does: the answer arrives long after the field cleared
          from the reader's mind. */}
      {busy ? (
        <p className="muted analysis-note" role="status">
          Working on “{asked}”…
        </p>
      ) : null}

      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      {/* **Cards, and only cards.** The narration, the receipt and the log
          live in the workspace; this surface is the board they produced.
          Horizontal first and wrapping down, so a row fills before a new one
          starts — each card is already as wide as what it holds. */}
      {cards.length > 0 ? (
        <div className="board-cards">
          {cards.map((step) => (
            <ArtifactCard
              key={step.ref}
              datasetId={datasetId}
              refId={step.ref}
              tool={step.tool}
              outputKind={step.output_kind}
            />
          ))}
        </div>
      ) : null}

      {silent !== null && !busy ? (
        <p className="muted analysis-note">{silent}</p>
      ) : null}

      {cards.length === 0 && silent === null && !busy && error === null ? (
        <p className="muted analysis-note">
          Ask a question about this dataset. What the tools draw appears here;
          the answer that goes with it is in the full-screen workspace.
        </p>
      ) : null}

      {/* The way into the workspace. Bottom-right and floating, because it is
          a change of surface rather than a step in the reading: putting it in
          the flow would make it something to scroll past on the way to the
          answer. A link rather than a button — it goes to a URL, and the
          middle-click, the back button and the bookmark should all work. */}
      <a
        className="fullscreen-entry"
        href={`/datasets/${datasetId}/analysis`}
        aria-label="Open the full-screen workspace"
      >
        <Expand size={16} />
        <span>Full screen</span>
      </a>
    </div>
  );
}
