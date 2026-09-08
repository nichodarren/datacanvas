import { describe, expect, it } from "vitest";

import { describeArgs, resultsOf, withoutCitations } from "@/lib/citations";

/**
 * D-099: the ids stay on the wire and leave the screen.
 *
 * What is under test is the **line between them**. The model still writes
 * `[ref: …]` and the backend still validates against it; these are the rules
 * for what a person is shown, and the sharp edge is over-stripping — deleting
 * something from an answer because it was shaped like an id.
 */

describe("citations in a narration", () => {
  const known = new Set(["comp-1", "bca9d582-0ece-434b-9c71-93b23bc6fcf1"]);

  it("removes the span and the space before it", () => {
    // Not just the brackets: `rows [ref: comp-1].` left as `rows .` would
    // trade a UUID for a typo.
    expect(withoutCitations("The dataset holds 891 rows [ref: comp-1].", known)).toBe(
      "The dataset holds 891 rows.",
    );
  });

  it("removes every span, not only the first", () => {
    expect(
      withoutCitations("It holds 891 rows [ref: comp-1] and 12 columns [ref: comp-1].", known),
    ).toBe("It holds 891 rows and 12 columns.");
  });

  it("removes the bare form models write anyway", () => {
    // The backend reads this form too, so leaving it would put back exactly
    // what the rest of this module takes away.
    expect(withoutCitations("The mean fare is 84.15 [comp-1].", known)).toBe(
      "The mean fare is 84.15.",
    );
  });

  it("leaves bracketed prose that is not an id", () => {
    // The guard that matters. `[see above]` is four characters or more and
    // matches the shape; only the lookup tells it apart from a citation, and
    // without the lookup this function edits sentences.
    const text = "The column [see above] holds 891 values.";
    expect(withoutCitations(text, known)).toBe(text);
  });

  it("leaves a sentence that never cited anything", () => {
    expect(withoutCitations("The chart shows three bars.", known)).toBe(
      "The chart shows three bars.",
    );
  });
});

describe("a step's arguments", () => {
  const AGGREGATE = { ref: "bca9d582-0ece-434b-9c71-93b23bc6fcf1", tool: "aggregate" };
  const steps = [AGGREGATE, { ref: "cd97c7d6-8f99-4f36-ad48-7bc46d2bf785", tool: "plot" }];

  it("names the step an argument points at", () => {
    // The half that removing the receipt's own id column does not reach: this
    // id lives *inside* the arguments, which are the part being kept.
    expect(
      describeArgs(
        { x: "Pclass", y: "mean_Fare", mark: "bar", table: AGGREGATE.ref },
        steps,
      ),
    ).toBe("x=Pclass · y=mean_Fare · mark=bar · table=aggregate");
  });

  it("tells two runs of one tool apart, and only then", () => {
    const twice = [
      { ref: "a-1", tool: "aggregate" },
      { ref: "a-2", tool: "aggregate" },
    ];
    expect(describeArgs({ table: "a-1" }, twice)).toBe("table=aggregate #1");
    expect(describeArgs({ table: "a-2" }, twice)).toBe("table=aggregate #2");
    // One aggregate needs no ordinal: `#1` alone is a number to ignore.
    expect(describeArgs({ table: AGGREGATE.ref }, steps)).toBe("table=aggregate");
  });

  it("leaves a value that is not a reference alone", () => {
    expect(describeArgs({ table: "dataset", column: "Fare" }, steps)).toBe(
      "table=dataset · column=Fare",
    );
  });

  it("keeps an argument sitting at its default", () => {
    // §9.4 hashes arguments into a computation's identity, so a threshold the
    // model never typed still decided the answer. Hiding it would make two
    // different results look like the same one.
    expect(describeArgs({ mark: "bar", transform: "none" }, steps)).toBe(
      "mark=bar · transform=none",
    );
  });

  it("drops an argument that was never set", () => {
    expect(describeArgs({ x: "Pclass", y: null, color: "" }, steps)).toBe("x=Pclass");
  });
});

describe("what a turn produced", () => {
  const bins = { ref: "comp-1", tool: "bin_column", args: { column: "amount", n_bins: 10 } };
  const chart = { ref: "comp-2", tool: "plot", args: { table: "comp-1", mark: "bar" } };

  it("keeps the chart and drops the step it was drawn from", () => {
    // Knowable exactly rather than by heuristic: `plot` names `comp-1`.
    expect(resultsOf([bins, chart]).map((s) => s.tool)).toEqual(["plot"]);
  });

  it("keeps a result that nothing read, wherever it sits", () => {
    // *The last step* is the tempting shortcut and it is wrong: a turn that
    // reports and then charts has two results, and keeping only the last
    // would drop the report.
    const report = { ref: "comp-0", tool: "missingness_report", args: {} };
    expect(resultsOf([report, bins, chart]).map((s) => s.tool)).toEqual([
      "missingness_report",
      "plot",
    ]);
  });

  it("keeps an intermediate when the turn stopped before anything read it", () => {
    // A rate limit on the call that would have plotted leaves the bands as
    // the only thing there is. You get to see what you got.
    expect(resultsOf([bins]).map((s) => s.tool)).toEqual(["bin_column"]);
  });

  it("does not let an ordinary argument consume anything", () => {
    // `table: "dataset"` is not a reference, and neither is `mark: "bar"`.
    const alone = { ref: "comp-3", tool: "plot", args: { table: "dataset", mark: "bar" } };
    expect(resultsOf([alone])).toHaveLength(1);
  });

  it("keeps two charts drawn from one step", () => {
    const second = { ref: "comp-3", tool: "plot", args: { table: "comp-1", mark: "line" } };
    expect(resultsOf([bins, chart, second]).map((s) => s.ref)).toEqual(["comp-2", "comp-3"]);
  });
});
