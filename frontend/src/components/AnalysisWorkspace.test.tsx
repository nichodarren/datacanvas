import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisWorkspace } from "@/components/AnalysisWorkspace";
import { ApiError, api, type History, type Turn, type TurnSummary } from "@/lib/api";

/**
 * The full-screen workspace.
 *
 * The layout is geometry and jsdom has no layout engine, so what is checked
 * here is what the surface **claims** and how its three zones stay connected:
 * the log is an index into the canvas, and an entry that could not select its
 * own answer would make it a list of things you can no longer reach.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, ask: vi.fn(), history: vi.fn(), forget: vi.fn() },
  };
});

function turn(over: Partial<TurnSummary> = {}): TurnSummary {
  return {
    id: "t-1",
    asked_at: "2026-08-28T01:00:00Z",
    question: "how many rows are there?",
    narrative: "The dataset holds 891 rows [ref: comp-1].",
    grounded: true,
    stopped: null,
    steps: [
      { ref: "comp-1", tool: "describe_dataset", args: {}, output_kind: "column_cards" },
    ],
    complaints: [],
    provider: "gemini",
    model: "gemini-3.5-flash-lite",
    ...over,
  };
}

const ANSWERED: Turn = {
  narrative: "The dataset holds 891 rows [ref: comp-1].",
  grounded: true,
  steps: [
      { ref: "comp-1", tool: "describe_dataset", args: {}, output_kind: "column_cards" },
    ],
  complaints: [],
  stopped: null,
  rejections: [],
  categories: [],
  tokens: 0,
  privacy_mode: "balanced",
  provider: "gemini",
  model: "gemini-3.5-flash-lite",
};

function log(...turns: TurnSummary[]): History {
  return { turns };
}

beforeEach(() => {
  vi.mocked(api.ask).mockReset();
  vi.mocked(api.history).mockReset();
  vi.mocked(api.history).mockResolvedValue(log());
});

const open = () =>
  render(<AnalysisWorkspace datasetId="dataset-1" datasetName="titanic" />);

const field = () => screen.getByRole("textbox", { name: /ask a question/i });

/**
 * The log, scoped.
 *
 * A question appears twice on this surface — as a log entry and as the heading
 * of the answer it opens — and that is the connection working rather than a
 * duplication. So a test about the log has to say it means the log.
 */
const entries = () => screen.getByRole("list", { name: /questions asked/i });

/**
 * One entry of the log, by the question it holds.
 *
 * Scoped, because a question is deliberately in two places: the log lists it
 * and the panel's own header carries it, so that a collapsed panel says what
 * it is hiding rather than showing two dots. That is the connection working —
 * and it means a test has to say which of the two it means.
 */
/**
 * One log entry, told apart from the delete beside it.
 *
 * Every row now holds two buttons and the second is labelled `Forget “…”`,
 * which contains the question — good for a screen reader reading a list of
 * sixteen, ambiguous for a query matching on the question alone. The row's own
 * button is the one whose name does *not* announce what it removes.
 */
const entry = (text: RegExp) =>
  within(entries()).getByRole("button", {
    name: (accessible: string) => text.test(accessible) && !accessible.startsWith("Forget"),
  });

/** The delete beside an entry. */
const forget = (text: RegExp) =>
  within(entries()).getByRole("button", {
    name: (accessible: string) => accessible.startsWith("Forget") && text.test(accessible),
  });

/** Wait for the log to arrive before reaching into it. */
const logged = () => screen.findByRole("list", { name: /questions asked/i });

/** The answer card. Named, because the question it holds is also in the log. */
const panel = () => screen.getByRole("region", { name: /^answer$/i });

