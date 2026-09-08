import { fireEvent, render, screen, waitForElementToBeRemoved } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ColumnPanel, shareAtOrBelow } from "@/components/ColumnPanel";
import { ApiError, type ColumnDetail, api } from "@/lib/api";

/**
 * The panel behind a profile card (§11.7).
 *
 * What cannot be asserted here is what it looks like: jsdom has no layout, and
 * the histogram's height, the type hue reaching it and the sticky header were
 * all checked in Chrome against the real stylesheet. What is left is the part
 * with rules attached — the navigation §11.7.6(f) argued a modal could not
 * have, and the geometry the figures compute in JS rather than in CSS, which
 * is assertable precisely because it is arithmetic.
 *
 * **One rule stopped being assertable here on 2026-08-26.** The receipt —
 * `profile_column v5 · c0ffee00 · 64 ms`, fingerprint in its tooltip — was the
 * one element on this panel that INV-5 could be *tested* through, and D-052
 * removed it. `computation_id`, `fingerprint` and `tool_version` are still in
 * the fixture below because they are still on the wire; nothing on screen
 * reads them any more, so nothing here can check that anything does.
 *
 * The figures are Titanic's `Fare` throughout, at the values
 * `tests/unit/test_column_profile.py` pins against the file itself. A fixture
 * of invented numbers would let the whiskers and the fence agree by accident;
 * on `Fare` they genuinely differ — the fence is 65.6344 and the largest value
 * inside it is 65.
 */
const BASE: ColumnDetail = {
  computation_id: "c0ffee00-0000-4000-8000-000000000000",
  fingerprint: "f".repeat(64),
  tool_name: "profile_column",
  tool_version: 5,
  computed_at: "2026-01-01T00:00:00Z",
  duration_ms: 64,
  column: "fare",
  logical_type: "numerical",
  physical_type: "VARCHAR",
  narrative: "fare — numerical. 891 values, 0.0% null, 248 distinct.",
  completeness: {
    total: 891,
    present: 891,
    nulls: 0,
    empty: 0,
    null_share: 0,
    zeros: 15,
    negatives: 0,
  },
  // Four slots covering 891 rows, the third of them holding a gap — enough to
  // assert the strip is drawn from the file's own order rather than from a
  // count, without pasting 223 of them.
  presence: {
    rows_per_slot: 223,
    slots: [
      { rows: 223, present: 223 },
      { rows: 223, present: 223 },
      { rows: 223, present: 120 },
      { rows: 222, present: 222 },
    ],
  },
  cardinality: { distinct: 248, is_unique: false },
  numeric: {
    conforming: 891,
    mean: 32.2042079685746,
    median: 14.4542,
    mode: 8.05,
    std: 49.69342859718089,
    variance: 2469.4368457431156,
    minimum: 0,
    maximum: 512.3292,
    value_range: 512.3292,
    iqr: 23.0896,
    skewness: 4.787316519674892,
    kurtosis: 33.398140880898595,
    quantiles: [
      { q: 0.01, value: 0 },
      { q: 0.05, value: 7.225 },
      { q: 0.25, value: 7.9104 },
      { q: 0.5, value: 14.4542 },
      { q: 0.75, value: 31 },
      { q: 0.95, value: 112.0791 },
      { q: 0.99, value: 249.0062 },
    ],
    outlier_low: -26.724,
    outlier_high: 65.6344,
    outlier_count: 116,
    whisker_low: 0,
    whisker_high: 65,
    smallest: [0, 0, 0, 0, 0],
    largest: [512.3292, 512.3292, 512.3292, 263, 263],
    bins: [
      { lower: 0, upper: 256.1646, count: 838 },
      { lower: 256.1646, upper: 512.3292, count: 53 },
    ],
    ecdf: [
      { p: 0, value: 0 },
      { p: 0.5, value: 14.4542 },
      { p: 1, value: 512.3292 },
    ],
    // Four distinct values on the axis 0..512.3292, at 0%, 25%, 50% and 100%
    // of it, so a tick landing anywhere else is an arithmetic bug rather than
    // a rounding difference.
    rug: [
      { value: 0, count: 15 },
      { value: 128.0823, count: 4 },
      { value: 256.1646, count: 1 },
      { value: 512.3292, count: 3 },
    ],
    rug_stride: 1,
  },
  categorical: null,
  text: null,
  date: null,
  boolean: null,
};

