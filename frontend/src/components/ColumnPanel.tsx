"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Ellipsis } from "@/components/Ellipsis";
import { LoadFailure } from "@/components/LoadFailure";
import {
  type Bin,
  type ColumnDetail,
  type TopValue,
  api,
  describeFailure,
} from "@/lib/api";

/**
 * One column, in depth (§11.7) — the panel behind a profile card.
 *
 * ## A dialog that navigates, which is the resolution of an old objection
 *
 * §11.7.6(f) says **panel, not modal**, and gives a reason rather than a
 * preference: *"a modal forces you to close before looking at another column;
 * a panel lets you move prev/next without losing context — which is exactly how
 * an analyst sweeps new data."*
 *
 * The owner asked for a popup. Rather than pick one, this takes the objection
 * literally: it is a dialog **with ← → column navigation built in**, so the
 * thing §11.7.6(f) was protecting — sweeping columns without closing — is what
 * it does. What the dialog adds over a side panel is the room to show seven
 * quantiles and two lists of extremes without squeezing the grid behind it.
 *
 * ## Why the whole card is the trigger, and the badge still is not
 *
 * The type badge inside each card opens the type picker (FR-C.2, D-046). A
 * click handler on the `<article>` would fire for badge clicks too unless
 * somebody remembered to stop the event — and *"somebody remembers"* is the
 * failure mode this project keeps writing tests against.
 *
 * So the card carries an **overlay link**, the same shape the dataset card on
 * the home screen uses: a stretched button that sits *under* the badge in the
 * stacking order. Two sibling controls, no event plumbing, and nothing to
 * remember.
 */
export function ColumnPanel({
  datasetId,
  column,
  columns,
  onClose,
  onNavigate,
}: {
  datasetId: string;
  column: string;
  /** Every column on the tab, in file order — what ← and → walk. */
  columns: string[];
  onClose: () => void;
  onNavigate: (column: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [detail, setDetail] = useState<ColumnDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Which way the last move went, so the incoming card is dealt from the side
  // it came from. A card that always flies in from the right would make → and
  // ← feel like the same gesture.
  const [dealt, setDealt] = useState<"next" | "previous">("next");

  const at = columns.indexOf(column);
  const previous = at > 0 ? columns[at - 1] : null;
  const next = at >= 0 && at < columns.length - 1 ? columns[at + 1] : null;

  function walk(to: string | null | undefined, way: "next" | "previous") {
    // `undefined` as well as `null`: `columns[at - 1]` is typed optional under
    // `noUncheckedIndexedAccess`, and an out-of-range step is the same nothing
    // as a step from the end of the deck.
    if (to === null || to === undefined) return;
    setDealt(way);
    onNavigate(to);
  }

  const load = useCallback(async () => {
    setDetail(null);
    setError(null);
    try {
      setDetail(await api.columnProfile(datasetId, column));
    } catch (cause) {
      setError(describeFailure(cause));
    }
  }, [datasetId, column]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const element = dialog.current;
    if (element !== null && !element.open) element.showModal();
  }, []);

  /**
   * ← and → walk the deck, bound on the **document**.
   *
   * They were on the dialog, and that worked only by a browser's kindness:
   * `key={column}` remounts the whole card on every step, so whatever had
   * focus is destroyed mid-gesture and Chrome hands focus back to the dialog
   * itself. React's handler then still fires — until the day something else
   * ends up focused, or another engine parks focus on `<body>` instead, and
   * the second press of → quietly does nothing.
   *
   * A `showModal()` dialog traps focus, so a document listener cannot fire
   * while anything else on the page is being read — the same argument the
   * dialog-bound version used, now without depending on where focus landed.
   * `preventDefault` because ← and → also scroll, and stepping to the next
   * column while the old one's scroll position moves is two answers to one
   * keypress.
   */
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") walk(previous, "previous");
      else walk(next, "next");
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  return (
    <dialog
      ref={dialog}
      className="column-panel"
      aria-labelledby="column-panel-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      {/* `key` is the whole animation. Changing column remounts this subtree,
          which replays the CSS that deals it in — and resets the scroll to the
          top, which is what you want when the content underneath is a different
          column entirely. */}
      <div
        key={column}
        className="panel-body typed"
        data-type={detail?.logical_type}
        data-dealt={dealt}
      >
        <header className="panel-head">
          <div className="panel-name">
            <Ellipsis as="h2" className="mono">
              {column}
            </Ellipsis>
            {detail ? (
              <span
                className="pill tag"
                title={`stored as ${detail.physical_type}`}
              >
                {detail.logical_type}
              </span>
            ) : null}
          </div>

          {/* **`3 of 24` is gone** (D-067), at the product owner's request. It
              was argued for twice — first when the panel was built, then again
              when the arrows left the header and it stayed behind — on the
              grounds that arrows alone leave you counting, and that knowing a
              sweep is nearly done is most of why anyone keeps sweeping. That
              reading has not changed; the decision has. What is left to say
              where you are is the chevrons going grey at the ends of the
              deck. */}
          <div className="panel-nav">
            <button
              type="button"
              className="panel-close"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </header>

        {/* The scroller starts **here**, below the header, so its bar does
            too. The header used to be `position: sticky` inside this box,
            which keeps it on screen but leaves the scrollbar running the full
            height of the card — past the name and the way out, which do not
            scroll and have no business being beside a bar that says something
            does. */}
        <div className="panel-scroll">
          {error ? (
            <LoadFailure message={error} onRetry={() => void load()} />
          ) : detail === null ? (
            <p className="muted">Reading this column…</p>
          ) : (
            <Detail detail={detail} />
          )}
        </div>
      </div>

      {/* Last in the DOM although they sit at the far left and right, because
          `showModal()` focuses the **first** focusable descendant — and with
          the chevrons first, opening a column put the keyboard on *Previous
          column* and a stray Enter walked backwards out of the card you had
          just chosen. The close button is the first control now.

          Outside the card, pinned to the viewport rather than to the dialog:
          they are how you move *between* cards, and a control that belongs to
          the deck rather than to one card should not sit inside one. Fixed
          positioning works here because a `showModal()` dialog and its children
          live in the top layer together — and because nothing between them and
          the viewport is transformed, which the dealt-card animation is careful
          to keep true by living on `.panel-body`. */}
      <button
        type="button"
        className="deck-step"
        data-side="previous"
        onClick={() => walk(previous, "previous")}
        disabled={!previous}
        aria-label={`Previous column${previous ? `: ${previous}` : ""}`}
      >
        ‹
      </button>
      <button
        type="button"
        className="deck-step"
        data-side="next"
        onClick={() => walk(next, "next")}
        disabled={!next}
        aria-label={`Next column${next ? `: ${next}` : ""}`}
      >
        ›
      </button>
    </dialog>
  );
}

function Detail({ detail }: { detail: ColumnDetail }) {
  /**
   * **D-051.** A numerical column with values leads with the descriptive
   * table, and that table subsumes two things the other four types still show
   * above their shape: §11.7.7's narrative and the Completeness block.
   *
   * Neither is dropped for tidiness. The narrative's numeric branch reads out
   * the median, the mean, the skew direction and the fence — every one of
   * which is now a labelled row a few pixels below it, and the fence is
   * written under the boxplot that draws it. Completeness is the table's own
   * `Count & missing` group, counting the same things by the same rules.
   * Saying either twice would be the panel disagreeing with itself about which
   * copy to trust.
   *
   * A column with **no** values keeps both, and that is not an inconsistency
   * to be tidied away later: there is no descriptive table to write when there
   * is nothing to describe, and the narrative is then the only thing here that
   * can say *which kind of absent* (§11.8.3).
   */
  /**
   * **Has this type been given a table yet?**
   *
   * Two have — numerical (D-051) and categorical (D-060) — and for both the
   * table says what §11.7.7's sentence says, line for line: *"Most frequent
   * 'SKU-001' at 34.4%"* is row 1, *"the top five cover 64.9%"* is row 5's
   * cumulative column. The copy nobody updates is always the prose one.
   *
   * **The Completeness block goes with it**, and on the categorical panel it
   * survived exactly one revision. It was kept there on the argument that it
   * carries the split between NULL and `""` which D-059 had just cost the
   * numerical panel; the product owner read that argument and removed it
   * anyway. So no panel with a table can say *which kind* of missing a value
   * is, and the only figure left is the total, in the strip's caption above.
   * Recorded as debt rather than argued a third time.
   */
  const done = detail.completeness;

  /**
   * **The strip goes first, above everything** — narrative included.
   *
   * *Is this column even there* is the question that decides whether any
   * figure under it is worth reading, and *where* the gaps sit is the part of
   * it no count answers. For a numerical column that also reverses D-051's
   * *table first, figures after*; the order still holds for the three figures
   * further down, and this one is not really a figure.
   *
   * **Only two types draw it so far, and that is a list rather than a rule.**
   * `presence` is computed for all five (D-056) because completeness is the one
   * thing every column has. Numerical and categorical are the two the product
   * owner has reviewed; `text`, `date` and `boolean` get it when their panels
   * are reshaped, and turning it on is this condition.
   */
  return (
    <>
      {/* **Every panel opens with the strip, and an empty column is only the
          strip.** All five logical types have their own shape now, so §11.7.7's
          sentence and the Completeness block have nowhere left to stand: each
          panel says in figures what that sentence said in words, and the block
          was the last thing `text` still rendered.

          §11.7.6(c) is untouched — the narrative is still computed, still on
          the wire, and still inherits the bundle's `computation_id`. What it
          has lost is a **reader**. Recorded as debt rather than removed: taking
          it out is a version bump for no visible gain, and the surface most
          likely to want it back (a citable summary, or Phase 5's narrator) has
          not been built. */}
      <Presence it={detail.presence} done={done} />

      {detail.numeric ? (
        <Numeric
          it={detail.numeric}
          done={detail.completeness}
          card={detail.cardinality}
        />
      ) : null}
      {detail.categorical ? (
        <Categorical it={detail.categorical} present={done.present} />
      ) : null}
      {detail.text ? <Text it={detail.text} present={done.present} /> : null}
      {detail.date ? (
        <DateShape it={detail.date} present={done.present} />
      ) : null}
      {detail.boolean ? (
        <Boolean it={detail.boolean} present={done.present} />
      ) : null}

      {/* **The receipt is gone (D-052), for the third time.**

          `profile_column v5 · a3b89c7a · 125 ms`, with the full fingerprint in
          its tooltip, was the only place INV-5's *"every number comes from a
          Computation that can be referenced"* could actually be read by a
          person. It has now been cut from the header (2026-07-31), from above
          the profile grid (D-044) and from here — and §14.2's written promise
          when the first went was that the shape could change *but it has to
          come back*.

          **The model has not moved.** `computation_id`, `fingerprint`,
          `tool_version` and `duration_ms` are still computed, still stored,
          still on the wire in `ColumnDetail`. Bringing a fourth shape back is
          a component's worth of work, not a data one — which is exactly what
          was said of the second, five days before it was cut. */}
    </>
  );
}

/**
 * §11.7.3 for a numerical column: the table first, then the three figures that
 * draw what it says, then the values no figure can show you.
 *
 * The order is the argument. A reader who came for a number reads down and
 * stops; a reader who came for a shape scrolls once and gets three views of
 * one axis. The layout before D-051 interleaved them — histogram, statistics,
 * quantiles, fence, extremes — so neither reader could skim.
 */
