"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, describeFailure, type Ran, type TurnSummary } from "@/lib/api";
import { ArtifactCard } from "@/components/ArtifactCard";
import { describeArgs, resultsOf, withoutCitations } from "@/lib/citations";
import { ArrowLeft, ChevronDown, Rocket, Send, Trash, Verified } from "@/components/Icon";

/**
 * The full-screen analysis workspace.
 *
 * ## Three zones, and each one answers a different question
 *
 * ```
 * ┌───────────────┬──────────────────────────────────┐
 * │ answer        │                                  │
 * │  "what does   │   canvas — the cards themselves  │
 * │   it say?"    │                                  │
 * ├───────────────┤        ┌──────────────┐          │
 * │ log           │        │  composer    │          │
 * │  "what have   │        └──────────────┘          │
 * │   I asked?"   │                                  │
 * └───────────────┴──────────────────────────────────┘
 * ```
 *
 * ## Why the canvas is cumulative
 *
 * A log entry is a **handle on its own results** — click it and the canvas
 * focuses the cards that entry produced. That only means anything if the
 * canvas keeps every turn's cards. Replacing them per question would make the
 * log a list of things you can no longer see.
 *
 * So: the canvas accumulates, the log is the index into it, and the left panel
 * shows one turn at a time — whichever the log has selected, newest by default.
 *
 * ## Why the composer is at the bottom here and at the top in the tab
 *
 * D-047 put it at the top and refused a bar at the foot of the window, because
 * in a **scrolling document** that reads as a chat column, and §14.1 names the
 * mental model as the thing this product is not. A floating composer over a
 * **canvas** is a different object: it is the tool you draw with, not the
 * conversation you are having. Narrowed rather than reversed, on the product
 * owner's decision.
 *
 * ## What is honestly missing
 *
 * Nothing renders in the canvas yet. The tools produce `report`, `matrix`,
 * `table` and `chart_spec`, and no renderer for any of them exists — so the
 * centre says so in a sentence. It does **not** show dotted placeholder slots:
 * D-047 built twenty-eight of those and D-081 removed them, because an outline
 * that will never fill is a promise the screen cannot keep (§14.5).
 */
/**
 * The kinds this canvas draws.
 *
 * `column_cards` and `stat_panel` are dead ends by design (§11.4.1): their
 * shape changes with a column's logical type, so five different layouts do not
 * fit one rectangle. The Profile tab and the column panel draw them, and a
 * card here would be a worse copy of a surface that already exists.
 */
const DRAWN = new Set(["table", "report", "matrix", "chart_spec"]);