const CATEGORICAL: ColumnDetail = {
  ...BASE,
  logical_type: "categorical",
  numeric: null,
  categorical: {
    top: [
      { value: "male", count: 577 },
      { value: "female", count: 300 },
    ],
    // Fourteen rows in neither of the two named categories, spread over three
    // more — enough that the `others` row has to appear and the cumulative
    // column has to reach 100% without it lying.
    others_count: 14,
    others_distinct: 3,
    top5_share: 1,
    rare_categories: 2,
    concentration: [
      { rank: 1, share: 0.6476 },
      { rank: 2, share: 0.9843 },
      { rank: 3, share: 0.9944 },
      { rank: 4, share: 0.9989 },
      { rank: 5, share: 1 },
    ],
  },
  completeness: { ...BASE.completeness, zeros: null, negatives: null },
};

/**
 * Wait for the bundle to arrive.
 *
 * This was `findByText(/profile_column/)` while the receipt existed (D-052
 * removed it), then `/Central tendency|Completeness/` while every type still
 * rendered one or the other (D-061 removed the Completeness block from the
 * second type). Chasing a shared element was the mistake both times — the
 * five shapes have less in common with every revision.
 *
 * The loading line is the one thing every type shows and every type stops
 * showing, whatever it renders next.
 */
async function loaded(): Promise<void> {
  await waitForElementToBeRemoved(() => screen.queryByText(/Reading this column/));
}

const TEXT: ColumnDetail = {
  ...BASE,
  logical_type: "text",
  numeric: null,
  text: {
    length_min: 3,
    length_median: 5,
    length_mean: 6.2,
    length_max: 12,
    words_min: 1,
    words_median: 1,
    words_mean: 1,
    words_max: 1,
    length_bins: [{ lower: 3, upper: 12, count: 891 }],
    word_bins: [{ lower: 1, upper: 1, count: 891 }],
    share_numeric: 0.97,
    share_dateish: 0,
    share_with_digit: 1,
    share_padded: 0,
    share_upper: 1,
    share_punct: 0.5,
    share_url: 0,
    share_non_ascii: 0,
    top: [{ value: "A-001", count: 3 }],
    others_count: 888,
    others_distinct: 245,
    tokens_total: 1782,
    tokens_distinct: 249,
    top_words: [{ value: "a", count: 891 }],
    top_pairs: [{ value: "a 001", count: 3 }],
    top_triples: [],
    cloud: [
      { value: "a", count: 891 },
      { value: "001", count: 223 },
      { value: "002", count: 3 },
    ],
    vocabulary: [
      { rank: 1, share: 0.5 },
      { rank: 249, share: 1 },
    ],
    samples: ["A-001", "A-002"],
  },
  completeness: { ...BASE.completeness, zeros: null, negatives: null },
};

function show(columns = ["fare", "age", "sex"], column = "fare") {
  const onNavigate = vi.fn();
  const onClose = vi.fn();
  const view = render(
    <ColumnPanel
      datasetId="dataset-1"
      column={column}
      columns={columns}
      onClose={onClose}
      onNavigate={onNavigate}
    />,
  );
  return { onNavigate, onClose, container: view.container, unmount: view.unmount };
}

/** The `left`/`width` a figure computed, as numbers rather than as `"12.687%"`. */
function box(container: HTMLElement, selector: string): { left: number; width: number } {
  const element = container.querySelector<HTMLElement>(selector);
  if (element === null) throw new Error(`no ${selector} in the panel`);
  return {
    left: Number.parseFloat(element.style.left),
    width: Number.parseFloat(element.style.width),
  };
}