describe("arriving", () => {
  it("says so honestly when nothing has been asked", async () => {
    open();

    expect(
      await screen.findByText(/Questions you ask about this dataset are kept here/i),
    ).toBeInTheDocument();
    // And no count, because zero is what the sentence above already says.
    // A `0` beside the label would be a second way of saying nothing.
    expect(
      within(screen.getByRole("button", { name: /agent log/i })).queryByText("0"),
    ).not.toBeInTheDocument();
  });

  it("shows the newest answer without being asked to", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({ id: "new", question: "the newest one", narrative: "Newest." }),
        turn({ id: "old", question: "the oldest one", narrative: "Oldest." }),
      ),
    );
    open();

    // Newest first from the server, so the head is the last thing asked — and
    // that is what somebody arriving is looking at.
    expect(await screen.findByText("Newest.")).toBeInTheDocument();
    expect(screen.queryByText("Oldest.")).not.toBeInTheDocument();
  });

  it("promises nothing about the canvas that it cannot keep", async () => {
    open();

    // §14.5, and D-081: twenty-eight dashed placeholder slots were built here
    // and removed, because an outline that will never fill is a promise the
    // screen cannot keep. A sentence can be honest; an empty card cannot.
    const canvas = await screen.findByRole("main", { name: /results/i });
    expect(within(canvas).getByText(/Results appear here/i)).toBeInTheDocument();
    expect(canvas.querySelectorAll("article")).toHaveLength(0);
  });


  it("collapses even with nothing in it", async () => {
    open();

    // The head used to appear only once there was an answer, so an empty
    // panel could not be closed and the card grew a new control the moment a
    // question was asked. A card that changes shape halfway through is one
    // you have to re-learn.
    const head = await screen.findByRole("button", { name: /answer/i });
    expect(head).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(head);

    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Every figure in the answer/i)).not.toBeInTheDocument();
  });

  it("keeps the question visible while collapsed, so the card says what it hides", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(turn({ question: "how many rows are there?", narrative: "891." })),
    );
    open();

    await logged();
    const head = within(panel()).getByRole("button", { name: /how many rows/i });
    await userEvent.click(head);

    expect(screen.queryByText("891.")).not.toBeInTheDocument();
    expect(head).toHaveTextContent(/how many rows are there/i);
  });
});

describe("the agent log", () => {
  it("lists every question asked of this dataset", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(turn({ id: "a", question: "first" }), turn({ id: "b", question: "second" })),
    );
    open();

    await screen.findByRole("list", { name: /questions asked/i });
    expect(within(entries()).getByText("first")).toBeInTheDocument();
    expect(within(entries()).getByText("second")).toBeInTheDocument();
    // The count sits on the log's own header, not in the far corner of the
    // window: a number is read next to the thing it is about.
    expect(screen.getByRole("button", { name: /agent log/i })).toHaveTextContent("2");
  });

  it("opens the answer belonging to the entry that was clicked", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({ id: "a", question: "first", narrative: "First answer." }),
        turn({ id: "b", question: "second", narrative: "Second answer." }),
      ),
    );
    open();

    // The whole reason the log carries its own turn: an entry is a handle on
    // its own results, not a note that something once happened.
    await logged();
    await userEvent.click(entry(/second/));

    expect(await screen.findByText("Second answer.")).toBeInTheDocument();
    expect(screen.queryByText("First answer.")).not.toBeInTheDocument();
  });

  it("says which entry the panel is showing, and says it to a screen reader", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(turn({ id: "a", question: "first" }), turn({ id: "b", question: "second" })),
    );
    open();

    await logged();
    expect(entry(/first/)).toHaveAttribute("aria-current", "true");
    expect(entry(/second/)).toHaveAttribute("aria-current", "false");
  });

  it("marks an unverified answer, and never by colour alone", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({ id: "bad", question: "a doubtful one", grounded: false }),
        turn({ id: "good", question: "a solid one", grounded: true }),
      ),
    );
    open();

    // NFR-UX.3: a label a screen reader can read, not a colour an eye must
    // catch. And on **one** of the two entries — a mark on every row is
    // furniture rather than a warning.
    //
    // Scoped to the log, because the panel's own header carries the same
    // marker for whichever answer it is showing. Two marks for one turn is
    // the surface agreeing with itself, not a duplication.
    await logged();
    expect(within(entries()).getAllByLabelText(/not verified/i)).toHaveLength(1);
    expect(within(entries()).getAllByLabelText(/verified/i)).toHaveLength(2);
  });

  it("collapses, and says whether it is open", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn({ question: "kept" })));
    open();

    const head = await screen.findByRole("button", { name: /agent log/i });
    expect(head).toHaveAttribute("aria-expanded", "true");
    expect(entries()).toBeInTheDocument();

    await userEvent.click(head);

    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("list", { name: /questions asked/i }),
    ).not.toBeInTheDocument();
    // The answer stays: collapsing the index does not close what it opened.
    expect(screen.getByText(/The dataset holds 891 rows/)).toBeInTheDocument();
  });
});