export function AnalysisWorkspace({
  datasetId,
  datasetName,
}: {
  datasetId: string;
  datasetName: string;
}) {
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(true);
  const [panelOpen, setPanelOpen] = useState(true);
  const box = useRef<HTMLTextAreaElement>(null);
  const canvas = useRef<HTMLElement>(null);
  const label = useRef<HTMLSpanElement>(null);
  //: Whether the head's one line is showing the whole question.
  const [cut, setCut] = useState(false);

  /**
   * Read the log, and choose what the rail shows.
   *
   * `keepSelection` is false only after asking: a new question is the thing
   * you want to read, so the newest entry wins. Everywhere else a selection
   * the reader made survives a reload — losing it would move the panel out
   * from under somebody mid-sentence.
   */
  const load = useCallback(
    async (keepSelection = true) => {
      const history = await api.history(datasetId);
      setTurns(history.turns);
      // Newest first from the server, so the head is the last thing asked.
      const newest = history.turns[0]?.id ?? null;
      setSelected((current) =>
        keepSelection && current !== null && history.turns.some((t) => t.id === current)
          ? current
          : newest,
      );
    },
    [datasetId],
  );

  /**
   * Forget one turn, then read the log back.
   *
   * Re-read rather than spliced out of local state: the server is what the log
   * is, and a list that diverges from it after a failed delete is a list that
   * lies. Selection moves off the row that is going first, because pointing at
   * something deleted is how a panel ends up showing an answer with no entry.
   */
  const forget = useCallback(
    async (turnId: string) => {
      setSelected((current) => (current === turnId ? null : current));
      try {
        await api.forget(datasetId, turnId);
      } catch (cause) {
        setError(describeFailure(cause));
        return;
      }
      await load();
    },
    [datasetId, load],
  );

  useEffect(() => {
    void load().catch((cause) => setError(describeFailure(cause)));
  }, [load]);

  async function ask() {
    const text = question.trim();
    if (text === "" || busy) return;
    setBusy(true);
    setError(null);
    setAsked(text);
    setQuestion("");
    try {
      await api.ask(datasetId, text);
      // Reloaded rather than pushed onto the list from the response: `/ask`
      // returns a turn without its id or its timestamp, and a log whose newest
      // entry was assembled in the browser would disagree with the one the
      // server has the moment anything is reloaded.
      await load(false);
    } catch (cause) {
      setError(describeFailure(cause));
    } finally {
      setBusy(false);
      box.current?.focus();
    }
  }

  /**
   * Selecting a turn brings its cards into view.
   *
   * This is what makes the log an **index** rather than a list of things that
   * happened: the canvas keeps every turn, so an entry has somewhere to point.
   * Scrolling rather than filtering, because filtering would answer *show me
   * only this* — and the reader asked *take me to this*.
   */
  /**
   * Whether the head's single line is showing the whole question.
   *
   * Measured, because the same string fits or does not at every panel width,
   * and a character count would guess wrong at both ends. Re-run when the
   * question changes and when the panel opens, which are the two moments the
   * label's box exists at a new size.
   */
  useEffect(() => {
    const node = label.current;
    if (node === null) {
      setCut(false);
      return;
    }
    setCut(node.scrollWidth > node.clientWidth + 1);
  }, [selected, panelOpen, turns]);

  useEffect(() => {
    if (selected === null) return;
    const group = canvas.current?.querySelector(`[data-turn="${selected}"]`);
    // `nearest`: a card already on screen should not jump. Somebody clicking
    // an entry they can already see is orienting, not navigating.
    group?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selected]);

  const shown = turns.find((turn) => turn.id === selected) ?? null;

  return (
    <div className="workspace">
      <header className="workspace-bar">
        {/* Back to the tab the reader came from, not to the page's default.
            Landing on Profile after leaving the workspace is the page having
            forgotten where you were. */}
        <a className="workspace-exit" href={`/datasets/${datasetId}?tab=analysis`}>
          <ArrowLeft size={16} />
          <span>Exit full screen</span>
        </a>
        <h1 className="workspace-title">{datasetName}</h1>
      </header>

      {/* The canvas is the surface; the panel and the log float over it. Two
          cards rather than one rail, because they answer different questions
          and a reader closes one without losing the other. */}
      <div className="workspace-body">
        <main className="canvas" aria-label="Results" ref={canvas}>
          {error ? (
            <div className="banner error" role="alert">
              {error}
            </div>
          ) : null}

          {/* **Oldest first, and the newest at the bottom.** The canvas is a
              record of the work in the order it happened, and the composer is
              at the foot — so the card you just made is next to the box you
              made it with. */}
          {[...turns].reverse().map((entry) => (
            <section
              key={entry.id}
              className="turn"
              data-turn={entry.id}
              aria-current={entry.id === selected}
              aria-label={entry.question}
              /* **Anywhere in the group selects it**, not only the question.
                 The question stays a real button because that is the keyboard
                 path; this is a pointer shortcut over the same action. Not an
                 overlay: one would take the wheel and the tooltips away from a
                 chart, which is what the dataset card needed and this must
                 not. */
              onClick={() => setSelected(entry.id)}
            >
              <h2 className="turn-question">
                <button type="button" onClick={() => setSelected(entry.id)}>
                  {entry.question}
                </button>
                {/* **Beside the question, not on a card.** A card is one
                    result and this removes the whole turn — a trash can on the
                    chart would promise to delete the chart and take the answer
                    with it. It sits next to the thing it actually removes. */}
                <button
                  type="button"
                  className="turn-forget"
                  aria-label={`Forget “${entry.question}”`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void forget(entry.id);
                  }}
                >
                  <Trash size={13} />
                </button>
              </h2>

              <Cards datasetId={datasetId} turn={entry} />
            </section>
          ))}

          {/* §14.5: a sentence, not an outline. D-047 drew twenty-eight dashed
              slots here and D-081 removed them — a placeholder that will never
              fill is a promise the screen cannot keep. */}
          {turns.length === 0 ? (
            <p className="canvas-empty muted">
              Results appear here once there is something to draw.
            </p>
          ) : null}
        </main>

        {/* **One rail, not two anchors.** The panel and the log used to be
            positioned independently — `top` for one, `bottom` for the other —
            with viewport caps that summed to 104dvh, so on a short window they
            overlapped. Stacked in a column the log takes what it needs and the
            panel takes the rest, which is also what makes the panel grow when
            the log collapses. */}
        <div className="float-rail">
        <section
          className="float panel-answer"
          data-open={panelOpen}
          aria-label="Answer"
        >
          {/* **Always here, whatever the card holds.** It used to appear only
              once there was an answer, so an empty panel could not be closed
              and the card grew a new control the moment a question was asked.
              A card that changes shape halfway through is one you have to
              re-learn.

              Collapsed, this row **is** the card, so it carries the question
              rather than a pair of dots: two dots say something is hidden
              without saying what. */}
          <button
            type="button"
            className="float-head"
            aria-expanded={panelOpen}
            onClick={() => setPanelOpen((open) => !open)}
          >
            {shown && !busy ? <Grounded ok={shown.grounded} /> : null}
            <span className="float-head-label" ref={label}>
              {busy ? asked : (shown?.question ?? "Answer")}
            </span>
            <ChevronDown size={14} className="float-chevron" />
          </button>

          {panelOpen ? (
            <>
              <div className="float-body" aria-live="polite">
              {/* **Only when the head could not say it.** The head carries
                  the question already — that is what makes the collapsed card
                  meaningful — so repeating it below is two copies of one
                  sentence a centimetre apart. It earns its place exactly when
                  the head is cut, which is measured rather than guessed from a
                  character count: the same string fits or does not at every
                  panel width. */}
              {shown && !busy && cut ? <Asked text={shown.question} /> : null}

              {busy ? (
                <p className="muted" role="status">
                  Working on “{asked}”…
                </p>
              ) : shown ? (
                <Answer turn={shown} />
              ) : (
                <p className="muted">
                  Ask a question below. Every figure in the answer is computed
                  by a tool, and the tools that produced it are named underneath.
                </p>
              )}
              </div>
              {/* **Outside the scroller.** Who wrote the answer is a fact about
                  the whole card, so it stays put while the answer scrolls past
                  it — a footer, not the last line of the text. */}
              {shown && !busy ? <Wrote turn={shown} /> : null}
            </>
          ) : null}
        </section>

        {/* Anchored bottom-left, so the header is the part that never moves and
            the entries stack **above** it. Built the other way round the card
            would grow down out of the window. */}
        <section className="float panel-log" data-open={logOpen} aria-label="Agent log">
          {logOpen ? (
            turns.length === 0 ? (
              <p className="muted float-body">
                Questions you ask about this dataset are kept here.
              </p>
            ) : (
              <ol className="log-list" aria-label="Questions asked">
                {turns.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      className="log-entry"
                      aria-current={entry.id === selected}
                      onClick={() => setSelected(entry.id)}
                    >
                      <Grounded ok={entry.grounded} />
                      <span className="log-question">{entry.question}</span>
                    </button>
                    {/* A sibling, not a child: a button inside a button is
                        invalid HTML and the click belongs to whichever one the
                        browser feels like. Revealed on hover and on
                        `:focus-within`, so it is reachable by tab too. */}
                    <button
                      type="button"
                      className="log-forget"
                      aria-label={`Forget “${entry.question}”`}
                      onClick={() => void forget(entry.id)}
                    >
                      <Trash size={13} />
                    </button>
                  </li>
                ))}
              </ol>
            )
          ) : null}

          <button
            type="button"
            className="float-head log-head"
            aria-expanded={logOpen}
            onClick={() => setLogOpen((open) => !open)}
          >
            <Rocket size={15} />
            <span className="float-head-label">Agent log</span>
            {/* Next to the thing it counts, rather than in the far corner of
                the window. Closed, it is also the only sign there is anything
                inside. */}
            {turns.length > 0 ? (
              <span className="float-head-count muted">{turns.length}</span>
            ) : null}
            <ChevronDown size={14} className="float-chevron" />
          </button>
        </section>
        </div>
      </div>

      {/* Floating over the canvas rather than pinned to the window: on a canvas
          this is the tool you draw with. See the note above on D-047. */}
      <div className="workspace-composer">
        <textarea
          ref={box}
          className="ask"
          rows={1}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
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
  );
}