describe("one column, in depth", () => {
  afterEach(() => vi.restoreAllMocks());

  it("walks to the next column without closing", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { onNavigate, onClose } = show();
    await loaded();

    // §11.7.6(f) rejected a modal because *"it forces you to close before
    // looking at another column"*. This is the answer to that objection rather
    // than to the preference: the dialog navigates, so a sweep never closes it.
    await userEvent.setup().click(screen.getByRole("button", { name: /Next column/ }));

    expect(onNavigate).toHaveBeenCalledWith("age");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("walks the deck from the keyboard, wherever focus happens to be", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    // Opened in the middle of the deck so both directions exist. The panel is
    // controlled — `onNavigate` is a spy, so `column` never actually moves —
    // which is why each press is measured against the same starting card.
    const { onNavigate } = show(["fare", "age", "sex"], "age");
    await loaded();

    // Bound on the **document** since D-057. `key={column}` remounts the whole
    // card on every step, so whatever had focus is destroyed mid-gesture — a
    // dialog-bound handler then works only while the browser happens to hand
    // focus back to the dialog itself. Pressing against `document.body` is the
    // case that used to be luck.
    document.body.focus();
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onNavigate).toHaveBeenLastCalledWith("sex");

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(onNavigate).toHaveBeenLastCalledWith("fare");
  });

  it("leaves a modified arrow alone", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { onNavigate } = show();
    await loaded();

    // Ctrl+→ and Alt+→ are the browser's, and stepping a column on a gesture
    // somebody aimed at their history is a surprise nobody asked for.
    fireEvent.keyDown(document, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(document, { key: "ArrowRight", ctrlKey: true });
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("stops at both ends", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    show(["fare", "age"], "fare");
    await loaded();

    expect(screen.getByRole("button", { name: /Previous column/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Next column/ })).toBeEnabled();
  });

  it("shows a column with a shape, and never the Completeness block", async () => {
    // **The block has no surface left.** It went from numerical (D-059), from
    // categorical (D-061), and from `text` when that type got a shape of its
    // own — every logical type now says in figures what the block said in
    // numbers. `zeros` and `negatives` still arrive as `null` rather than `0`
    // for a non-numeric column, and `test_zero_and_negative_counts_only_exist_
    // for_numbers` on the backend is the guard that outlived the surface.
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);
    const { container } = show();
    await loaded();

    expect(screen.queryByText("Completeness")).not.toBeInTheDocument();
    expect(screen.getByText("Length")).toBeInTheDocument();
    expect(container.querySelector(".presence")).not.toBeNull();
  });

  it("passes the server's own words through when it refuses", async () => {
    // An `ApiError` under 500, which is what the route answers for a column
    // name that is not in this dataset — 422, not 404. The API's failures are
    // written to be read by a person (P6), so the detail is shown rather than
    // replaced with a house message.
    vi.spyOn(api, "columnProfile").mockRejectedValue(
      new ApiError(422, "'Fare ' is not a column of this dataset"),
    );
    show();

    expect(await screen.findByText(/is not a column of this dataset/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});

describe("the numerical panel (D-051)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("says each fact once: the table replaces the narrative and Completeness", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    show();
    // Not `loaded()`: this test is about `Completeness` being absent, and a
    // wait that resolves on either word would be waiting for the thing it is
    // about to deny. The table's own heading is the honest signal.
    await screen.findByText("Central tendency");

    // Every figure the narrative reads out — median, mean, skew, the fence —
    // is now a labelled row or a caption within a screen of it. Two copies of
    // one number is the panel disagreeing with itself about which to trust,
    // and the second copy is the one nobody updates.
    expect(screen.queryByText(BASE.narrative)).not.toBeInTheDocument();
    expect(screen.queryByText("Completeness")).not.toBeInTheDocument();

    expect(screen.getByText("Central tendency")).toBeInTheDocument();
    // `Count & missing` was here until D-059 removed it. What replaced it for
    // the one figure it still owes the reader is the strip's own caption.
    expect(screen.queryByText("Count & missing")).not.toBeInTheDocument();
    expect(screen.getByText(/completeness · /)).toBeInTheDocument();
    // The statistics the owner asked for that this panel did not have before.
    expect(screen.getByText("variance")).toBeInTheDocument();
    expect(screen.getByText("kurtosis")).toBeInTheDocument();
    expect(screen.getByText("range")).toBeInTheDocument();
  });

  it("gives a column with nothing in it the strip, a red statement, and no furniture", async () => {
    // **D-064.** Whatever the type says it is, a column with no values gets one
    // figure and one line. The five shape blocks are already `null` here — the
    // reader will not compute a distribution over no values — so what stood
    // before was §11.7.7's sentence above a Completeness block of zeroes, which
    // is a lot of furniture around the single fact that there is nothing here.
    const empty: ColumnDetail = {
      ...BASE,
      narrative: "fare — numerical. 0 values, 100.0% null, 0 distinct. Every row is null.",
      completeness: { ...BASE.completeness, present: 0, nulls: 891, empty: 0, null_share: 1 },
      cardinality: { distinct: 0, is_unique: false },
      presence: {
        rows_per_slot: 223,
        slots: [
          { rows: 223, present: 0 },
          { rows: 223, present: 0 },
          { rows: 223, present: 0 },
          { rows: 222, present: 0 },
        ],
      },
      numeric: null,
    };
    vi.spyOn(api, "columnProfile").mockResolvedValue(empty);
    const { container } = show();

    // The strip is the one figure that is more informative empty than full,
    // which is why it survives here where the histogram does not: §11.8.3
    // refuses a histogram because an empty frame reads as a finding, and an
    // empty completeness strip **is** the finding.
    const note = await screen.findByText(/No value in any of the 891 rows/);
    expect(container.querySelectorAll(".presence .slot")).toHaveLength(4);
    expect(note).toHaveAttribute("data-empty");

    // Named by kind, not merely "empty". D-059 and D-061 took the NULL-versus-`""`
    // split off every panel that has a table, and this column has no table — so
    // this line is the last place the distinction is drawn at all.
    expect(note).toHaveTextContent("all of them NULL");

    expect(screen.queryByText(empty.narrative)).not.toBeInTheDocument();
    expect(screen.queryByText("Completeness")).not.toBeInTheDocument();
    expect(screen.queryByText("Central tendency")).not.toBeInTheDocument();
    expect(container.querySelector(".freq")).toBeNull();
  });

  it("says which kind of empty when a column is both", async () => {
    // A column can be entirely NULL, entirely `""`, or a mix — and a mix is the
    // case a single word for it would erase.
    vi.spyOn(api, "columnProfile").mockResolvedValue({
      ...BASE,
      completeness: { ...BASE.completeness, present: 0, nulls: 500, empty: 391, null_share: 500 / 891 },
      presence: { rows_per_slot: 891, slots: [{ rows: 891, present: 0 }] },
      numeric: null,
    });
    show();

    expect(await screen.findByText(/500 NULL, 391 empty strings/)).toBeInTheDocument();
  });

  it("gives the outlier count its denominator", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    show();
    await loaded();

    // 116 outliers means one thing in 891 rows and another in 891,000.
    // 116 / 891 = 13.0%.
    const note = screen.getByText(/116 outliers/);
    expect(note).toHaveTextContent("116 outliers (13.0%)");

    // §11.7.6 wants the rule visible rather than magic, and since D-053 the
    // only place it survives is this tooltip — weaker than the rule asks for,
    // and still the difference between *84 rows are wrong* and *this fence was
    // built for symmetric data*. Asserted so that removing it has to be a
    // decision rather than a tidy-up.
    expect(note).toHaveAttribute("title", "IQR fence, k = 1.5 · [-26.724, 65.6344]");
  });

  it("stops the whisker at the last value inside the fence, not at the fence", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { container } = show();
    await loaded();

    // The distinction the two extra server fields exist for. `Fare`'s upper
    // fence is 65.6344 and the largest fare below it is 65, so a whisker drawn
    // to the fence would reach a place no passenger paid. Its low fence is
    // −26.724, which is worse: no fare is negative at all.
    const domain = 512.3292;
    const whisker = box(container, ".boxplot .whisker");
    expect(whisker.left).toBeCloseTo(0, 4);
    expect(whisker.width).toBeCloseTo((65 / domain) * 100, 4);
    expect(whisker.width).not.toBeCloseTo((65.6344 / domain) * 100, 4);

    // And what lies beyond it is drawn as reach rather than as data: one
    // hairline from the whisker cap out to the maximum.
    const tail = box(container, ".boxplot .tail");
    expect(tail.left).toBeCloseTo((65 / domain) * 100, 4);
    expect(tail.width).toBeCloseTo(((domain - 65) / domain) * 100, 4);
  });

  it("puts the mean and median lines on the histogram's own axis", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { container } = show();
    await loaded();

    // The gap between these two lines *is* the skew — the same fact as
    // `skewness 4.7873` in the form people reason with. It only says that if
    // both are placed against the bins' domain rather than against the box.
    const domain = 512.3292;
    expect(box(container, ".histogram .marker.mean").left).toBeCloseTo(
      (32.2042079685746 / domain) * 100,
      4,
    );
    expect(box(container, ".histogram .marker.median").left).toBeCloseTo(
      (14.4542 / domain) * 100,
      4,
    );
  });

  it("stops the shape statistics at four digits and no others", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    show();
    await loaded();

    // Skewness is read as a magnitude — is it 0, is it 1, is it 5 — and no
    // reading of a column changes between 4.787 and 4.787317. `p99`, two
    // columns over, is a value somebody may go and look up in the file, so it
    // keeps every digit it has.
    expect(screen.getByText("skewness").parentElement).toHaveTextContent("4.787");
    expect(screen.getByText("skewness").parentElement).not.toHaveTextContent("4.787317");
    expect(screen.getByText("p99").parentElement).toHaveTextContent("249.0062");
  });

  it("draws the gaps where the file has them, not just how many", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { container } = show();
    await screen.findByText("Central tendency");

    // The one question a count cannot answer. `null 19.9%` says the same thing
    // about a column emptied at the end and one missing at random; the slot
    // opacities say which. Third slot of four is 120/223 present.
    const slots = [...container.querySelectorAll<HTMLElement>(".presence .slot")];
    expect(slots).toHaveLength(4);
    expect(Number.parseFloat(slots[2]!.style.opacity)).toBeCloseTo(120 / 223, 6);
    expect(Number.parseFloat(slots[0]!.style.opacity)).toBe(1);
  });

  it("closes the frequency table's arithmetic with an others row", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(CATEGORICAL);
    const { container } = show();
    await loaded();

    // Two categories shown of five. A table that stopped at the second would
    // contradict its own arithmetic — a reader adds the percentage column and
    // gets 98.4%. This row is the missing 1.6%.
    const rows = [...container.querySelectorAll(".freq tbody tr")];
    expect(rows).toHaveLength(3);
    expect(rows.at(-1)).toHaveClass("rest");
    expect(rows.at(-1)).toHaveTextContent("3 more categories");
    expect(rows.at(-1)?.querySelector(".share")).toHaveTextContent("1.6%");

    // The cumulative column left with D-062; the curve carries it now, and it
    // is drawn for every categorical column rather than only for the ones the
    // table cannot finish.
    expect(container.querySelector(".freq .cumulative")).toBeNull();
    expect(container.querySelector(".curve")).not.toBeNull();

    // And the remainder carries no bar: one for three categories at once would
    // be compared against single categories on the same baseline.
    expect(rows.at(-1)?.querySelector(".fill")).toBeNull();
    expect(rows[0]?.querySelector(".fill")).not.toBeNull();
  });

  it("draws one rug tick per distinct value, at its own position", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BASE);
    const { container } = show();
    await loaded();

    // **Unbinned, and that is the point.** The histogram above it has two
    // bars; a column holding only four values is smooth to that figure and a
    // comb to this one.
    const ticks = [...container.querySelectorAll<HTMLElement>(".rug .tick")];
    expect(ticks).toHaveLength(4);
    expect(ticks.map((tick) => tick.style.left)).toEqual(["0%", "25%", "50%", "100%"]);

    // Weight is `sqrt(count / max)` with a floor, and it rides a custom
    // property so the dim and lit rules can beat it by specificity rather than
    // by `!important`.
    expect(ticks[0]?.style.getPropertyValue("--weight")).toBe("1");
    expect(Number(ticks[2]?.style.getPropertyValue("--weight"))).toBeCloseTo(0.28, 6);
  });

  it("draws no box and no curve for a column that is all one value", async () => {
    // A box of zero width and a vertical ECDF are two figures whose only
    // content is that they are degenerate. The histogram's single bar and the
    // table say the whole truth: min, median and max are the same number.
    const flat: ColumnDetail = {
      ...BASE,
      numeric: {
        ...BASE.numeric!,
        minimum: 7,
        maximum: 7,
        value_range: 0,
        median: 7,
        bins: [{ lower: 7, upper: 7, count: 891 }],
      },
    };
    vi.spyOn(api, "columnProfile").mockResolvedValue(flat);
    const { container } = show();
    await loaded();

    expect(container.querySelector(".histogram")).not.toBeNull();
    expect(container.querySelector(".boxplot")).toBeNull();
    expect(container.querySelector(".ecdf")).toBeNull();
    expect(container.querySelector(".histogram .marker")).toBeNull();
  });
});