function Numeric({
  it,
  done,
  card,
}: {
  it: NonNullable<ColumnDetail["numeric"]>;
  done: ColumnDetail["completeness"];
  card: ColumnDetail["cardinality"];
}) {
  const q = new Map(it.quantiles.map((point) => [point.q, point.value]));
  const outlierShare = done.present === 0 ? 0 : it.outlier_count / done.present;

  return (
    <>
      <div className="stat-table">
        <StatBand
          title="Central tendency"
          rows={[
            ["mean", num(it.mean)],
            ["median", num(it.median)],
            ["mode", num(it.mode)],
          ]}
        />
        <StatBand
          title="Dispersion"
          rows={[
            ["std", num(it.std)],
            // Variance is std², in squared units nobody reads directly. It is
            // here because a descriptive table is where a reader expects to
            // find it, not because it says anything std does not.
            ["variance", num(it.variance)],
            ["range", num(it.value_range)],
            ["IQR", num(it.iqr)],
          ]}
        />
        <StatBand
          title="Position"
          rows={[
            ["min", num(it.minimum)],
            ["Q1", num(q.get(0.25) ?? null)],
            ["Q3", num(q.get(0.75) ?? null)],
            ["max", num(it.maximum)],
          ]}
        />
        <StatBand
          title="Percentiles"
          rows={it.quantiles.map(
            (point) =>
              [`p${Math.round(point.q * 100)}`, num(point.value)] as const,
          )}
        />
        <StatBand
          title="Distribution shape"
          rows={[
            // Both are dimensionless, and both have a reference value — which
            // is the only reason either can be read on its own at all.
            //
            // Four digits, where every other figure in this table gets seven.
            // These two are read as magnitudes — is it 0, is it 1, is it 5 —
            // and no reading of a column changes between `4.731` and
            // `4.730719`. `p99 823,698`, next to them, is a value somebody may
            // go and look up in the file.
            [
              "skewness",
              brief(it.skewness),
              "0 is symmetric · positive means a longer right tail",
            ],
            [
              "kurtosis",
              brief(it.kurtosis),
              "excess kurtosis (Fisher) · a normal distribution is 0",
            ],
          ]}
        />
        {/* **`Count & missing` is gone (D-059)**, at the product owner's
            request, and three things went with it.

            **The separation of `null` from `""`.** §11.7.3 asks for it and this
            panel was the only surface in the product that drew it — everywhere
            else `_PRESENT` already treats them alike. A numerical column now
            reports how much is missing and not which kind of missing, and the
            reader who needs to know cannot find out here.

            **`zero` and `negative`**, which are facts only a number column has:
            `discount_pct` holds 156 zeros, and that is the difference between
            *no discount was given* and *no discount was recorded*.

            **`rows` and `present`**, whose job passed to the strip above — its
            caption carries the total missing and its hover carries row numbers.

            The reader still gets the *amount* missing. What is gone is every
            way of asking what kind. */}
        <StatBand
          title="Uniqueness"
          rows={[
            ["distinct", card.distinct.toLocaleString("en")],
            // `repeated 0` says *every value appears once* without needing a
            // row whose value is the word "no".
            [
              "repeated",
              Math.max(0, done.present - card.distinct).toLocaleString("en"),
            ],
          ]}
        />
      </div>

      <Figures it={it} q={q} outlierShare={outlierShare} />

      {/* **Extremes cut (D-052).** It showed the five values at each end, and
          it was the only place the panel quoted the file rather than summarised
          it — which is what let a reader spot a sentinel (`0`, `-1`, `9999`)
          sitting in the data being counted as a measurement, and see whether
          the maximum stood apart from its neighbours or sat at the end of a
          smooth tail.

          `smallest` and `largest` are still computed and still on the wire.
          What replaced them on screen is nothing; `min` and `max` in the
          Position group are what is left of that end of the column. */}
    </>
  );
}

/**
 * Completeness in file order — missingno's matrix, for one column, horizontal.
 *
 * Each slot is a run of consecutive file rows, and its **opacity is the share
 * of that run which is there**. That is not a stylistic choice: at 240 slots a
 * 1,200-row column puts five rows in each, and five rows are not all present
 * or all absent. Drawing a slot solid unless it were entirely null would round
 * every scattered gap away — which on Titanic's `Age` is 140 slots out of 223,
 * the whole finding.
 *
 * A track sits behind the slots so the strip's extent is visible where nothing
 * is: without it, a column that is missing from row 900 onward would simply
 * stop, and a strip that stops looks like a strip that was not drawn.
 *
 * **What this is not.** `missingness_report` (§11.4, P0) compares columns —
 * which ones go missing together, and whether that is a pattern. This is one
 * column's own shape over row order, and it needs nothing but the column it
 * belongs to. The boundary is the same one the moments follow: `profile_column`
 * describes **one** column, the analyzers compare **several**.
 */
function Presence({
  it,
  done,
}: {
  it: ColumnDetail["presence"];
  done: ColumnDetail["completeness"];
}) {
  const [over, setOver] = useState<number | null>(null);
  if (it.slots.length === 0) return null;
  const nothing = done.present === 0;

  // **One word, `missing`.** It said `absent` and named the kinds — `832
  // empty`, `177 null` — because a caption reading *"832 missing"* directly
  // under a table row reading `null 0 (0%)` was two true statements arriving
  // as a contradiction (the failure that took this tool from v3 to v4). D-059
  // removed that table row, so there is nothing left for the word to disagree
  // with, and the product owner asked for one term rather than three.
  //
  // What it costs is stated where the band was removed: nothing on a numerical
  // panel says which *kind* of missing any more.
  const missing = done.total - done.present;
  const slot = over === null ? undefined : it.slots[over];
  const from = over === null ? 0 : over * it.rows_per_slot + 1;

  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      0.999999,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    setOver(Math.floor(fraction * it.slots.length));
  }

  return (
    <figure className="figure">
      <div
        className="presence"
        role="img"
        aria-label={
          `Completeness in file order across ${done.total.toLocaleString("en")} rows.` +
          ` ${missing === 0 ? "None missing" : `${missing.toLocaleString("en")} missing`}.`
        }
        onPointerMove={probe}
        onPointerLeave={() => setOver(null)}
      >
        {it.slots.map((run, index) => (
          <span
            // Position is the identity: two slots holding the same counts are
            // still different runs of the file.
            // eslint-disable-next-line react/no-array-index-key
            key={index}
            className="slot"
            style={{ opacity: run.rows === 0 ? 0 : run.present / run.rows }}
          />
        ))}
        {over === null ? null : (
          <span
            className="presence-cursor"
            style={{ left: `${((over + 0.5) / it.slots.length) * 100}%` }}
          />
        )}
      </div>
      {/* For a column with nothing in it the caption stops summarising and
          starts **stating**, in `--danger` — the colour this stylesheet reserves
          for *this failed, or will destroy something*, and the same one the
          close button and the delete control take on hover. An empty column is
          not a warning about the future; it is a fact that will make every
          analysis downstream of it empty too, and it should be impossible to
          scroll past.

          It says **which kind** of empty, and that distinction now lives here
          alone: D-059 and D-061 took the NULL-versus-`""` split off the panels
          that have tables, and a column with nothing in it has no table. */}
      <figcaption
        className="chart-note"
        data-lit={over !== null}
        data-empty={nothing || undefined}
      >
        {nothing
          ? absence(done)
          : slot === undefined
            ? `completeness · ${
                missing === 0
                  ? "none missing"
                  : `${missing.toLocaleString("en")} missing (${share(missing / done.total)})`
              }`
            : `rows ${from.toLocaleString("en")} – ${(from + slot.rows - 1).toLocaleString("en")} · ${
                slot.rows === slot.present
                  ? "all present"
                  : `${(slot.rows - slot.present).toLocaleString("en")} of ${slot.rows} missing`
              }`}
      </figcaption>
    </figure>
  );
}

/**
 * What a column holds when it holds nothing — said in full, and named by kind.
 *
 * A NULL is an absent answer and a `""` is an answer that says nothing, and a
 * column can be entirely one, entirely the other, or a mix. That is the whole
 * of what there is to report, so it is reported precisely rather than as
 * *"empty"*.
 */
function absence(done: ColumnDetail["completeness"]): string {
  const rows = done.total.toLocaleString("en");
  if (done.nulls === done.total)
    return `No value in any of the ${rows} rows: all of them NULL.`;
  if (done.empty === done.total) {
    return `No value in any of the ${rows} rows: all of them empty strings.`;
  }
  return (
    `No value in any of the ${rows} rows:` +
    ` ${done.nulls.toLocaleString("en")} NULL, ${done.empty.toLocaleString("en")} empty strings.`
  );
}

/**
 * Histogram, boxplot and ECDF over **one** x axis, drawn at one width.
 *
 * Sharing the axis is the whole reason they are stacked rather than laid out
 * as three cards. The peak of the histogram sits above the box that contains
 * it; the tail sits above the hairline that measures it; the place where the
 * bars thin out sits above the whisker cap that says where the fence fell.
 * Three figures on three scales would each be true, and none of them would
 * answer a question raised by the others.
 */
function Figures({
  it,
  q,
  outlierShare,
}: {
  it: NonNullable<ColumnDetail["numeric"]>;
  q: Map<number, number>;
  outlierShare: number;
}) {
  const bins = it.bins;
  const lo = bins.at(0)?.lower;
  const hi = bins.at(-1)?.upper;
  if (lo === undefined || hi === undefined) return null;
  // A column where every value is the same has a histogram — one bar — and no
  // axis to spread anything along. A box of zero width and a vertical ECDF
  // would be two figures whose only content is that they are degenerate.
  const spread = hi > lo;
  const at = (value: number) =>
    Math.min(100, Math.max(0, ((value - lo) / (hi - lo)) * 100));

  const q1 = q.get(0.25);
  const q3 = q.get(0.75);
  const boxable =
    spread &&
    q1 !== undefined &&
    q3 !== undefined &&
    it.median !== null &&
    it.whisker_low !== null &&
    it.whisker_high !== null &&
    it.minimum !== null &&
    it.maximum !== null;

  return (
    <div className="figures">
      <figure className="figure">
        {/* The keys sit outside the plot rather than on the lines. On `Fare`
            the mean is at 6% of the axis and the median at 3%, so two labels
            drawn where their lines are would land on top of each other — and
            the pair being close together is exactly what the reader is meant
            to see.

            **Which line, not what it reads.** The figures were here until the
            product owner removed them; both are two rows away in Central
            tendency, and a legend's job is to say which stroke is which. Each
            key still only appears when its line is actually drawn. */}
        <figcaption className="chart-legend">
          {it.mean !== null ? (
            <span className="key mean caps">mean</span>
          ) : null}
          {it.median !== null ? (
            <span className="key median caps">median</span>
          ) : null}
        </figcaption>
        <Histogram
          bins={bins}
          markers={
            spread
              ? [
                  { kind: "mean", value: it.mean },
                  { kind: "median", value: it.median },
                ]
              : []
          }
        />
      </figure>

      {/* Under the histogram and on the same axis, because it answers the
          question the bars above it cannot: not *how many fall near here* but
          **which values this column actually contains**. */}
      {spread && it.rug.length > 1 ? (
        <figure className="figure">
          <Rug points={it.rug} at={at} />
        </figure>
      ) : null}

      {boxable ? (
        <figure className="figure">
          <BoxPlot
            at={at}
            lo={lo}
            hi={hi}
            minimum={it.minimum as number}
            maximum={it.maximum as number}
            whiskerLow={it.whisker_low as number}
            whiskerHigh={it.whisker_high as number}
            q1={q1 as number}
            q3={q3 as number}
            median={it.median as number}
            fenceLow={it.outlier_low}
            fenceHigh={it.outlier_high}
            outliers={it.outlier_count}
            outlierShare={outlierShare}
          />
        </figure>
      ) : null}

      {spread && it.ecdf.length > 1 ? (
        /* No caption. It read *"Share of values at or below x · 50% ≤ 98,400 ·
           95% ≤ 428,065"*, and both of those figures are rows in the
           Percentiles band a few pixels above — so unlike the outlier fence it
           replaced nothing, it repeated something. What took its place answers
           the same question for **every** x rather than for two of them, which
           is the one thing an ECDF can do and a histogram cannot. */
        <figure className="figure">
          <Ecdf points={it.ecdf} at={at} lo={lo} hi={hi} />
        </figure>
      ) : null}

      <div className="chart-axis mono">
        <span>{num(lo)}</span>
        <span>{num(hi)}</span>
      </div>
    </div>
  );
}