/**
 * Whether an answer passed §12.5, as a shape rather than as a colour.
 *
 * NFR-UX.3: colour is never the only carrier. A tick and a warning are
 * different drawings before they are different hues, and each says which it is
 * to a screen reader.
 */
function Grounded({ ok }: { ok: boolean }) {
  return ok ? (
    <Verified size={15} className="ok" aria-label="verified" />
  ) : (
    <span className="log-flag" aria-label="not verified">
      !
    </span>
  );
}

/**
 * What a turn produced, drawn.
 *
 * **Results only.** A histogram is `bin_column` then `plot`, and drawing both
 * puts the bands beside the picture of the bands — the same fact twice, with
 * the intermediate taking the wider card. `resultsOf` keeps the steps nothing
 * else read, which is exact rather than a guess about which tool matters.
 *
 * ⚠️ **The receipt below the answer still lists every step**, and it has to:
 * that is where a reader sees the chart came from `bin_column(n_bins=10)`
 * rather than from somewhere unnamed. Hiding a step from the canvas is a
 * layout decision; hiding it from the provenance would be a different and
 * worse one.
 */
function Cards({ datasetId, turn }: { datasetId: string; turn: TurnSummary }) {
  const drawn = resultsOf(turn.steps).filter((step) => DRAWN.has(step.output_kind));

  if (drawn.length === 0) {
    // §14.5 again: name which kind of empty this is. A turn that ran six tools
    // and drew nothing is a different thing from one that ran none, and a
    // blank space says neither.
    return (
      <p className="muted turn-empty">
        {turn.stopped ??
          (turn.steps.length === 0
            ? "This question ran no tools."
            : "This answer produced nothing the canvas draws.")}
      </p>
    );
  }

  return (
    <div className="turn-cards">
      {drawn.map((step) => (
        <ArtifactCard
          key={step.ref}
          datasetId={datasetId}
          refId={step.ref}
          tool={step.tool}
          outputKind={step.output_kind}
        />
      ))}
    </div>
  );
}