/**
 * The arithmetic behind the ECDF's hover readout.
 *
 * Tested here rather than through a pointer event because jsdom has no layout:
 * `getBoundingClientRect()` returns zeros, so `track()` refuses to compute a
 * readout from a zero-width box and nothing would ever render. What the browser
 * checks is that the crosshair lands where the pointer is; what this checks is
 * that the number beside it is the right one.
 */
describe("the text panel (D-070, D-071)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens on length, and no longer on what the characters are", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);
    const { container } = show();
    await loaded();

    // `Looks like` led this panel for one revision (D-070) and D-072 removed
    // it. All eight of its shares are still on the wire and none of them has a
    // reader — so a column that is 97% numbers held as text no longer says so
    // anywhere, and neither does a `padded` value that will split into two
    // categories in every aggregation downstream.
    const rails = [...container.querySelectorAll(".stat-rail")].map((r) => r.textContent);
    expect(rails[0]).toBe("Length");
    expect(screen.queryByText("Looks like")).not.toBeInTheDocument();
    expect(screen.queryByText("non-ASCII")).not.toBeInTheDocument();

    // Two derived distributions, side by side: a column of fixed-width codes
    // spikes in both, prose spreads in both, a URL column is long in
    // characters and one word wide.
    expect(container.querySelectorAll(".pair .histogram")).toHaveLength(2);
  });

  it("keeps derived figures to four digits so they fit their own labels", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);
    show();
    await loaded();

    // `chars per word` rendered as `6.557778` at seven significant digits and
    // **overran its label**. Seven is right for a value from the file and
    // wrong for a mean: 1782 tokens over 891 rows is 2, and 6.2 / 1 is 6.2.
    const perWord = screen.getByText("chars/word").parentElement;
    expect(perWord).toHaveTextContent("6.2");
    expect(screen.getByText("diversity").parentElement).toHaveTextContent("0.1397");
  });

  it("draws the cloud in rank order, at sizes proportional to area", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);
    const { container } = show();
    await loaded();

    // Every term, in the order the server ranked them. `key` is the value, so
    // a duplicate would have shown up as a React warning rather than as a
    // missing word (`vitest.setup.ts` turns that into a failure).
    const words = [...container.querySelectorAll(".cloud text")];
    expect(words.map((word) => word.textContent)).toEqual(["a", "001", "002"]);

    // **`sqrt`, not linear.** 891 against 223 is four times the count. Linear
    // on font size would draw the first word four times the height of the
    // second and so **sixteen times its area**, which is the reading a cloud
    // gets wrong and the reason this figure was refused twice. At sqrt the
    // size ratio is 2 and the areas stand in the ratio the counts do.
    const size = (index: number) => Number(words[index]?.getAttribute("font-size"));
    expect(size(0) / size(1)).toBeCloseTo(Math.sqrt(891 / 223), 6);
    expect(size(0) / size(1)).toBeCloseTo(2, 2);

    // And a floor under it: 3 of 891 works out at 3.6 units in a box 300 deep,
    // which is a smudge rather than a word. Below the floor the encoding stops
    // being true, and that is the honest cost of the clamp.
    expect(size(2)).toBe(11);
  });

  it("places the same column in the same place twice", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);

    // No RNG in the layout. A figure that reshuffles on every open is one
    // nobody can point at, and two readers comparing screens would be looking
    // at two different pictures of one column.
    const positions = async () => {
      const { container, unmount } = show();
      await loaded();
      const seen = [...container.querySelectorAll(".cloud text")].map(
        (word) => `${word.getAttribute("x")},${word.getAttribute("y")}`,
      );
      unmount();
      return seen;
    };
    expect(await positions()).toEqual(await positions());
  });

  it("draws the vocabulary block, and says what its curve counts to a reader who cannot see it", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(TEXT);
    const { container } = show();
    await loaded();

    // §11.7.3 put word cloud, sentiment and NLP outside tabular scope; D-071
    // records the crossing rather than slipping it in. Nothing is removed from
    // the tokens — no stopword list, because a stopword list is a language.
    expect(container.querySelectorAll(".terms-column")).toHaveLength(3);
    expect(screen.getByText("Vocabulary")).toBeInTheDocument();
    // The curve serves two panels, and `categories` is the wrong word on the
    // one counting words. The caption that printed it is gone, so the only
    // place the unit survives is the name a screen reader reads.
    const curve = container.querySelector(".curve-wrap");
    expect(curve).toHaveAttribute("aria-label", expect.stringContaining("terms"));
    expect(curve?.getAttribute("aria-label")).not.toContain("categories");
    expect(screen.queryByText(/share covered by/)).not.toBeInTheDocument();
  });
});