/**
 * One tick per distinct value, at its own position (D-074).
 *
 * **The only unbinned figure on this panel, and that is its whole reason.** A
 * histogram answers *how many fall near here*, and twenty bars over `age` look
 * equally smooth whether the column holds every age or only the ones ending in
 * 0 and 5. A rug answers *which values are in here*, so a lattice shows up as
 * evenly spaced gaps: rounding, a unit that changed halfway down the file, a
 * placeholder coded as 999, all of them are in the answer.
 *
 * Opacity carries the count and is deliberately weak at it: `sqrt`, floored so
 * that a value occurring once is still visible, because **presence is the
 * reading here** and frequency is the histogram's job two figures up.
 *
 * ⚠️ Past `RUG_POINTS` distinct values the server thins by rank rather than
 * cutting the tail, and **nothing on screen says so any more**. The figure
 * pins both ends, so the axis stays true; what a reader cannot tell is whether
 * a gap between two ticks is a gap in the column or a value the stride
 * skipped.
 */
function Rug({
  points,
  at,
}: {
  points: { value: number; count: number }[];
  at: (value: number) => number;
}) {
  const [over, setOver] = useState<number | null>(null);
  const top = Math.max(1, ...points.map((point) => point.count));
  const lit = over === null ? undefined : points[over];

  /** Snap to the nearest tick: the rug has values, not a domain. */
  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      100,
      Math.max(0, ((event.clientX - rect.left) / rect.width) * 100),
    );
    let best = 0;
    for (let index = 1; index < points.length; index += 1) {
      const here = points[index];
      const there = points[best];
      if (here === undefined || there === undefined) continue;
      if (
        Math.abs(at(here.value) - fraction) <
        Math.abs(at(there.value) - fraction)
      )
        best = index;
    }
    setOver(best);
  }

  return (
    <>
      <div
        className="rug"
        role="img"
        aria-label={`${points.length.toLocaleString("en")} distinct values, each at its own position on the axis.`}
        onPointerMove={probe}
        onPointerLeave={() => setOver(null)}
      >
        {points.map((point, index) => (
          <span
            key={point.value}
            className="tick"
            data-lit={index === over || undefined}
            style={
              {
                left: `${at(point.value)}%`,
                "--weight": Math.max(0.28, Math.sqrt(point.count / top)),
              } as React.CSSProperties
            }
          />
        ))}
      </div>
      {/* Hover only. It said `1 in 3 distinct values` when a column carried
          more distinct values than the panel can separate, and that line is
          gone at the owner's request. `rug_stride` is still computed and still
          on the wire; what it no longer has is a reader, so a rug drawn from
          one value in three now looks exactly like a rug drawn from all of
          them. Both ends are still pinned, so at least the axis is honest. */}
      <p className="chart-note" data-lit={lit !== undefined}>
        {lit !== undefined ? `${num(lit.value)} · ${lit.count.toLocaleString("en")}` : "\u00a0"}
      </p>
    </>
  );
}

/**
 * A box, two whiskers, and a hairline for the part outside the fence.
 *
 * The whiskers stop at the most extreme value still **inside** the fence,
 * which is the standard and which is why the server sends two extra numbers
 * for it. Drawing them to the fence would be cheaper and would claim data
 * reaches a place no value does — on `Fare` the low fence is −26.72 and the
 * column holds no negative value at all.
 *
 * The outliers are **not** drawn as points. Only ten are on the wire, and ten
 * dots where there are a hundred and sixteen values is a picture of the sample
 * rather than of the column. The hairline says how far they reach; the caption
 * says how many there are.
 */
function BoxPlot({
  at,
  lo,
  hi,
  minimum,
  maximum,
  whiskerLow,
  whiskerHigh,
  q1,
  q3,
  median,
  fenceLow,
  fenceHigh,
  outliers,
  outlierShare,
}: {
  at: (value: number) => number;
  lo: number;
  hi: number;
  minimum: number;
  maximum: number;
  whiskerLow: number;
  whiskerHigh: number;
  q1: number;
  q3: number;
  median: number;
  fenceLow: number | null;
  fenceHigh: number | null;
  outliers: number;
  outlierShare: number;
}) {
  const [part, setPart] = useState<Part | null>(null);
  const span = (from: number, to: number) => ({
    left: `${at(from)}%`,
    width: `${Math.max(0, at(to) - at(from))}%`,
  });

  /** Which landmark the pointer is over, by value rather than by hit area. */
  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      1,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    const value = lo + fraction * (hi - lo);
    // The median first, and measured in **percent of the axis** rather than in
    // the column's units: a line two pixels wide cannot be hit by aiming at a
    // value, and on a skewed column the median sits inside a box only a few
    // percent across.
    if (Math.abs(fraction * 100 - at(median)) < 1.2) setPart("median");
    else if (value < whiskerLow) setPart("tail-low");
    else if (value > whiskerHigh) setPart("tail-high");
    else if (value < q1) setPart("whisker-low");
    else if (value <= q3) setPart("box");
    else setPart("whisker-high");
  }

  return (
    <>
      <div
        className="boxplot"
        role="img"
        aria-label={
          `Box plot. Median ${num(median)}, quartiles ${num(q1)} to ${num(q3)},` +
          ` whiskers ${num(whiskerLow)} to ${num(whiskerHigh)},` +
          ` full range ${num(minimum)} to ${num(maximum)}.`
        }
        onPointerMove={probe}
        onPointerLeave={() => setPart(null)}
      >
        {whiskerLow > minimum ? (
          <span
            className="tail"
            data-lit={part === "tail-low"}
            style={span(minimum, whiskerLow)}
          />
        ) : null}
        {maximum > whiskerHigh ? (
          <span
            className="tail"
            data-lit={part === "tail-high"}
            style={span(whiskerHigh, maximum)}
          />
        ) : null}
        <span
          className="whisker"
          data-lit={part === "whisker-low" || part === "whisker-high"}
          style={span(whiskerLow, whiskerHigh)}
        />
        <span className="cap" style={{ left: `${at(whiskerLow)}%` }} />
        <span className="cap" style={{ left: `${at(whiskerHigh)}%` }} />
        <span className="box" data-lit={part === "box"} style={span(q1, q3)} />
        <span
          className="mid"
          data-lit={part === "median"}
          style={{ left: `${at(median)}%` }}
        />
      </div>

      {/* **The caption is the boxplot's readout.** A floating label would have
          to land somewhere in 44px of height, which means on top of the
          histogram above or the ECDF below. The line under the figure is
          already there, already the right size, and already where the eye goes
          after the shape — so hovering swaps what it says and leaves it where
          it is.

          Its resting state keeps the count *with its denominator*, because 116
          outliers means one thing in 891 rows and another in 891,000.

          **⚠️ The fence is in the tooltip**, at the product owner's request,
          and that is weaker than §11.7.6 asks for: *the rule is stated, not
          applied silently*. It matters most where the count is least
          trustworthy. On `amount` the rule flags 7.0% where it was designed to
          flag about 0.7%, because the column is skewed 4.73 — those 84 rows are
          a lognormal meeting a rule built for symmetric data, not 84 bad
          values. And its lower fence sits at −122,300 on a column with no
          negative value at all. Both tells are in the fence; neither is in the
          count. */}
      <figcaption
        className="chart-note"
        data-lit={part !== null}
        title={`IQR fence, k = 1.5 · [${num(fenceLow)}, ${num(fenceHigh)}]`}
      >
        {part === null
          ? outliers === 0
            ? "no outliers"
            : `${outliers.toLocaleString("en")} outlier${outliers === 1 ? "" : "s"} (${share(
                outlierShare,
              )})`
          : LANDMARK[part]({
              minimum,
              maximum,
              whiskerLow,
              whiskerHigh,
              q1,
              q3,
              median,
            })}
      </figcaption>
    </>
  );
}

type Part =
  "tail-low" | "tail-high" | "whisker-low" | "whisker-high" | "box" | "median";

/**
 * What each landmark says when the pointer is on it.
 *
 * Ranges rather than counts on the tails: the bundle carries **one** outlier
 * total, not one per side, so *"84 outliers below 7,500"* would be a number
 * invented to fill a sentence on a column whose outliers are all at the top.
 */
const LANDMARK: Record<Part, (it: Landmarks) => string> = {
  median: (it) => `median · ${num(it.median)}`,
  box: (it) => `middle half · ${num(it.q1)} – ${num(it.q3)}`,
  "whisker-low": (it) =>
    `lower whisker · ${num(it.whiskerLow)} – ${num(it.q1)}`,
  "whisker-high": (it) =>
    `upper whisker · ${num(it.q3)} – ${num(it.whiskerHigh)}`,
  "tail-low": (it) =>
    `outside the fence · ${num(it.minimum)} – ${num(it.whiskerLow)}`,
  "tail-high": (it) =>
    `outside the fence · ${num(it.whiskerHigh)} – ${num(it.maximum)}`,
};

interface Landmarks {
  minimum: number;
  maximum: number;
  whiskerLow: number;
  whiskerHigh: number;
  q1: number;
  q3: number;
  median: number;
}

/**
 * The quantile function, plotted the way an ECDF is read: value across,
 * proportion up.
 *
 * `preserveAspectRatio="none"` stretches the viewBox to whatever width the
 * stack has, which is what keeps this curve on the same axis as the two
 * figures above it. `vectorEffect="non-scaling-stroke"` is what stops that
 * stretch from turning a 1px line into a wedge.
 *
 * The percentage ticks sit outside the `<svg>` for the same reason: text
 * inside a stretched viewBox is stretched with it.
 */