/**
 * One turn in the panel.
 *
 * The same honesty the tab already keeps: §12.5 rule 3 **flags** an unverified
 * answer rather than hiding it, because a confident sentence with nothing
 * behind it is worse than no sentence — there is no way to tell from reading.
 */
function Answer({ turn }: { turn: TurnSummary }) {
  // The ids the model wrote, so the bare form is only read where it resolves.
  const known = new Set(turn.steps.map((step) => step.ref));

  return (
    <div className="answer" data-grounded={turn.grounded}>

      {turn.narrative ? (
        <p className="narrative">{withoutCitations(turn.narrative, known)}</p>
      ) : (
        <p className="muted">
          {turn.stopped ?? "The model did not produce an answer."}
        </p>
      )}

      {turn.complaints.length > 0 ? (
        <div className="banner warn" role="alert">
          <strong>Not verified.</strong> This answer failed the citation check,
          so it is shown as written rather than as fact:
          <ul>
            {turn.complaints.map((complaint) => (
              <li key={`${complaint.kind}:${complaint.detail}`}>
                {complaint.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {turn.steps.length > 0 ? <Receipt steps={turn.steps} /> : null}
    </div>
  );
}

/**
 * The question this answer belongs to, wrapped rather than cut.
 *
 * Clamped to four lines with a control to open it, because the panel is a
 * fixed width and a paragraph-long prompt would otherwise push the answer out
 * of view — the thing the reader came for. The control appears only when there
 * is something behind it: an *expand* that reveals nothing is furniture.
 */
function Asked({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const body = useRef<HTMLParagraphElement>(null);
  const [clipped, setClipped] = useState(false);

  useEffect(() => {
    const node = body.current;
    if (node === null) return;
    // Measured rather than guessed from a character count: the same string
    // wraps to a different number of lines at every panel width.
    setClipped(node.scrollHeight > node.clientHeight + 1);
  }, [text]);

  return (
    <div className="asked" data-open={open}>
      <p className="asked-text" ref={body}>
        {text}
      </p>
      {clipped ? (
        <button type="button" className="asked-more" onClick={() => setOpen((was) => !was)}>
          {open ? "Show less" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Who wrote this, in the quietest type on the card.
 *
 * **The model, not the rung.** `gemini#2` names which of three accounts paid
 * for the call, which matters to a bill and to nobody reading an answer;
 * `gemini-3.5-flash-lite` is what shaped the sentence, and it is the question
 * asked first when one looks wrong. The account is on the wire for §12.8 and
 * deliberately not on the screen.
 *
 * Absent rather than blank when it was not recorded: every turn stored before
 * this existed has an empty string, and *via* followed by nothing would read
 * as a bug rather than as an older row.
 */
function Wrote({ turn }: { turn: TurnSummary }) {
  if (!turn.model) return null;
  return (
    <p className="answer-model faint">
      via <span className="mono">{turn.model}</span>
    </p>
  );
}

/**
 * What produced the answer: the tools, with their arguments a hover away.
 *
 * **The name and the arguments, and no id** (D-099). A `computation_id` says
 * *which row*; `aggregate · group_by=Pclass` says *why the number is what it
 * is*, which is the question a reader of an answer actually has.
 *
 * ## Why the popup is positioned from the viewport
 *
 * It lives inside `.float-body`, which scrolls — an absolutely positioned
 * tooltip would be clipped by that overflow the moment the receipt sat near
 * the bottom of a long answer. `position: fixed` takes the viewport as its
 * containing block instead, so nothing between here and the window can cut it
 * off.
 *
 * ⚠️ **That holds only while no ancestor has a `transform`, `filter` or
 * `contain`**, any of which would quietly make itself the containing block and
 * bring the clipping back. This stylesheet has already been bitten by exactly
 * that — a marquee's transform capturing a pseudo-element — so it is named
 * here rather than left to be rediscovered.
 *
 * Hover **and** focus, so the arguments are reachable without a mouse; a tap
 * focuses too, which is how this works on a touch screen.
 */
function Receipt({ steps }: { steps: Ran[] }) {
  const [at, setAt] = useState<{ ref: string; x: number; y: number } | null>(null);
  const active = steps.find((step) => step.ref === at?.ref) ?? null;

  const show = (ref: string) => (event: { currentTarget: HTMLButtonElement }) => {
    const box = event.currentTarget.getBoundingClientRect();
    // Clamped off the left edge; the right is handled by `max-width`, and the
    // rail this sits in is on the left of the window anyway.
    setAt({ ref, x: Math.max(8, box.left), y: box.bottom + 6 });
  };

  return (
    <div className="receipt">
      <ul className="tools">
        {steps.map((step) => (
          <li key={step.ref}>
            <button
              type="button"
              className="tool-chip caps"
              aria-describedby={at?.ref === step.ref ? "tool-args" : undefined}
              onMouseEnter={show(step.ref)}
              onFocus={show(step.ref)}
              onMouseLeave={() => setAt(null)}
              onBlur={() => setAt(null)}
            >
              {step.tool}
            </button>
          </li>
        ))}
      </ul>
      {active && at ? (
        <p
          id="tool-args"
          role="tooltip"
          className="mono tool-args"
          style={{ left: at.x, top: at.y }}
        >
          {describeArgs(active.args, steps)}
        </p>
      ) : null}
    </div>
  );
}