describe("the date panel (D-069)", () => {
  afterEach(() => vi.restoreAllMocks());

  const series = (keys: string[]) => keys.map((key) => ({ key, count: 1 }));
  const DATE: ColumnDetail = {
    ...BASE,
    logical_type: "date",
    numeric: null,
    completeness: { ...BASE.completeness, total: 1200, present: 1200, zeros: null, negatives: null },
    presence: { rows_per_slot: 5, slots: [{ rows: 5, present: 5 }] },
    date: {
      conforming: 1200,
      earliest: "2023-01-01T00:00:00",
      latest: "2023-03-31T00:00:00",
      span_days: 89,
      granularity: "daily",
      days_seen: 60,
      days_in_span: 90,
      by_year: series(["2023"]),
      by_month: series(["2023-01", "2023-02", "2023-03"]),
      // Real ISO keys, because the calendar reads a weekday out of them.
      // 2023-01-01 is a **Sunday**, which is the case worth pinning: Monday
      // leads the grid, so that day belongs in row 7 of column 1 and the six
      // cells above it are days the span does not cover.
      by_day: series(
        Array.from(
          { length: 90 },
          (_, i) => new Date(Date.UTC(2023, 0, 1 + i)).toISOString().slice(0, 10),
        ),
      ),
      by_weekday: series(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
      by_month_of_year: series(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]),
      by_hour: [],
    },
  };

  it("picks the finest grain the span can carry, and lets you change it", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(DATE);
    const { container } = show();
    await loaded();

    // 90 daily buckets is under the 120 a panel this wide can draw, so day is
    // the natural choice. Switching is **display only**: every grain arrived
    // in one bundle under one `computation_id`.
    expect(container.querySelectorAll(".figure .histogram .bar")).toHaveLength(90);
    expect(screen.getByRole("button", { name: "day" })).toHaveAttribute("data-on", "true");

    await userEvent.setup().click(screen.getByRole("button", { name: "month" }));
    expect(container.querySelectorAll(".figure .histogram .bar")).toHaveLength(3);
  });

  it("draws the whole of a cycle, and no hours when there are none", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(DATE);
    const { container } = show();
    await loaded();

    // Seven and twelve whatever the data does — *nothing on Sunday* is a
    // finding, and a chart of six bars is a chart that lost one.
    const cycles = [...container.querySelectorAll(".cycle")];
    expect(cycles).toHaveLength(2);
    expect(cycles[0]?.querySelectorAll(".stem")).toHaveLength(7);
    expect(cycles[1]?.querySelectorAll(".stem")).toHaveLength(12);
    expect(screen.getByText("day of week")).toBeInTheDocument();
    // Not `by month`: the timeline above has a month grain that means
    // something else entirely.
    expect(screen.getByText("month of year")).toBeInTheDocument();
    expect(screen.queryByText("hour of day")).not.toBeInTheDocument();
  });

  it("lays the span out as a calendar, Monday first", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(DATE);
    const { container } = show();
    await loaded();

    // 2023-01-01 is a Sunday. Monday leads the grid, so that day takes row 7
    // of column 1 and the six cells above it are simply absent: the span does
    // not cover them, and drawing them would invent days.
    const cells = [...container.querySelectorAll<HTMLElement>(".cal-grid span")];
    expect(cells).toHaveLength(90);
    expect(cells[0]?.dataset.day).toBe("2023-01-01");
    expect(cells[0]?.style.gridRow).toBe("7");
    expect(cells[0]?.style.gridColumn).toBe("1");
    // The next day is a Monday, so it opens column 2.
    expect(cells[1]?.style.gridRow).toBe("1");
    expect(cells[1]?.style.gridColumn).toBe("2");
  });

  it("draws the empty days rather than leaving holes", async () => {
    // The finding this figure exists for. A day inside the span holding
    // nothing, rendered as nothing, reads as the edge of the data instead of
    // as a hole in it.
    const quiet = DATE.date!.by_day.map((day, index) => ({ ...day, count: index < 10 ? 0 : 1 }));
    vi.spyOn(api, "columnProfile").mockResolvedValue({
      ...DATE,
      date: { ...DATE.date!, by_day: quiet },
    });
    const { container } = show();
    await loaded();

    expect(container.querySelectorAll(".cal-grid span")).toHaveLength(90);
    expect(container.querySelectorAll('.cal-grid span[data-level="0"]')).toHaveLength(10);
  });

  it("gives every month label its own week columns, summing to the grid", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(DATE);
    const { container } = show();
    await loaded();

    // Labels are placed by `span`, not by arithmetic that has to agree with
    // the grid's gaps. The spans have to add up to the column count or the
    // strip drifts out of line with the cells above it.
    const months = [...container.querySelectorAll<HTMLElement>(".cal-months span")];
    const spans = months.map((month) => Number(month.style.gridColumn.replace("span ", "")));
    const columns = [...container.querySelectorAll<HTMLElement>(".cal-grid span")].reduce(
      (widest, cell) => Math.max(widest, Number(cell.style.gridColumn)),
      0,
    );
    expect(spans.reduce((sum, span) => sum + span, 0)).toBe(columns);
    expect(months.map((month) => month.textContent).filter(Boolean)).toEqual(["Jan", "Feb", "Mar"]);
  });

  it("turns the parsed count red when the column is only partly readable", async () => {
    // The trap: a column forced to `date` whose values are `07/03/2024` draws a
    // real range built from whatever fraction happened to be ISO, with nothing
    // on screen saying so. `conforming` was in the bundle and no panel read it.
    vi.spyOn(api, "columnProfile").mockResolvedValue({
      ...DATE,
      date: { ...DATE.date!, conforming: 400 },
    });
    const { container } = show();
    await loaded();

    const alarm = container.querySelector(".cell[data-alarm]");
    expect(alarm).not.toBeNull();
    expect(alarm).toHaveTextContent("400 of 1,200");
  });
});