function Ecdf({
  points,
  at,
  lo,
  hi,
}: {
  points: { p: number; value: number }[];
  at: (value: number) => number;
  lo: number;
  hi: number;
}) {
  const [cursor, setCursor] = useState<{
    at: number;
    value: number;
    p: number;
  } | null>(null);
  const head = points.at(0);
  const tail = points.at(-1);
  if (head === undefined || tail === undefined) return null;

  /** Follow the pointer's x, and read the curve's height there. */
  function track(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    // jsdom reports every rect as zero, and so does a page mid-layout. A
    // readout computed from a zero width would be a number about nothing.
    if (rect.width === 0) return;
    const fraction = Math.min(
      1,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    const value = lo + fraction * (hi - lo);
    setCursor({ at: fraction * 100, value, p: shareAtOrBelow(points, value) });
  }
  const path = points
    .map(
      (point) =>
        `${(at(point.value) * 10).toFixed(2)},${(100 - point.p * 100).toFixed(2)}`,
    )
    .join(" ");
  const first = (at(head.value) * 10).toFixed(2);
  const last = (at(tail.value) * 10).toFixed(2);
  return (
    // `role="img"` rather than `aria-hidden`: the name below replaces the
    // contents, so the three bare tick percentages are not read aloud out of
    // the picture they belong to, and the figure still says what it shows. The
    // hover readout is pointer-only by nature; the quartiles it would reveal
    // are rows in the Percentiles band either way.
    <div
      className="curve-wrap"
      role="img"
      aria-label={
        `Cumulative distribution. 25% of values at or below ${num(valueAt(points, 0.25))},` +
        ` 50% at or below ${num(valueAt(points, 0.5))},` +
        ` 75% at or below ${num(valueAt(points, 0.75))}.`
      }
      onPointerMove={track}
      onPointerLeave={() => setCursor(null)}
    >
      <svg className="curve" viewBox="0 0 1000 100" preserveAspectRatio="none">
        <polygon
          className="curve-area"
          points={`${first},100 ${path} ${last},100`}
        />
        {CURVE_GRID.map((line) => (
          <line
            key={line}
            className="curve-grid"
            x1="0"
            x2="1000"
            y1={100 - line}
            y2={100 - line}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <polyline
          className="curve-line"
          points={path}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {CURVE_GRID.map((line) => (
        <span
          key={line}
          className="curve-tick mono"
          style={{ bottom: `${line}%` }}
        >
          {line}%
        </span>
      ))}
      {cursor === null ? null : (
        <>
          <span className="curve-cursor" style={{ left: `${cursor.at}%` }} />
          <span
            className="curve-dot"
            style={{ left: `${cursor.at}%`, bottom: `${cursor.p * 100}%` }}
          />
          <Readout at={cursor.at} bottom={cursor.p * 100}>
            {share(cursor.p)} ≤ {num(cursor.value)}
          </Readout>
        </>
      )}
    </div>
  );
}

/**
 * F(x) — the share of values at or below `x`, off the sampled curve.
 *
 * **Ties resolve upward, and that is the definition rather than a convenience.**
 * F(x) is *"how much of the column is ≤ x"*, so where a run of the grid holds
 * one repeated value — which is how a step in the distribution appears in the
 * quantile function — the answer at that value is the **top** of the step, not
 * somewhere inside it. Hence the scan for the last index at or below `x`
 * instead of a binary search for the first.
 */
export function shareAtOrBelow(
  points: { p: number; value: number }[],
  x: number,
): number {
  let index = -1;
  for (let k = 0; k < points.length; k += 1) {
    const point = points[k];
    if (point !== undefined && point.value <= x) index = k;
  }
  if (index < 0) return 0;
  const here = points[index];
  const next = points[index + 1];
  if (here === undefined) return 0;
  if (next === undefined) return 1;
  if (next.value === here.value) return next.p;
  return (
    here.p + ((x - here.value) / (next.value - here.value)) * (next.p - here.p)
  );
}

/** The value at a given proportion — the curve read the other way. */
function valueAt(
  points: { p: number; value: number }[],
  p: number,
): number | null {
  const hit = points.find((point) => point.p >= p - 1e-9);
  return hit === undefined ? null : hit.value;
}

/** Where the ECDF rules itself, in percent. Quartiles, so the box above lines up. */
const CURVE_GRID = [25, 50, 75];

/**
 * One band of the descriptive table: its name in the left rail, its figures in
 * the shared four-column field beside it.
 *
 * **This was seven small tables in a multi-column flow until D-054**, and the
 * product owner was right that it read as a mess. Every group set its own
 * height, so no row in one column lined up with any row in another; the tallest
 * group (`Percentiles`, seven rows) decided where the flow broke; and
 * `Uniqueness` ended up alone in the fifth column with a void beneath it. Five
 * lists side by side, not a table.
 *
 * The rail fixes it by giving every band the same two-part shape — name, then
 * figures — and the field fixes it by being **exactly four columns for every
 * band**, so `median` sits under `variance` sits under `Q1` sits under `p5`.
 * `display: contents` is what lets the rail share one `max-content` track
 * across all seven bands without each band knowing about the others.
 */
function StatBand({
  title,
  rows,
  alarm,
}: {
  title: string;
  /** The one row, if any, that should be read as red. */
  alarm?: string;
  /** `[label, value]`, or `[label, value, hint]` when the figure needs its
   *  convention stated — a kurtosis of 0 means two different things depending
   *  on which definition the reader learnt. */
  rows: readonly (
    readonly [string, string] | readonly [string, string, string]
  )[];
}) {
  return (
    <div className="stat-band">
      <h3 className="stat-rail caps">{title}</h3>
      <div className="stat-cells">
        {rows.map(([label, value, hint]) => (
          <div
            className="cell"
            key={label}
            title={hint}
            data-alarm={label === alarm || undefined}
          >
            <span>{label}</span>
            <strong className="mono">{value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * §11.7.3 for a categorical column: the table first, then the one figure that
 * says what the table cannot.
 *
 * Built on the numerical panel's shape (D-051) and on the same rule — **say
 * each fact once**. The product owner asked for a frequency table *and* a
 * sorted bar chart, and those are the same ten rows: two blocks would repeat
 * every category name and put one comparison on screen twice. The bar is a
 * column inside the table instead.
 *
 * Two of the five proposals were argued down rather than built, and both
 * arguments are recorded in D-060. A **percentage bar chart** draws bars whose
 * lengths are identical to the count bars — `count / max` and `pct / maxPct`
 * are the same fraction — so the percentage became a column. A **treemap**
 * compares by area, which is the hardest encoding to read, and earns that cost
 * back only on hierarchical data; these columns are flat strings.
 */
function Categorical({
  it,
  present,
}: {
  it: NonNullable<ColumnDetail["categorical"]>;
  present: number;
}) {
  const [over, setOver] = useState<number | null>(null);
  const widest = Math.max(1, ...it.top.map((item) => item.count));
  const rows = it.top.map((item, index) => ({
    rank: index + 1,
    value: item.value,
    count: item.count,
    width: (item.count / widest) * 100,
    share: present === 0 ? 0 : item.count / present,
    // A **sequential** ramp, not a categorical palette. Rank is ordered, and a
    // scale that runs one way says so; ten unrelated hues would claim the
    // categories have no order when the whole table is sorted by one. It also
    // stays inside the type's own colour, which is what keeps a categorical
    // panel looking like a categorical panel.
    step: ramp(index, it.top.length),
  }));
  const remainder =
    it.others_distinct > 0 && present > 0 ? it.others_count / present : 0;

  let cursor = 0;
  const wedges: Slice[] = rows.map((row) => {
    const from = cursor;
    cursor += row.share;
    return {
      rank: row.rank,
      from,
      to: cursor,
      tone: row.step,
      label: row.value,
      detail: `${row.count.toLocaleString("en")} · ${share(row.share)}`,
    };
  });
  if (remainder > 0) {
    wedges.push({
      rank: 0,
      from: cursor,
      to: 1,
      tone: "rest",
      label: `${it.others_distinct.toLocaleString("en")} more categor${
        it.others_distinct === 1 ? "y" : "ies"
      }`,
      detail: share(remainder),
      pin: false,
    });
  }

  return (
    <>
      {/* Table and donut side by side (D-063). The bar column had the whole
          width of the panel and almost nothing to do with it — on `rating` the
          five bars differ by 2.3 percentage points across 1,000px. Half of
          that width now holds the one figure that shows the **whole**. */}
      <div className="composition">
        <table className="freq" onPointerLeave={() => setOver(null)}>
          <thead>
            <tr>
              <th className="rank">#</th>
              <th className="name">category</th>
              <th className="bar" aria-label="share of values" />
              <th>count</th>
              <th>%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.value}
                data-lit={over === row.rank}
                onPointerEnter={() => setOver(row.rank)}
              >
                <td className="rank">{row.rank}</td>
                <td className="name" title={row.value}>
                  {row.value}
                </td>
                <td className="bar">
                  <span className="track">
                    <span
                      className="fill"
                      style={
                        {
                          width: `${row.width}%`,
                          "--step": row.step,
                        } as React.CSSProperties
                      }
                    />
                  </span>
                </td>
                <td className="count mono">{row.count.toLocaleString("en")}</td>
                <td className="share mono">{share(row.share)}</td>
              </tr>
            ))}
            {/* **Not optional.** A frequency table that stops at ten without
              saying so contradicts its own arithmetic: a reader adds the
              percentage column and gets 62%. This row is what makes it sum to
              a hundred. */}
            {it.others_distinct > 0 ? (
              <tr
                className="rest"
                data-lit={over === 0}
                onPointerEnter={() => setOver(0)}
              >
                {/* No rank, and nothing standing in for one. The remainder is not
                  a category, so it does not hold a place in an ordering of
                  them. */}
                <td className="rank" />
                <td className="name">
                  {it.others_distinct.toLocaleString("en")} more categor
                  {it.others_distinct === 1 ? "y" : "ies"}
                </td>
                <td className="bar" />
                <td className="count mono">
                  {it.others_count.toLocaleString("en")}
                </td>
                <td className="share mono">{share(remainder)}</td>
              </tr>
            ) : null}
          </tbody>
        </table>

        {/* **Drawn for one category too.** It was suppressed at first on the
            argument that a full ring says only that the category is the only
            one — which the table said in a row. The argument was wrong in a way
            the product owner found by opening `country` and asking *why does
            this look different from the others*: **a panel whose anatomy
            changes with the data makes the reader notice what is missing**, and
            the answer here (*the column is constant*) is exactly the finding
            that should have been visible instead of absent.

            §11.8.3's rule about empty columns does not reach this. That rule is
            about a figure that would be **blank** — a histogram of a column
            with nothing in it is one empty frame that looks like a finding and
            is not one. A full ring is not blank; it is a complete and true
            picture of a column that holds one value. */}
        {rows.length > 0 ? (
          <Donut slices={wedges} total={present} over={over} onOver={setOver} />
        ) : null}
      </div>

      {/* **`rare_categories` has no surface any more** (D-061). It said how
          many categories appear fewer than five times, which is the one thing
          about a long tail that neither the table nor the curve can state — the
          table stops at ten and the curve draws a shape rather than a count.
          Still computed, still on the wire, nothing reads it.

          The count of categories went with it and is at least recoverable: when
          every category fits, the table **is** the list; when it does not, the
          `others` row says how many more there are. */}

      {/* **Always drawn now (D-062)**, and the reason it once was not has been
          removed rather than worked around. It used to appear only when the
          table could not show every category, because otherwise the curve would
          be the table's own `cum %` column drawn as a line — one fact stated
          twice. That column is gone, so the curve is the only place cumulative
          behaviour lives, and it belongs on every categorical column.

          **A column with one category draws it too**, at the product owner's
          request and in the one shape that is true for a rank axis with a
          single rank — see `Concentration`. */}
      {it.concentration.length > 0 ? (
        <Concentration points={it.concentration} />
      ) : null}
    </>
  );
}

/**
 * Where a rank sits on the type's own colour ramp, from 1 (strongest) down.
 *
 * Stops at 0.32 rather than 0: a slice mixed all the way into the panel is a
 * hole in the ring, and the tenth category is small, not absent.
 */
function ramp(index: number, total: number): number {
  return total <= 1 ? 1 : 1 - 0.68 * (index / (total - 1));
}

/**
 * Composition as a ring — the one figure on this panel that shows the **whole**.
 *
 * ## Why this and not the treemap that was argued down
 *
 * The treemap was proposed for *"relative magnitude antar kategori"*, which
 * bars on a shared baseline do strictly better, and for hierarchy, which these
 * columns do not have. Neither reason survived. This is here for a different
 * one: **part-to-whole**, and specifically the part the bars refuse to draw.
 *
 * The frequency table deliberately gives the remainder **no bar** — one bar for
 * 110 categories at once would be compared against single categories on a
 * shared baseline and win for a reason that means nothing. In a ring there is
 * no baseline to compete on: every slice is a share of one circle, and the
 * remainder is legitimately one region of it. So this is the only place the
 * tail is drawn to scale, and the only place the question *"what is this
 * column made of"* is answered as a single picture.
 *
 * What it is **not** asked to do is compare similar slices — that is what the
 * bars beside it and the `%` column are for. A figure that only has to carry
 * one reading can be judged on whether it carries that one.
 *
 * ## The remainder is grey on purpose
 *
 * It is not a category, so it is not on the categories' ramp. Same reason its
 * table row is set in `--ink-faint` and carries no bar.
 */
function Donut({
  slices,
  total,
  over,
  onOver,
}: {
  slices: Slice[];
  /** What the hole reads when nothing is hovered: the whole the slices divide. */
  total: number;
  over: number | null;
  onOver: (rank: number | null) => void;
}) {
  const lit = slices.find((slice) => slice.rank === over);

  return (
    <figure className="donut" onPointerLeave={() => onOver(null)}>
      <svg
        viewBox="0 0 240 240"
        role="img"
        aria-label="Composition of this column by category"
      >
        {slices.map((slice) => {
          // A wedge covering the whole turn has coincident endpoints, and an
          // arc between two identical points draws nothing. A column with one
          // category is a ring, so it is drawn as one: a stroked circle at the
          // mean radius, as thick as the band.
          const whole = slice.to - slice.from > 0.9999;
          // `key` is **not** in here. React reads it before props are applied
          // and cannot see one that arrives through a spread — it warns, and
          // then falls back to position for reconciliation. Every other
          // attribute is shared between the two shapes; the key is passed on
          // each element directly.
          const shape = {
            className: whole ? "slice whole" : "slice",
            "data-tone":
              typeof slice.tone === "string" ? slice.tone : undefined,
            "data-lit": slice.rank === over,
            style:
              typeof slice.tone === "number"
                ? ({ "--step": slice.tone } as React.CSSProperties)
                : undefined,
            onPointerEnter: () => onOver(slice.rank),
          };
          return whole ? (
            <circle key={slice.rank} {...shape} cx="120" cy="120" r="88" />
          ) : (
            <path key={slice.rank} {...shape} d={wedge(slice.from, slice.to)} />
          );
        })}
        {/* The rank, on the slices with room for it. This is the join the
            product owner asked for: the number in the ring is the number in the
            table's `#` column, so a slice can be found without a legend and
            without a colour anybody has to remember. 4% is where a wedge stops
            being wide enough to hold two digits at this radius. */}
        {slices.map((slice) =>
          slice.to - slice.from < 0.04 ||
          slice.pin === false ||
          slice.rank === 0 ? null : (
            <text
              key={slice.rank}
              className="pin"
              x={120 + 87 * Math.cos(mid(slice.from, slice.to))}
              y={120 + 87 * Math.sin(mid(slice.from, slice.to))}
            >
              {slice.rank}
            </text>
          ),
        )}
      </svg>

      {/* The hole is the readout. A label floating beside a wedge has to dodge
          the wedge; a label in the middle of a ring never does, and the ring
          was going to have a hole anyway. */}
      <figcaption className="hub">
        {lit === undefined ? (
          /* The size of the whole the slices are shares of — and since D-061
             took the Completeness block off this panel, the only place a
             categorical column says how many values it holds at all. `11
             slices` stood here first and was a fact about the chart rather
             than about the column. */
          <>
            <strong className="mono">{total.toLocaleString("en")}</strong>
            <span>values</span>
          </>
        ) : (
          <>
            {/* Truncated, not marqueed. `Ellipsis` scrolls its text when it
                overflows, which is right for a column name in a header and
                wrong inside a 104px hole — it read as `l0 more categories`
                mid-scroll, clipped at both ends. The full name is one row away
                in the table, which is lit at the same moment. */}
            <span title={lit.label}>{lit.label}</span>
            <strong className="mono">{lit.detail}</strong>
          </>
        )}
      </figcaption>
    </figure>
  );
}

/**
 * One wedge, and how it is painted.
 *
 * `tone` is a number when the slice sits on the type's own ramp — a rank in a
 * frequency table — and a name when it does not. `"rest"` is the remainder a
 * top-N table leaves behind, and the class a boolean's `false` takes: neither
 * is *wrong*, both are what is left once the thing being counted is counted.
 * `"other"` is for a value that belongs to no class at all, which on a boolean
 * column means a word that is neither true nor false.
 */
interface Slice {
  rank: number;
  from: number;
  to: number;
  tone: number | "rest" | "other";
  label: string;
  detail: string;
  /** `false` keeps the rank number off a wedge that has no rank to show. */
  pin?: boolean;
}

/** Mid-angle of a slice, in radians, measured from twelve o'clock. */
function mid(from: number, to: number): number {
  return ((from + to) / 2) * 2 * Math.PI - Math.PI / 2;
}

/**
 * One wedge of the ring, as an SVG path.
 *
 * Clockwise from twelve o'clock, which is where a reader starts looking and
 * therefore where rank 1 belongs.
 */
function wedge(from: number, to: number): string {
  const OUTER = 110;
  const INNER = 66;
  const a0 = from * 2 * Math.PI - Math.PI / 2;
  const a1 = to * 2 * Math.PI - Math.PI / 2;
  const wide = to - from > 0.5 ? 1 : 0;
  const at = (radius: number, angle: number) =>
    `${(120 + radius * Math.cos(angle)).toFixed(2)} ${(120 + radius * Math.sin(angle)).toFixed(2)}`;
  return (
    `M${at(OUTER, a0)} A${OUTER} ${OUTER} 0 ${wide} 1 ${at(OUTER, a1)}` +
    ` L${at(INNER, a1)} A${INNER} ${INNER} 0 ${wide} 0 ${at(INNER, a0)} Z`
  );
}

/**
 * **When a figure is drawn for a degenerate column, and when it is not.**
 *
 * The product owner has now asked twice why a panel looked different, which is
 * the cost of deciding this case by case. The rule, stated once:
 *
 * > A figure is drawn when its **axis has extent**, and suppressed when the
 * > axis collapses to a point.
 *
 * That is not the same as *the data is boring*, and it is not §11.8.3's rule
 * about empty columns either. It is about whether there is anything to draw
 * **along**:
 *
 * - **Histogram** of a constant column — one bar, full width. Drawn: the frame
 *   is filled with a true picture.
 * - **Donut** of a one-category column — a full ring. Drawn, for the same
 *   reason, and suppressing it was the mistake D-063's follow-up corrected.
 * - **Boxplot** and **ECDF** of a constant column — `min === max`, so the x
 *   axis is a point. Suppressed.
 * - **Concentration curve** of a one-category column — one rank, so the x axis
 *   is a point. Suppressed.
 *
 * The last one was suppressed on that rule, and the product owner asked for it
 * back — so the rule gained the clause it was missing. **Suppression is what a
 * collapsed axis deserves only when there is no true picture to put there.**
 * When there is one, draw it.
 *
 * For a rank axis with a single rank there is: the share covered is 100% at
 * every point of that axis, which is a **flat line at the top**. What could
 * *not* be drawn is the naive rendering — the sole point lands at `1000,0`, the
 * area polygon becomes `0,100 1000,0 1000,100`, and that is **a filled
 * triangle**: a picture of concentration climbing across a range of ranks that
 * does not exist. Not empty. False. Hence the explicit two-point case below.
 *
 * ⚠️ The boxplot and the ECDF are still suppressed on a constant numerical
 * column, and whether the same clause applies to them is open — it belongs to
 * the next review of that panel, not to this one.
 *
 * ---
 *
 * Cumulative share against category rank — the Pareto reading, over **every**
 * category rather than the ten in the table.
 *
 * Bars plus a cumulative line over the top ten was the shape asked for, and it
 * would draw the head of a two-hundred-category column and say nothing about
 * the tail *while looking exactly like a chart that had*. This is the line
 * component computed over all of them, which is the part that carries the
 * reading: **how many categories it takes to cover most of the column.**
 *
 * The x axis is rank and is linear, so a long tail looks long. That is the
 * finding, not a distortion of it.
 */
function Concentration({
  points,
  unit = "categories",
}: {
  points: { rank: number; share: number }[];
  /** What rank 1 is one of. Only the accessible name uses it now: the caption
   *  that printed it is gone, and *categories* is wrong on the panel counting
   *  words, so a sighted reader takes the unit from the figure it sits under
   *  and a screen reader still has it said. */
  unit?: string;
}) {
  const [over, setOver] = useState<number | null>(null);
  const last = points.at(-1);
  if (last === undefined) return null;
  const ranks = last.rank;

  const at = (rank: number) =>
    ranks <= 1 ? 0 : ((rank - 1) / (ranks - 1)) * 100;
  const only = points.length === 1 ? points[0] : undefined;
  // One rank spans the whole axis, so its share holds across the whole width.
  // Mapping the single point would emit one coordinate, which `polyline` draws
  // as nothing and `polygon` closes into a triangle that climbs across ranks
  // the column does not have.
  const path =
    only === undefined
      ? points
          .map(
            (point) =>
              `${(at(point.rank) * 10).toFixed(2)},${(100 - point.share * 100).toFixed(2)}`,
          )
          .join(" ")
      : `0,${(100 - only.share * 100).toFixed(2)} 1000,${(100 - only.share * 100).toFixed(2)}`;
  const lit = over === null ? undefined : points[over];

  /** Snap to the nearest sampled rank — the curve has points, not a domain. */
  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      1,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    const wanted = 1 + fraction * (ranks - 1);
    let best = 0;
    for (let index = 1; index < points.length; index += 1) {
      const here = points[index];
      const there = points[best];
      if (here === undefined || there === undefined) continue;
      if (Math.abs(here.rank - wanted) < Math.abs(there.rank - wanted))
        best = index;
    }
    setOver(best);
  }

  return (
    <figure className="figure">
      <div
        className="curve-wrap"
        role="img"
        aria-label={`Cumulative share against rank, across ${ranks.toLocaleString("en")} ${unit}.`}
        onPointerMove={probe}
        onPointerLeave={() => setOver(null)}
      >
        <svg
          className="curve"
          viewBox="0 0 1000 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <polygon className="curve-area" points={`0,100 ${path} 1000,100`} />
          {CURVE_GRID.map((line) => (
            <line
              key={line}
              className="curve-grid"
              x1="0"
              x2="1000"
              y1={100 - line}
              y2={100 - line}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          <polyline
            className="curve-line"
            points={path}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        {CURVE_GRID.map((line) => (
          <span
            key={line}
            className="curve-tick mono"
            style={{ bottom: `${line}%` }}
          >
            {line}%
          </span>
        ))}
        {lit === undefined ? null : (
          <>
            <span
              className="curve-cursor"
              style={{ left: `${at(lit.rank)}%` }}
            />
            <Readout at={at(lit.rank)} bottom={lit.share * 100}>
              top {lit.rank.toLocaleString("en")} · {share(lit.share)}
            </Readout>
          </>
        )}
      </div>
      {/* An axis, the same way the numerical figures carry one: a curve whose
          x is a rank says nothing until the reader knows how many ranks there
          are. */}
      <div className="chart-axis mono">
        <span>1</span>
        <span>{ranks.toLocaleString("en")}</span>
      </div>
    </figure>
  );
}

/**
 * §11.7.3 for a text column, in four parts.
 *
 * A `text` column in a tabular dataset is nearly always one of three things:
 * a mistyped code, a short label, or prose. The composition block was what
 * said which, and it led the panel for exactly one revision before the product
 * owner removed it (D-072) — so the figures below now describe a shape without
 * naming the thing that has it.
 *
 * ⚠️ **The vocabulary block crosses a boundary §11.7.3 drew** — *word cloud,
 * sentiment, NLP are outside tabular scope* — at the product owner's decision,
 * and D-071 records the crossing rather than slipping it in. What is drawn is
 * the narrowest honest form: tokens split on non-alphanumerics, lowercased,
 * and **nothing removed**. No stopword list, because a stopword list is a
 * language and this product has no notion of one.
 *
 * The consequence used to be visible rather than hidden, which was the point
 * of putting composition above it: on `comment` the commonest term is `a` at
 * 509, and on `product_name` it is `portable` at 212. Same code, different kind
 * of column — and since D-072 nothing on the panel says which kind it is.
 */
function Text({
  it,
  present,
}: {
  it: NonNullable<ColumnDetail["text"]>;
  present: number;
}) {
  const [over, setOver] = useState<number | null>(null);
  const widest = Math.max(1, ...it.top.map((item) => item.count));
  const rows = it.top.map((item, index) => ({
    rank: index + 1,
    value: item.value,
    count: item.count,
    width: (item.count / widest) * 100,
    share: present === 0 ? 0 : item.count / present,
    step: ramp(index, it.top.length),
  }));
  const remainder =
    it.others_count > 0 && present > 0 ? it.others_count / present : 0;
  const diversity =
    it.tokens_total === 0 ? 0 : it.tokens_distinct / it.tokens_total;

  return (
    <>
      <div className="stat-table">
        {/* **`Looks like` is gone (D-072)**, at the product owner's request, and
            with it every share it drew: numeric, date-like, has-a-digit,
            padded, UPPERCASE, punctuation, URL and non-ASCII.

            All eight are still computed and still on the wire. What they no
            longer have is a reader, and three things go quiet with them:

            **A mistyped column.** `postal_code` reads 94.8% numeric, which is
            how a column of numbers held as text announced itself.

            **A null marker wearing a value's clothes.** The 5.2% of
            `postal_code` that is *not* numeric is 62 rows holding the word
            `unknown`, in a column this product reports as `0% null`. Nothing
            else on any panel finds that.

            **`padded`.** `Jakarta ` and `Jakarta` are two categories in every
            aggregation downstream, which §11.7.4 called the classic silent bug
            on real data.

            And the figures below lose their precondition: `mean 42.9
            characters` is a fact about sentences or a fact about digits, and
            the panel no longer says which. */}
        <StatBand
          title="Length"
          rows={[
            ["min", num(it.length_min)],
            ["median", num(it.length_median)],
            ["mean", brief(it.length_mean)],
            ["max", num(it.length_max)],
          ]}
        />
        <StatBand
          title="Words"
          rows={[
            ["min", num(it.words_min)],
            ["median", num(it.words_median)],
            ["mean", brief(it.words_mean)],
            // The one figure the scatter plot was proposed for. 200 characters
            // in one word is a URL or a blob, and it is a number rather than a
            // cloud of points somebody has to regress by eye.
            [
              "chars/word",
              it.words_mean === null ||
              it.words_mean === 0 ||
              it.length_mean === null
                ? "n/a"
                : brief(it.length_mean / it.words_mean),
            ],
          ]}
        />
      </div>

      <div className="pair">
        <Measure title="character length" bins={it.length_bins} unit="chars" />
        <Measure title="word count" bins={it.word_bins} unit="words" />
      </div>

      <div className="composition">
        <table className="freq" onPointerLeave={() => setOver(null)}>
          <thead>
            <tr>
              <th className="rank">#</th>
              <th className="name">value</th>
              <th className="bar" aria-label="share of rows" />
              <th>count</th>
              <th>%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.value}
                data-lit={over === row.rank}
                onPointerEnter={() => setOver(row.rank)}
              >
                <td className="rank">{row.rank}</td>
                <td className="name" title={row.value}>
                  {row.value}
                </td>
                <td className="bar">
                  <span className="track">
                    <span
                      className="fill"
                      style={
                        {
                          width: `${row.width}%`,
                          "--step": row.step,
                        } as React.CSSProperties
                      }
                    />
                  </span>
                </td>
                <td className="count mono">{row.count.toLocaleString("en")}</td>
                <td className="share mono">{share(row.share)}</td>
              </tr>
            ))}
            {/* A frequency table that stops at ten without saying so
                contradicts its own arithmetic. */}
            {remainder > 0 ? (
              <tr className="rest">
                <td className="rank" />
                <td className="name">
                  {it.others_distinct.toLocaleString("en")} more value
                  {it.others_distinct === 1 ? "" : "s"}
                </td>
                <td className="bar" />
                <td className="count mono">
                  {it.others_count.toLocaleString("en")}
                </td>
                <td className="share mono">{share(remainder)}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {it.tokens_total > 0 ? (
        <>
          <div className="stat-table">
            <StatBand
              title="Vocabulary"
              rows={[
                ["words", it.tokens_total.toLocaleString("en")],
                ["distinct", it.tokens_distinct.toLocaleString("en")],
                // Type–token ratio. Near 1 is a column of unique strings; near
                // 0 is a template repeated. `comment` scores 0.004.
                ["diversity", brief(diversity)],
                // No `per value` here. It read `tokens_total / present`, which
                // **is** `Words / mean` two bands up: the sum of every row's
                // token count over the row count is the average token count,
                // identical by construction and measured identical at
                // 7.273585 on `comment`. Two names for one number is the panel
                // disagreeing with itself about which to trust.
              ]}
            />
          </div>

          <div className="terms">
            <Terms title="words" items={it.top_words} />
            <Terms title="pairs" items={it.top_pairs} />
            <Terms title="triples" items={it.top_triples} />
          </div>

          {/* ⚠️ **This and the `words` column above it are the same fact.**
              Same query, same counts, same ranks: one as a ranking to count
              down, one as a shape to look at. Both are drawn because the point
              of D-073 is to let the two be compared on real data, and if the
              cloud stays, the `words` column is what it replaces. */}
          <WordCloud items={it.cloud} />

          {it.vocabulary.length > 1 ? (
            <Concentration points={it.vocabulary} unit="terms" />
          ) : null}
        </>
      ) : null}

      {/* **No `Examples` block.** Ten values sorted alphabetically were what
          this panel showed before it had a frequency table, and the table now
          shows the same kind of thing better: for a column with repeats it
          shows the ones that repeat, and for a column of unique values every
          count is 1 and it *is* the sample. `samples` is still computed and
          still on the wire. */}
    </>
  );
}

/* ------------------------------------------------------------ word cloud ---

   Kept out twice on one argument, and the argument has not changed: **a cloud
   encodes frequency as font size**, and a reader compares glyph heights far
   worse than they compare bar lengths on a shared baseline. It is the encoding
   objection that sank the treemap in D-060, and no scope decision repairs it.

   It is drawn anyway, at the product owner's direction and after the objection
   was put twice (D-073), but in the form that costs the least:

   **Area, not height.** The size is `sqrt(count)`, so a word twice as common
   covers twice the *area* rather than four times it. A cloud scaled linearly
   on font size is the version of this chart that actually lies.

   **No rotation.** Half the words turned on their side is the decoration that
   makes clouds unreadable, and it buys nothing but density.

   **No randomness.** Placement is a fixed spiral walked in rank order, so the
   same column draws the same cloud every time. INV-6 is about the numbers, but
   a figure that reshuffles on every open is a figure nobody can refer to. */

/** The box the cloud is laid out in, in viewBox units. */
const CLOUD_BOX = { w: 1000, h: 300 } as const;
const CLOUD_MAX = 62;
const CLOUD_MIN = 11;
const CLOUD_PAD = 7;

/** Narrow and wide glyphs, so packing does not have to measure the DOM.
 *
 *  `measureText` would be exact and costs a canvas context, which jsdom does
 *  not implement and complains to `console.error` about, and a warning is a
 *  defect here (see `vitest.setup.ts`). An em table is deterministic, runs
 *  identically anywhere, and is wrong by a few percent in a layout that
 *  already pads every box by 7 units. */
const CLOUD_NARROW = new Set([...`iljtfrI.,;:'|!()[]{} `]);
const CLOUD_WIDE = new Set([..."mwMW@%"]);

function cloudSpan(text: string, size: number): number {
  let em = 0;
  for (const glyph of text) {
    em += CLOUD_NARROW.has(glyph) ? 0.36 : CLOUD_WIDE.has(glyph) ? 0.95 : 0.62;
  }
  return em * size;
}

type Placed = {
  value: string;
  count: number;
  size: number;
  x: number;
  y: number;
  step: number;
};

/**
 * Rank order down an Archimedean spiral, first non-overlapping position wins.
 *
 * The spiral is stretched by the box's own aspect so a wide panel fills with a
 * wide cloud rather than a circle in the middle of one. A word that finds no
 * room inside the box is **dropped rather than shrunk**. Shrinking it to fit
 * would put a word on screen at a size its count did not earn, which is the
 * one thing this figure cannot afford given what it already asks of the eye.
 */
function packCloud(items: TopValue[]): Placed[] {
  const top = items[0]?.count ?? 0;
  if (top <= 0) return [];
  const stretch = CLOUD_BOX.w / CLOUD_BOX.h;
  const cx = CLOUD_BOX.w / 2;
  const cy = CLOUD_BOX.h / 2;
  const placed: Placed[] = [];
  const boxes: { x: number; y: number; w: number; h: number }[] = [];

  items.forEach((item, index) => {
    // Area proportional to count, which is what `sqrt` buys.
    const size = Math.max(CLOUD_MIN, CLOUD_MAX * Math.sqrt(item.count / top));
    const w = cloudSpan(item.value, size) + CLOUD_PAD;
    const h = size * 1.02 + CLOUD_PAD;
    if (w > CLOUD_BOX.w || h > CLOUD_BOX.h) return;

    for (let tick = 0; tick < 2600; tick += 1) {
      const angle = tick * 0.18;
      const radius = angle * 1.15;
      const x = cx + Math.cos(angle) * radius * stretch;
      const y = cy + Math.sin(angle) * radius;
      const box = { x: x - w / 2, y: y - h / 2, w, h };
      if (
        box.x < 0 ||
        box.y < 0 ||
        box.x + w > CLOUD_BOX.w ||
        box.y + h > CLOUD_BOX.h
      ) {
        continue;
      }
      const clear = boxes.every(
        (other) =>
          box.x + box.w <= other.x ||
          other.x + other.w <= box.x ||
          box.y + box.h <= other.y ||
          other.y + other.h <= box.y,
      );
      if (!clear) continue;
      boxes.push(box);
      placed.push({
        value: item.value,
        count: item.count,
        size,
        x,
        y,
        step: ramp(index, items.length),
      });
      return;
    }
  });

  return placed;
}

function WordCloud({ items }: { items: TopValue[] }) {
  const [over, setOver] = useState<string | null>(null);
  // `items ?? []` guards a field that is *typed* as always present. A 200 with
  // a key missing is a shape this wire has produced before — `presence` was
  // dropped by the response model's whitelist and failed nowhere (D-056) — and
  // a bundle cached under an older `tool_version` has the same shape. Every
  // other block on this panel would still render; without this the whole panel
  // throws on `items[0]` and the column shows nothing at all.
  const placed = useMemo(() => packCloud(items ?? []), [items]);
  if (placed.length === 0) return null;

  const lit = placed.find((word) => word.value === over);

  return (
    <figure className="figure">
      <div
        className="cloud-wrap"
        role="img"
        aria-label={`The ${placed.length.toLocaleString("en")} commonest terms, sized by how often each occurs.`}
        onPointerLeave={() => setOver(null)}
      >
        <svg
          className="cloud"
          viewBox={`0 0 ${CLOUD_BOX.w} ${CLOUD_BOX.h}`}
          aria-hidden="true"
        >
          {placed.map((word) => (
            <text
              key={word.value}
              x={word.x}
              y={word.y}
              fontSize={word.size}
              data-lit={word.value === over || undefined}
              style={{ "--step": word.step } as React.CSSProperties}
              onPointerEnter={() => setOver(word.value)}
            >
              {word.value}
            </text>
          ))}
        </svg>
      </div>
      {/* Hover only. It said `14 more did not fit` when the spiral ran out of
          room, and that line is gone at the owner's request. The count was of
          the sixty terms *offered* rather than of the vocabulary, so on a
          column with 103 distinct words it accounted for 14 of the 43 that are
          missing and stayed quiet about the other 29 — `distinct` in the band
          above and the right end of the curve's axis below both carry the real
          figure. The blank keeps the line's height, so nothing shifts when a
          word is hovered. */}
      <p className="chart-note" data-lit={lit !== undefined}>
        {lit !== undefined
          ? `${lit.value} · ${lit.count.toLocaleString("en")}`
          : " "}
      </p>
    </figure>
  );
}

/** A histogram over a measure derived from the value rather than over the value. */
function Measure({
  title,
  bins,
  unit,
}: {
  title: string;
  bins: Bin[];
  unit: string;
}) {
  const [over, setOver] = useState<number | null>(null);
  if (bins.length === 0) return null;
  const tallest = Math.max(1, ...bins.map((bin) => bin.count));
  const lit = over === null ? undefined : bins[over];

  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      0.999999,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    setOver(Math.floor(fraction * bins.length));
  }

  return (
    <figure className="figure">
      <figcaption className="caps">{title}</figcaption>
      <div
        className="histogram short"
        role="img"
        aria-label={`Distribution of ${title}.`}
        onPointerMove={probe}
        onPointerLeave={() => setOver(null)}
      >
        {bins.map((bin) => (
          <span
            key={bin.lower}
            className="bar"
            data-lit={bins.indexOf(bin) === over}
            style={{
              height: `${bin.count === 0 ? 0 : Math.max(2, (bin.count / tallest) * 100)}%`,
            }}
          />
        ))}
      </div>
      <p className="chart-note" data-lit={lit !== undefined}>
        {lit === undefined
          ? `${num(bins.at(0)?.lower ?? null)} to ${num(bins.at(-1)?.upper ?? null)} ${unit}`
          : `${num(lit.lower)} to ${num(lit.upper)} ${unit} · ${lit.count.toLocaleString("en")}`}
      </p>
    </figure>
  );
}

/** One column of the vocabulary: the commonest terms at one n-gram width. */
function Terms({ title, items }: { title: string; items: TopValue[] }) {
  const widest = Math.max(1, ...items.map((item) => item.count));
  return (
    <figure className="terms-column">
      <figcaption className="caps">{title}</figcaption>
      {items.length === 0 ? (
        // A single-token column has no pairs, and saying so beats an empty box.
        <p className="chart-note">none</p>
      ) : (
        <ul className="value-bars">
          {items.map((item, index) => (
            <li key={item.value}>
              {/* Truncated, not marqueed. `Ellipsis` scrolls its text when it
                  overflows, which is right for a column name in a header and
                  wrong for a list of terms: a trigram wider than its slot read
                  as its own value printed twice. */}
              <span className="label" title={item.value}>
                {item.value}
              </span>
              <span className="track">
                <span
                  className="fill"
                  style={
                    {
                      width: `${(item.count / widest) * 100}%`,
                      "--step": ramp(index, items.length),
                    } as React.CSSProperties
                  }
                />
              </span>
              <span className="mono count">
                {item.count.toLocaleString("en")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}

function DateShape({
  it,
  present,
}: {
  it: NonNullable<ColumnDetail["date"]>;
  present: number;
}) {
  // The finest grain the panel can draw legibly. `by_day` arrives empty past
  // the span limit, so this falls through on its own.
  const grains: { key: Grain; series: { key: string; count: number }[] }[] = [
    { key: "day", series: it.by_day },
    { key: "month", series: it.by_month },
    { key: "year", series: it.by_year },
  ];
  const offered = grains.filter((grain) => grain.series.length > 0);
  const natural =
    offered.find((grain) => grain.series.length <= 120) ?? offered.at(-1);
  const [grain, setGrain] = useState<Grain | null>(null);
  const shown = offered.find((each) => each.key === grain) ?? natural;

  const empty = Math.max(0, it.days_in_span - it.days_seen);
  const partial = it.conforming < present;

  return (
    <>
      <div className="stat-table">
        <StatBand
          title="Coverage"
          rows={[
            // First, and red when it is not everything: every figure below is
            // computed from these values and from no others.
            partial
              ? ([
                  "parsed",
                  `${it.conforming.toLocaleString("en")} of ${present.toLocaleString("en")}`,
                  "everything below is computed from these values alone",
                ] as const)
              : ([
                  "parsed",
                  `${it.conforming.toLocaleString("en")} of ${present.toLocaleString("en")}`,
                ] as const),
            ["start", day(it.earliest)],
            ["end", day(it.latest)],
            [
              "span",
              it.span_days === null
                ? "n/a"
                : `${it.span_days.toLocaleString("en")} days`,
            ],
          ]}
          alarm={partial ? "parsed" : undefined}
        />
        <StatBand
          title="Calendar"
          rows={[
            ["grain", it.granularity],
            ["days seen", it.days_seen.toLocaleString("en")],
            ["days empty", empty.toLocaleString("en")],
            ["of", it.days_in_span.toLocaleString("en")],
          ]}
        />
      </div>

      {shown === undefined ? null : (
        <figure className="figure">
          <figcaption className="chart-legend">
            {offered.map((each) => (
              <button
                key={each.key}
                type="button"
                className="grain"
                data-on={each.key === shown.key}
                onClick={() => setGrain(each.key)}
              >
                {each.key}
              </button>
            ))}
          </figcaption>
          {/* Switching grain is **display only**: all three series arrive in
              one bundle under one `computation_id`, so no button here can
              produce a number the panel did not already have. */}
          <Series points={shown.series} />
        </figure>
      )}

      {/* One cell per day, seven rows deep (D-074). The timeline above counts
          rows over time and the cycles below fold the whole span onto seven
          bars; neither can show **where** the quiet is. 243 of `order_date`'s
          901 days hold nothing, and here that is a pattern rather than a
          number: a blank column is a week nobody ordered, a blank row is a
          weekday nobody ever orders. */}
      {it.by_day.length > 0 ? <Calendar days={it.by_day} /> : null}

      <div className="cycles">
        {/* `day of week`, not `by weekday`, and `month of year`, not `by
            month`: the timeline above has a **month** grain that means
            something else entirely, and one word for two figures on one panel
            is how a reader learns to distrust both. */}
        <Cycle title="day of week" points={it.by_weekday} />
        <Cycle title="month of year" points={it.by_month_of_year} />
        {/* Absent rather than twenty-four empty bars: a column of dates without
            times has no hours to distribute, and an empty frame reads as a
            finding (§11.8.3). */}
        {it.by_hour.length > 0 ? (
          <Cycle title="hour of day" points={it.by_hour} />
        ) : null}
      </div>
    </>
  );
}

/** Monday first, matching `by_weekday` and `isodow` on the server. */
const CAL_ROWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const CAL_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/**
 * The span as a calendar: one cell per day, weeks across, weekdays down.
 *
 * **What no other figure on this panel can show is where the gaps are.** The
 * timeline counts rows over time, and at month grain a fortnight of silence
 * inside a busy month is invisible. The cycles fold every Monday in the span
 * onto one bar, so a run of dead Mondays in April reads exactly like Mondays
 * being quiet throughout. Here a blank column is a week nobody ordered and a
 * blank row is a weekday nobody ever does.
 *
 * ⚠️ **Colour carries the count, and colour is a weak encoding for magnitude.**
 * Accepted rather than overlooked: this figure is read for *pattern*, the
 * timeline above it does magnitude, and the levels stop at four so no reader is
 * invited to rank two shades. **Zero is not blank** — a day inside the span
 * with no rows gets its own faint cell, because the gaps are the finding and a
 * gap drawn as nothing looks like the edge of the data.
 */
function Calendar({ days }: { days: { key: string; count: number }[] }) {
  const [over, setOver] = useState<string | null>(null);

  const cells = useMemo(() => {
    const first = days[0];
    if (first === undefined) return null;
    // `Date.UTC` throughout: `new Date("2023-01-01")` is UTC midnight, and
    // asking it for a *local* weekday moves the whole grid by a day for every
    // reader west of Greenwich.
    const start = new Date(`${first.key}T00:00:00Z`);
    if (Number.isNaN(start.getTime())) return null;
    // Monday of the week the span opens in, so column 0 is a whole week.
    const lead = (start.getUTCDay() + 6) % 7;

    const top = Math.max(1, ...days.map((day) => day.count));
    const slots = days.map((day, index) => {
      const place = lead + index;
      return {
        key: day.key,
        count: day.count,
        week: Math.floor(place / 7),
        row: place % 7,
        // Four levels and no more. Enough to see a busy week, few enough that
        // nobody tries to read a number off a shade.
        level:
          day.count === 0 ? 0 : Math.min(4, Math.ceil((day.count / top) * 4)),
      };
    });
    const weeks = Math.floor((lead + days.length - 1) / 7) + 1;

    // A month label spans the week columns it owns, so it lines up with the
    // grid instead of being positioned by arithmetic that has to agree with
    // the grid's gaps. Each column belongs to the month of its earliest day,
    // so the spans sum to `weeks` exactly and nothing drifts.
    const owner: (number | undefined)[] = Array.from({ length: weeks });
    for (const slot of slots) {
      owner[slot.week] ??= Number(slot.key.slice(5, 7)) - 1;
    }
    const months: { label: string; span: number }[] = [];
    for (const month of owner) {
      const label = month === undefined ? "" : (CAL_MONTHS[month] ?? "");
      const last = months.at(-1);
      if (last !== undefined && last.label === label) last.span += 1;
      else months.push({ label, span: 1 });
    }

    return { slots, weeks, months };
  }, [days]);

  if (cells === null) return null;
  const lit = cells.slots.find((slot) => slot.key === over);

  return (
    <figure className="figure">
      <div
        className="calendar"
        style={{ "--weeks": cells.weeks } as React.CSSProperties}
      >
        {/* The labels hang **inside the plot**, positioned against the grid's
            own height, rather than sitting in a column beside it. As a sibling
            they were the taller element: seven lines of 11px text is 77px and
            the grid over a two-year span is 54px, so the row sized itself to
            the labels and every one of them drifted below the row it named. */}
        <div className="cal-plot">
          {/* One handler for the whole grid rather than one per day: a
            two-and-a-half-year span is nine hundred cells. */}
          <div
            className="cal-grid"
            role="img"
            aria-label={`One cell per day across the span, ${cells.weeks.toLocaleString("en")} weeks.`}
            style={{ aspectRatio: `${cells.weeks} / 7` }}
            onPointerOver={(event) => {
              const day = (event.target as HTMLElement).dataset.day;
              if (day !== undefined) setOver(day);
            }}
            onPointerLeave={() => setOver(null)}
          >
            {cells.slots.map((slot) => (
              <span
                key={slot.key}
                data-day={slot.key}
                data-level={slot.level}
                data-lit={slot.key === over || undefined}
                style={{ gridColumn: slot.week + 1, gridRow: slot.row + 1 }}
              />
            ))}
          </div>
          {CAL_ROWS.map((day, index) =>
            // Every other one. Seven labels over a row 8px tall collide, and
            // four are more than enough to count from.
            index % 2 === 0 ? (
              <span
                key={day}
                className="cal-day"
                aria-hidden="true"
                style={{ top: `${(index / 7) * 100}%` }}
              >
                {day}
              </span>
            ) : null,
          )}
        </div>
        <div className="cal-months" aria-hidden="true">
          {cells.months.map((month, index) => (
            <span
              key={`${month.label}-${index}`}
              style={{ gridColumn: `span ${month.span}` }}
            >
              {/* A month owning one or two columns has no room for its name,
                  and a label squeezed into 16px is a smudge that still costs
                  the reader a glance. */}
              {month.span > 2 ? month.label : ""}
            </span>
          ))}
        </div>
      </div>
      <p className="chart-note" data-lit={lit !== undefined}>
        {lit === undefined
          ? "\u00a0"
          : `${lit.key} · ${lit.count.toLocaleString("en")}`}
      </p>
    </figure>
  );
}

type Grain = "day" | "month" | "year";

/** The timeline: one bar per calendar bucket, empties included. */
function Series({ points }: { points: { key: string; count: number }[] }) {
  const [over, setOver] = useState<number | null>(null);
  const tallest = Math.max(1, ...points.map((point) => point.count));
  const lit = over === null ? undefined : points[over];

  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      0.999999,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    setOver(Math.floor(fraction * points.length));
  }

  return (
    <>
      {/* **The gap has to go when the buckets are many.** `.histogram` puts 2px
          between bars, which is right for twenty and fatal for nine hundred:
          901 gaps is 1,802px inside a 1,030px box, so every bar collapses to
          nothing and the figure renders blank. Past 150 buckets the bars sit
          flush, the way the completeness strip does, and the chart reads as a
          density field rather than as a row of bars. */}
      <div
        className="histogram tall"
        data-dense={points.length > 150 || undefined}
        role="img"
        aria-label={`Counts across ${points.length.toLocaleString("en")} calendar buckets.`}
        onPointerMove={probe}
        onPointerLeave={() => setOver(null)}
      >
        {points.map((point, index) => (
          <span
            key={point.key}
            className="bar"
            data-lit={index === over}
            // An empty bucket draws nothing at all: the floor that keeps a
            // small bar visible would make a gap look like a value.
            style={{
              height: `${point.count === 0 ? 0 : Math.max(2, (point.count / tallest) * 100)}%`,
            }}
          />
        ))}
        {over !== null && lit !== undefined ? (
          <Readout
            at={((over + 0.5) / points.length) * 100}
            bottom={
              lit.count === 0 ? 0 : Math.max(2, (lit.count / tallest) * 100)
            }
          >
            {lit.key} · {lit.count.toLocaleString("en")}
          </Readout>
        ) : null}
      </div>
      <div className="chart-axis mono">
        <span>{points.at(0)?.key}</span>
        <span>{points.at(-1)?.key}</span>
      </div>
    </>
  );
}

/**
 * One cyclic distribution, folded across the whole span.
 *
 * The domain is always complete — seven weekdays, twelve months, twenty-four
 * hours — because *nothing on Sunday* is a finding and a chart of six bars is a
 * chart that lost one.
 */
function Cycle({
  title,
  points,
}: {
  title: string;
  points: { key: string; count: number }[];
}) {
  const [over, setOver] = useState<number | null>(null);
  const tallest = Math.max(1, ...points.map((point) => point.count));
  const lit = over === null ? undefined : points[over];

  return (
    <figure className="cycle">
      <figcaption className="caps">{title}</figcaption>
      <div className="bars" onPointerLeave={() => setOver(null)}>
        {points.map((point, index) => (
          <span
            key={point.key}
            className="stem"
            data-lit={index === over}
            onPointerEnter={() => setOver(index)}
          >
            <span
              className="bar"
              style={{
                height: `${point.count === 0 ? 0 : Math.max(3, (point.count / tallest) * 100)}%`,
              }}
            />
          </span>
        ))}
      </div>
      {/* **Labelled, or the chart cannot be read.** Seven bars and a note
          saying *peak Fri* leaves the reader counting from one end to find it.
          Twenty-four hours have no room for twenty-four labels, so that one
          prints every third — enough to locate a bar by counting one or two
          along, which seven or twelve never require. */}
      <div className="ticks" aria-hidden="true">
        {points.map((point, index) => (
          <span
            key={point.key}
            data-shown={points.length <= 12 || index % 3 === 0}
          >
            {point.key}
          </span>
        ))}
      </div>
      {/* No count in front of the peak. `7 ·` sits under seven labelled bars,
          `12 ·` under twelve, `24 ·` under an axis running 00 to 21 — each one
          counts what the reader is already looking at. */}
      <p className="chart-note" data-lit={lit !== undefined}>
        {lit === undefined
          ? `peak ${points.reduce((best, point) => (point.count > best.count ? point : best)).key}`
          : `${lit.key} · ${lit.count.toLocaleString("en")}`}
      </p>
    </figure>
  );
}

function Boolean({
  it,
  present,
}: {
  it: NonNullable<ColumnDetail["boolean"]>;
  present: number;
}) {
  const [over, setOver] = useState<number | null>(null);
  const classes: {
    rank: number;
    label: string;
    count: number;
    tone: Slice["tone"];
  }[] = [
    { rank: 1, label: "true", count: it.true_count, tone: 1 },
    { rank: 2, label: "false", count: it.false_count, tone: "rest" },
    { rank: 3, label: "neither", count: it.other_count, tone: "other" },
  ];

  const widest = Math.max(1, ...classes.map((each) => each.count));
  let cursor = 0;
  const slices: Slice[] = [];
  const rows: {
    rank: number;
    label: string;
    count: number;
    share: number;
    width: number;
    tone: Slice["tone"];
  }[] = [];
  for (const each of classes) {
    if (each.count === 0) continue;
    const portion = present === 0 ? 0 : each.count / present;
    const from = cursor;
    cursor += portion;
    slices.push({
      rank: each.rank,
      from,
      to: cursor,
      tone: each.tone,
      label: each.label,
      detail: `${each.count.toLocaleString("en")} · ${share(portion)}`,
      pin: false,
    });
    rows.push({
      rank: each.rank,
      label: each.label,
      count: each.count,
      share: portion,
      width: (each.count / widest) * 100,
      tone: each.tone,
    });
  }
  if (slices.length === 0) return null;

  return (
    <div className="composition">
      {/* **The counts came back** (D-067). D-066 left this panel at a strip and
          a ring on the argument that a two-row table is the same pair of counts
          at greater length — which was true of the *ring*, and false of a
          reader who is not hovering it. The exact figures existed only under a
          pointer, and the product owner's complaint was the emptiness that
          bought.

          It is the categorical anatomy exactly: table on the left, ring on the
          right, hover lighting both. The width is filled with information
          rather than with a larger circle. */}
      <table className="freq" onPointerLeave={() => setOver(null)}>
        <thead>
          <tr>
            <th className="name">class</th>
            <th className="bar" aria-label="share of values" />
            <th>count</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.label}
              data-lit={over === row.rank}
              data-tone={typeof row.tone === "string" ? row.tone : undefined}
              onPointerEnter={() => setOver(row.rank)}
            >
              <td className="name">{row.label}</td>
              <td className="bar">
                <span className="track">
                  <span
                    className="fill"
                    style={
                      typeof row.tone === "number"
                        ? ({
                            width: `${row.width}%`,
                            "--step": row.tone,
                          } as React.CSSProperties)
                        : { width: `${row.width}%` }
                    }
                  />
                </span>
              </td>
              <td className="count mono">{row.count.toLocaleString("en")}</td>
              <td className="share mono">{share(row.share)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <Donut slices={slices} total={present} over={over} onOver={setOver} />
    </div>
  );
}

function Histogram({
  bins,
  markers = [],
}: {
  bins: Bin[];
  markers?: { kind: "mean" | "median"; value: number | null }[];
}) {
  const [over, setOver] = useState<number | null>(null);
  const lo = bins.at(0)?.lower;
  const hi = bins.at(-1)?.upper;
  if (lo === undefined || hi === undefined) return null;
  const tallest = Math.max(1, ...bins.map((b) => b.count));
  const drawn =
    hi > lo ? markers.filter((marker) => marker.value !== null) : [];
  const lit = over === null ? undefined : bins[over];

  /** Which bar, from the pointer's x — not from a hit area on each bar.

      The bars are equal width with a 2px gap, and hovering the bars themselves
      would drop the readout every time the pointer crossed a gap. Dividing the
      width by the bin count has no gaps in it. */
  function probe(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const fraction = Math.min(
      0.999999,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    setOver(Math.floor(fraction * bins.length));
  }

  return (
    <div
      className="histogram tall"
      role="img"
      aria-label={`Histogram of ${bins.length} bins from ${num(lo)} to ${num(hi)}.`}
      onPointerMove={probe}
      onPointerLeave={() => setOver(null)}
    >
      {bins.map((bin, index) => (
        <span
          key={bin.lower}
          className="bar"
          data-lit={index === over}
          // Percentage of the tallest bar, not of the row count: a column where
          // one bucket holds 98% would otherwise draw one visible bar and
          // nineteen invisible ones, which is true and unreadable.
          //
          // **The floor does not apply to an empty bin (D-051).** It did, and
          // on `amount` it drew fifteen identical stubs along the tail — some
          // holding a handful of rows and some holding none, at exactly the
          // same height. A gap in the data is one of the things a histogram is
          // read for, and the floor was hiding every one of them.
          style={{
            height: `${bin.count === 0 ? 0 : Math.max(2, (bin.count / tallest) * 100)}%`,
          }}
        />
      ))}
      {drawn.map((marker) => (
        <span
          key={marker.kind}
          className={`marker ${marker.kind}`}
          style={{
            left: `${Math.min(100, Math.max(0, (((marker.value as number) - lo) / (hi - lo)) * 100))}%`,
          }}
        />
      ))}
      {over !== null && lit !== undefined ? (
        <Readout
          at={((over + 0.5) / bins.length) * 100}
          bottom={
            lit.count === 0 ? 0 : Math.max(2, (lit.count / tallest) * 100)
          }
        >
          {num(lit.lower)} – {num(lit.upper)} · {lit.count.toLocaleString("en")}
        </Readout>
      ) : null}
    </div>
  );
}

/**
 * The label that follows a pointer across a figure.
 *
 * It flips at the halfway marks rather than being clamped to the edges: a
 * clamped label stops tracking the thing it names, and one that flips never
 * leaves the figure **and** never covers the part being read.
 */
function Readout({
  at,
  bottom,
  children,
}: {
  at: number;
  bottom: number;
  children: React.ReactNode;
}) {
  return (
    <span
      className="chart-readout mono"
      style={{
        left: `${at}%`,
        bottom: `${bottom}%`,
        transform: `translate(${at > 50 ? "calc(-100% - 10px)" : "10px"}, ${
          bottom > 55 ? "calc(100% + 10px)" : "-10px"
        })`,
      }}
    >
      {children}
    </span>
  );
}

/**
 * A figure, at seven significant digits, grouped.
 *
 * **The compact threshold moved from 100,000 to a billion (D-051), because
 * where these numbers are shown changed.** It was chosen when every one of
 * them lived in a chip about six characters wide, and `146.8K` was the honest
 * trade for the room available. They now sit in a table cell with a column to
 * itself — and in that setting compact notation stopped being a compromise and
 * started being a loss: the five largest `amount` values read `2.3M`, `1.8M`,
 * `1.3M`, `1.2M`, `1.2M`, of which the last two are different numbers rendered
 * identically. A list of extremes exists to show the values.
 *
 * Seven digits rather than four decimals: it holds `512.3292` whole — the
 * figure `test_column_profile.py` pins against Titanic itself — and it stops
 * `146,847.4966666667` claiming ten digits of precision the file cannot carry.
 * Above a billion the grouping is worse than the abbreviation, so variance on
 * a large column goes back to `27.9B`.
 */
function num(value: number | null): string {
  return figure(value, 7);
}

/**
 * A **derived summary**, at four significant digits.
 *
 * The split is between figures that came out of the file and figures the
 * profiler worked out: `p99 823,698` and `max 512.3292` are values somebody
 * may go and look up, and they keep every digit they have. A mean, a ratio, a
 * skew is read as a magnitude — is it 0, is it 1, is it 5 — and no reading of
 * a column changes between `19.67` and `19.67333`.
 *
 * Seven digits on a small number is many decimals, which is how
 * `chars per word` rendered as `6.557778` and **overran its own label**. Four
 * significant digits holds `19.67`, `6.558` and `0.004035` alike, which a cap
 * on decimals could not: two decimals would round a type-token ratio to zero.
 */
function brief(value: number | null): string {
  return figure(value, 4);
}

/**
 * **One parameter each, and that is not a stylistic choice.**
 *
 * `num` briefly took the digit count as an optional second argument, and
 * `it.smallest.map(num)` then handed it the array index — so the first extreme
 * asked `Intl` for zero significant digits and the whole panel threw
 * `RangeError` before it rendered a single row. TypeScript accepted it:
 * `(value: number, digits?: number) => string` is assignable to a `map`
 * callback, which is exactly why the compiler could not help. Chrome found it,
 * and eleven of the fourteen tests in `ColumnPanel.test.tsx` turn red the moment
 * the second parameter comes back — the panel throws before it renders a row.
 */
function figure(value: number | null, digits: number): string {
  if (value === null) return "n/a";
  const magnitude = Math.abs(value);
  // A skewness of -0.0000001 renders as `-0` through `Intl.NumberFormat`, which
  // is arithmetically true and reads as a mistake. Anything that would round to
  // zero at this precision is written as zero, without a sign.
  if (magnitude < 5e-5) return "0";
  if (magnitude >= 1e9) {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat("en", {
    maximumSignificantDigits: digits,
  }).format(value);
}

function share(value: number): string {
  if (value === 0) return "0%";
  // Below a tenth of a percent, one decimal rounds to `0.0%`, which reads as
  // none. `<0.1%` says the true thing in the same width.
  if (value < 0.001) return "<0.1%";
  return `${(value * 100).toFixed(1)}%`;
}

function day(iso: string | null): string {
  return iso === null ? "n/a" : iso.slice(0, 10);
}