describe("asking", () => {
  it("will not send an empty question", async () => {
    open();

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await userEvent.type(field(), "   ");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("names the question in flight, because a turn is seconds not milliseconds", async () => {
    let release: (value: Turn) => void = () => {};
    vi.mocked(api.ask).mockReturnValue(
      new Promise<Turn>((resolve) => {
        release = resolve;
      }),
    );
    open();

    await userEvent.type(field(), "how many rows are there?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /how many rows are there/i,
    );
    release(ANSWERED);
  });

  it("reads the log back from the server rather than trusting the browser", async () => {
    vi.mocked(api.ask).mockResolvedValue(ANSWERED);
    vi.mocked(api.history)
      .mockResolvedValueOnce(log())
      .mockResolvedValueOnce(log(turn({ id: "fresh", question: "how many rows are there?" })));
    open();

    await userEvent.type(field(), "how many rows are there?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // `/ask` answers without an id or a timestamp, so a log assembled here
    // would disagree with the server's the moment anything reloads.
    await waitFor(() => expect(api.history).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /agent log/i })).toHaveTextContent("1"),
    );
  });

  it("shows the new answer rather than leaving the old one selected", async () => {
    vi.mocked(api.ask).mockResolvedValue(ANSWERED);
    vi.mocked(api.history)
      .mockResolvedValueOnce(log(turn({ id: "old", question: "older", narrative: "Old." })))
      .mockResolvedValueOnce(
        log(
          turn({ id: "new", question: "newer", narrative: "New." }),
          turn({ id: "old", question: "older", narrative: "Old." }),
        ),
      );
    open();

    await screen.findByText("Old.");
    await userEvent.type(field(), "newer");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("New.")).toBeInTheDocument();
  });

  it("keeps the entry the reader chose when the log reloads for another reason", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({ id: "a", question: "first", narrative: "First answer." }),
        turn({ id: "b", question: "second", narrative: "Second answer." }),
      ),
    );
    open();

    await logged();
    await userEvent.click(entry(/second/));
    expect(await screen.findByText("Second answer.")).toBeInTheDocument();

    // Losing it would move the panel out from under somebody mid-sentence.
    expect(entry(/second/)).toHaveAttribute("aria-current", "true");
  });
});