describe("the boolean panel (D-066)", () => {
  afterEach(() => vi.restoreAllMocks());

  const BOOLEAN: ColumnDetail = {
    ...BASE,
    logical_type: "boolean",
    numeric: null,
    boolean: { true_count: 502, false_count: 698, other_count: 0 },
    completeness: { ...BASE.completeness, total: 1200, present: 1200, zeros: null, negatives: null },
    presence: { rows_per_slot: 5, slots: [{ rows: 5, present: 5 }] },
  };

  it("is a strip, a table of classes, and a ring", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BOOLEAN);
    const { container } = show();
    await loaded();

    // D-066 left this at a strip and a ring, on the argument that a two-row
    // table is the same pair of counts at greater length. True of the *ring*,
    // false of a reader who is not hovering it — the exact figures existed only
    // under a pointer, and D-067 put them back where they can be read.
    expect(container.querySelector(".presence")).not.toBeNull();
    expect(container.querySelectorAll(".donut .slice")).toHaveLength(2);
    expect(container.querySelectorAll(".freq tbody tr")).toHaveLength(2);
    expect(screen.getByText("502")).toBeInTheDocument();
    expect(screen.getByText("41.8%")).toBeInTheDocument();

    // No concentration curve: two ranks say nothing a two-row table does not.
    expect(container.querySelector(".curve")).toBeNull();
    expect(screen.queryByText("Completeness")).not.toBeInTheDocument();
    expect(screen.queryByText(BOOLEAN.narrative)).not.toBeInTheDocument();
  });

  it("colours true and leaves false neutral", async () => {
    vi.spyOn(api, "columnProfile").mockResolvedValue(BOOLEAN);
    const { container } = show();
    await loaded();

    // A ring where both arcs are coloured makes a reader decide which colour
    // means which. One coloured arc against a neutral one reads as *this much
    // of it is true* without a legend — so `false` takes `rest`, the same tone
    // the categorical remainder uses.
    const slices = [...container.querySelectorAll<HTMLElement>(".donut .slice")];
    expect(slices[0]?.dataset.tone).toBeUndefined();
    expect(slices[0]?.style.getPropertyValue("--step")).toBe("1");
    expect(slices[1]?.dataset.tone).toBe("rest");
  });

  it("draws neither as a third arc rather than leaving a gap", async () => {
    // §11.8.4's rule for numbers that do not parse, applied to words that are
    // neither true nor false. Leaving it out would not merely omit it: the two
    // remaining arcs would not close the circle.
    vi.spyOn(api, "columnProfile").mockResolvedValue({
      ...BOOLEAN,
      boolean: { true_count: 500, false_count: 600, other_count: 100 },
    });
    const { container } = show();
    await loaded();

    const slices = [...container.querySelectorAll<HTMLElement>(".donut .slice")];
    expect(slices).toHaveLength(3);
    expect(slices[2]?.dataset.tone).toBe("other");
  });
});

