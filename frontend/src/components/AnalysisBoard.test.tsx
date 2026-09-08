import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisBoard } from "@/components/AnalysisBoard";
import { ApiError, type Turn, type TurnSummary, api } from "@/lib/api";

/**
 * The Analysis tab, now that it runs.
 *
 * Most of what matters about the layout is geometry, and jsdom has no layout
 * engine — the composer sticking and the answer block's rhythm were checked in
 * Chrome against the real stylesheet. What is left is what the surface
 * *claims*, and that is the part with rules attached to it.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, ask: vi.fn(), history: vi.fn(), artifact: vi.fn() },
  };
});

const GROUNDED: Turn = {
  narrative: "The mean rating is 3.0175 [ref: comp-1].",
  grounded: true,
  steps: [
    {
      ref: "comp-1",
      tool: "profile_column",
      args: { column: "rating" },
      output_kind: "stat_panel",
    },
  ],
  complaints: [],
  stopped: null,
  rejections: [],
  categories: ["profiling"],
  tokens: 986,
  privacy_mode: "balanced",
  provider: "gemini",
  model: "gemini-3.5-flash-lite",
};

/** One entry as the history route returns it. */
function logged(over: Partial<TurnSummary> = {}): { turns: TurnSummary[] } {
  return {
    turns: [
      {
        id: "t-1",
        asked_at: "2026-08-28T01:00:00Z",
        question: "what is the mean rating?",
        narrative: "The mean rating is 3.0175.",
        grounded: true,
        stopped: null,
        steps: [
          {
            ref: "comp-1",
            tool: "aggregate",
            args: { group_by: "rating" },
            output_kind: "table",
          },
          {
            ref: "comp-2",
            tool: "plot",
            args: { table: "comp-1", mark: "bar" },
            output_kind: "chart_spec",
          },
        ],
        complaints: [],
        provider: "gemini",
        model: "gemini-3.5-flash-lite",
        ...over,
      },
    ],
  };
}

beforeEach(() => {
  vi.mocked(api.ask).mockReset();
  vi.mocked(api.history).mockReset().mockResolvedValue({ turns: [] });
  vi.mocked(api.artifact).mockReset().mockResolvedValue({
    ref: "comp-2",
    tool: "plot",
    tool_version: 3,
    output_kind: "chart_spec",
    result: {},
  });
});

const board = () => render(<AnalysisBoard datasetId="dataset-1" />);
const field = () => screen.getByRole("textbox", { name: /ask a question/i });

describe("the analysis surface", () => {
  it("has one door, and it is the prompt", () => {
    board();

    // This asserted the opposite until D-049. It held **INV-1** — every Step
    // the copilot creates must also be creatable manually — and **P2**, that
    // the product is useful without AI. Both were revoked at the owner's
    // direction, so the assertion is inverted rather than deleted: a test that
    // simply disappears leaves nothing saying the second door was a decision
    // rather than an oversight.
    expect(field()).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a step" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("will not send an empty question", async () => {
    board();

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await userEvent.type(field(), "   ");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("asks, and puts what the tools drew on the board", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    vi.mocked(api.history).mockResolvedValue(logged());
    board();

    await userEvent.type(field(), "what is the mean rating?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(vi.mocked(api.ask)).toHaveBeenCalledWith("dataset-1", "what is the mean rating?");
    // The chart, and not the step it was drawn from: `resultsOf` keeps what
    // nothing else read, the same rule the canvas follows.
    expect(await screen.findByText("plot")).toBeInTheDocument();
    expect(screen.queryByText("aggregate")).not.toBeInTheDocument();
  });

  it("reads the board back from the server rather than from the last answer", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    vi.mocked(api.history).mockResolvedValue(logged());
    board();

    await userEvent.type(field(), "mean?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // Two surfaces that each remember their own half of a conversation
    // disagree the first time one of them is reloaded. Once on mount, once
    // after the ask.
    await waitFor(() => expect(vi.mocked(api.history)).toHaveBeenCalledTimes(2));
  });

  it("says which kind of nothing it is when a question draws nothing", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    vi.mocked(api.history).mockResolvedValue(
      logged({ narrative: null, grounded: false, steps: [], stopped: "every provider was unavailable" }),
    );
    board();

    await userEvent.type(field(), "mean?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // §14.5 and P6. Without this the busy line vanishes and nothing replaces
    // it, which reads exactly like never having asked.
    expect(await screen.findByText("every provider was unavailable")).toBeInTheDocument();
  });

  it("points at the workspace when the answer was words rather than a chart", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    vi.mocked(api.history).mockResolvedValue(
      logged({
        steps: [
          {
            ref: "comp-1",
            tool: "profile_column",
            args: { column: "rating" },
            output_kind: "stat_panel",
          },
        ],
      }),
    );
    board();

    await userEvent.type(field(), "profile rating");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // `stat_panel` is a dead end by design (§11.4.1), so the board draws
    // nothing — and says so rather than looking like a failure.
    expect(await screen.findByText(/full-screen workspace/i)).toBeInTheDocument();
  });

  it("names the question that is in flight", async () => {
    // A turn is up to seven model calls, so this is seconds. By the time the
    // answer lands the field has cleared from the reader's mind, and a bare
    // spinner does not put it back.
    let release: (turn: Turn) => void = () => {};
    vi.mocked(api.ask).mockReturnValue(
      new Promise<Turn>((resolve) => {
        release = resolve;
      }),
    );
    board();

    await userEvent.type(field(), "how is age spread out?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("status")).toHaveTextContent("how is age spread out?");
    release(GROUNDED);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });

  it("sends on Enter and takes a newline on Shift+Enter", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    board();

    await userEvent.type(field(), "one{Shift>}{Enter}{/Shift}two");
    expect(vi.mocked(api.ask)).not.toHaveBeenCalled();
    expect(field()).toHaveValue("one\ntwo");

    await userEvent.type(field(), "{Enter}");
    await waitFor(() => expect(vi.mocked(api.ask)).toHaveBeenCalledTimes(1));
  });

  it("passes a refusal through in the server's own words", async () => {
    // An `ApiError` under 500, which is what this route answers when the
    // Parquet is missing. The API's failures are written to be read by a
    // person (P6), so the detail is shown rather than replaced with a house
    // message — and a bare `Error` is *not* shown, because an exception from
    // anywhere else has no promise about being readable.
    vi.mocked(api.ask).mockRejectedValue(
      new ApiError(409, "the data for this version is not in storage"),
    );
    board();

    await userEvent.type(field(), "mean?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the data for this version is not in storage",
    );
  });
});