describe("what it shows about an answer", () => {
  it("flags an unverified answer rather than hiding it", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({
          grounded: false,
          narrative: "The rate is 35.7% [ref: comp-1].",
          complaints: [{ kind: "unsupported-number", detail: "35.7 is not in the result" }],
        }),
      ),
    );
    open();

    // §12.5 rule 3. A confident sentence with nothing behind it is worse than
    // no sentence, because reading it gives no way to tell.
    expect(await screen.findByText(/The rate is 35.7%/)).toBeInTheDocument();
    expect(screen.getByText(/Not verified/i)).toBeInTheDocument();
    expect(screen.getByText(/35.7 is not in the result/)).toBeInTheDocument();
  });

  it("names the tools an answer came from, and not their ids", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({
          steps: [
            {
              ref: "comp-1",
              tool: "aggregate",
              args: { group_by: "Pclass", measures: "mean(Fare)" },
              // Not a drawn kind: this test is about the receipt, and a card
              // would put the same tool name on screen twice.
              output_kind: "column_cards",
            },
          ],
        }),
      ),
    );
    open();

    // D-099. The receipt answers *why is the number what it is*, which a tool
    // and its arguments say and a UUID does not.
    const chip = await screen.findByRole("button", { name: "aggregate" });
    expect(screen.queryByText("comp-1")).not.toBeInTheDocument();

    // The arguments are a hover away, in a popup positioned from the viewport
    // so the scroller it lives in cannot clip it.
    expect(screen.queryByText(/group_by=Pclass/)).not.toBeInTheDocument();
    await userEvent.hover(chip);
    expect(
      await screen.findByText(/group_by=Pclass · measures=mean\(Fare\)/),
    ).toBeInTheDocument();

    // And reachable without a mouse, which is also how a tap reaches it.
    await userEvent.unhover(chip);
    expect(screen.queryByText(/group_by=Pclass/)).not.toBeInTheDocument();
    chip.focus();
    expect(
      await screen.findByText(/group_by=Pclass · measures=mean\(Fare\)/),
    ).toBeInTheDocument();
  });

  it("keeps the citation out of the sentence it was written into", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn()));
    open();

    // The model still writes `[ref: …]` and step 10 still validates against
    // it — stripping happens on the way to the screen and nowhere earlier,
    // because a prompt that stopped asking for citations would retire §12.5
    // rule 2 along with them.
    expect(await screen.findByText("The dataset holds 891 rows.")).toBeInTheDocument();
  });

  it("says the question once when the head can hold it", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn({ question: "short one" })));
    open();

    // The head carries the question already — that is what makes the collapsed
    // card meaningful — so repeating it below would be two copies of one
    // sentence a centimetre apart. The log's own entry is the second copy and
    // belongs to a different card.
    await screen.findByRole("button", { name: /show more/i }).catch(() => null);
    const panel = screen.getByRole("region", { name: "Answer" });
    expect(within(panel).getAllByText("short one")).toHaveLength(1);
  });

  it("repeats it in full only when the head had to cut it", async () => {
    // jsdom reports no layout, so the measurement has to be given one. This is
    // the branch that matters: without it the block either never appears or
    // always does, and both were shipped at some point.
    const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get: () => 999,
    });
    try {
      const long =
        "plot the average fare per passenger class but only for the passengers " +
        "who embarked at Southampton and were travelling with at least one sibling";
      vi.mocked(api.history).mockResolvedValue(log(turn({ question: long })));
      open();

      const panel = await screen.findByRole("region", { name: "Answer" });
      await waitFor(() => expect(within(panel).getAllByText(long)).toHaveLength(2));
    } finally {
      if (width) Object.defineProperty(HTMLElement.prototype, "scrollWidth", width);
      else Reflect.deleteProperty(HTMLElement.prototype, "scrollWidth");
    }
  });

  it("names the model that wrote the answer, not the account that paid", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn({ provider: "gemini#2" })));
    open();

    // `gemini#2` says which of three keys was billed, which matters to §12.8
    // and to nobody reading an answer. The model is what shaped the sentence,
    // and it is the question asked first when one looks wrong.
    expect(await screen.findByText("gemini-3.5-flash-lite")).toBeInTheDocument();
    expect(screen.queryByText(/gemini#2/)).not.toBeInTheDocument();
  });

  it("says nothing at all when no model was recorded", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn({ model: "" })));
    open();

    // Every turn stored before this existed has an empty string, and `via`
    // followed by nothing reads as a bug rather than as an older row.
    await screen.findByText(/The dataset holds 891 rows/);
    expect(screen.queryByText(/^via$/i)).not.toBeInTheDocument();
  });

  it("draws the chart and not the step it was drawn from", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(
        turn({
          steps: [
            { ref: "comp-1", tool: "bin_column", args: { column: "amount" }, output_kind: "table" },
            {
              ref: "comp-2",
              tool: "plot",
              args: { table: "comp-1", mark: "bar" },
              output_kind: "chart_spec",
            },
          ],
        }),
      ),
    );
    open();

    // Drawing both puts the bands beside a picture of the bands: the same
    // fact twice, with the intermediate taking the wider card.
    const canvas = await screen.findByRole("main", { name: /results/i });
    expect(within(canvas).getByText("plot")).toBeInTheDocument();
    expect(within(canvas).queryByText("bin_column")).not.toBeInTheDocument();

    // But the receipt still names it. Hiding a step from the canvas is a
    // layout decision; hiding it from the provenance would be a worse one.
    expect(screen.getByText("bin_column")).toBeInTheDocument();
  });

  it("forgets one question from the log, and reads the log back", async () => {
    const two = [turn({ id: "t-1", question: "first" }), turn({ id: "t-2", question: "second" })];
    vi.mocked(api.history).mockResolvedValue({ turns: two });
    vi.mocked(api.forget).mockResolvedValue(undefined);
    open();
    await logged();

    await userEvent.click(forget(/second/));

    // NFR-PRIV.3: the sentence a person typed has to be removable.
    expect(api.forget).toHaveBeenCalledWith("dataset-1", "t-2");
    // Read back rather than spliced out of local state: the server is what the
    // log is, and a list that diverges from it after a failed delete lies.
    expect(api.history).toHaveBeenCalledTimes(2);
  });

  it("keeps the log honest when forgetting fails", async () => {
    vi.mocked(api.history).mockResolvedValue(log(turn({ question: "first" })));
    vi.mocked(api.forget).mockRejectedValue(new ApiError(0, "offline"));
    open();
    await logged();

    await userEvent.click(forget(/first/));

    expect(await screen.findByText(/Could not reach the server/i)).toBeInTheDocument();
    // One read, from mounting. Nothing was removed, so nothing is re-read.
    expect(api.history).toHaveBeenCalledTimes(1);
  });

  it("selects a turn when its group is clicked, not only its question", async () => {
    const two = [turn({ id: "t-1", question: "first" }), turn({ id: "t-2", question: "second" })];
    vi.mocked(api.history).mockResolvedValue({ turns: two });
    open();
    await logged();

    // Newest first from the server, so `first` is selected on arrival.
    expect(entry(/first/)).toHaveAttribute("aria-current", "true");

    const canvas = await screen.findByRole("main", { name: /results/i });
    const group = canvas.querySelector('[data-turn="t-2"]');
    await userEvent.click(group as HTMLElement);

    expect(entry(/second/)).toHaveAttribute("aria-current", "true");
  });

  it("says what stopped a turn that never answered", async () => {
    vi.mocked(api.history).mockResolvedValue(
      log(turn({ narrative: null, grounded: false, stopped: "reached 6 steps without an answer" })),
    );
    open();

    // P6: a question that could not be answered is the most useful kind to
    // read back, so the row is kept and the reason is shown — **in both
    // places**, because the panel says why the answer is missing and the
    // canvas says why the space where its cards would be is empty (§14.5).
    const said = await screen.findAllByText(/reached 6 steps without an answer/i);
    expect(said).toHaveLength(2);
  });
});