describe("F(x), off the sampled curve", () => {
  // A step: a fifth of the column sits at exactly 10, which in the quantile
  // function shows up as the same value repeated across a run of the grid.
  const CURVE = [
    { p: 0, value: 0 },
    { p: 0.2, value: 10 },
    { p: 0.4, value: 10 },
    { p: 0.6, value: 30 },
    { p: 1, value: 100 },
  ];

  it("is zero below the smallest value and one above the largest", () => {
    expect(shareAtOrBelow(CURVE, -5)).toBe(0);
    expect(shareAtOrBelow(CURVE, 1000)).toBe(1);
  });

  it("resolves a step upward, because that is what F(x) means", () => {
    // *"How much of the column is at or below 10"* is the **top** of the step,
    // not somewhere inside it — 40%, not 20%. This is why the scan looks for
    // the last index at or below x rather than the first.
    expect(shareAtOrBelow(CURVE, 10)).toBeCloseTo(0.4, 10);
  });

  it("interpolates between two sampled points", () => {
    // Halfway from 30 to 100 in value is halfway from 0.6 to 1.0 in
    // proportion — the same straight line the curve is drawn as.
    expect(shareAtOrBelow(CURVE, 65)).toBeCloseTo(0.8, 10);
    expect(shareAtOrBelow(CURVE, 30)).toBeCloseTo(0.6, 10);
  });
});
