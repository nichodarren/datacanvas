import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactCard } from "@/components/ArtifactCard";
import { ApiError, api, type Artifact } from "@/lib/api";

/**
 * The card that draws a computation.
 *
 * What is under test is the **vocabulary**: a card renders from `output_kind`
 * and never from a tool's name (§11.2), which is what lets two renderers cover
 * thirteen of the seventeen tools. So each case here hands it a real bundle
 * shape and checks it drew the right thing — and, where a number could
 * mislead, that it said the thing that stops it misleading.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { ...actual.api, artifact: vi.fn() } };
});

function artifact(kind: string, result: Record<string, unknown>): Artifact {
  return {
    ref: "comp-abcdef12",
    tool: "some_tool",
    tool_version: 1,
    output_kind: kind,
    result,
  };
}

beforeEach(() => {
  vi.mocked(api.artifact).mockReset();
});

const draw = (kind: string) =>
  render(
    <ArtifactCard
      datasetId="dataset-1"
      refId="comp-abcdef12"
      tool="some_tool"
      outputKind={kind}
    />,
  );

describe("a table", () => {
  const TABLE = {
    sql: "SELECT …",
    columns: [{ name: "Pclass", logical_type: "numerical" }],
    row_count: 113,
    preview: { columns: ["Pclass", "count"], rows: [["1", "12"], ["2", "23"]] },
    note: "113 of 891 rows match; 778 were left behind",
  };

  it("draws the rows it was given", async () => {
    vi.mocked(api.artifact).mockResolvedValue(artifact("table", TABLE));
    draw("table");

    const grid = await screen.findByRole("table");
    expect(within(grid).getByRole("columnheader", { name: "Pclass" })).toBeInTheDocument();
    expect(within(grid).getByRole("cell", { name: "23" })).toBeInTheDocument();
  });

  it("says how many rows there are, not just how many it is showing", async () => {
    vi.mocked(api.artifact).mockResolvedValue(artifact("table", TABLE));
    draw("table");

    // A card that showed ten rows and said nothing would read as a result
    // with ten rows in it. The filter kept 113.
    expect(await screen.findByText(/2 of 113 rows/i)).toBeInTheDocument();
  });

  it("keeps the note the tool wrote", async () => {
    vi.mocked(api.artifact).mockResolvedValue(artifact("table", TABLE));
    draw("table");

    // `filter_rows` counts what it dropped for a reason: an aggregate over a
    // filter that matched nothing looks exactly like one that matched all.
    expect(await screen.findByText(/778 were left behind/)).toBeInTheDocument();
  });

  it("shows a null as a null rather than as an empty cell", async () => {
    vi.mocked(api.artifact).mockResolvedValue(
      artifact("table", {
        ...TABLE,
        preview: { columns: ["Cabin"], rows: [[null]] },
        row_count: 1,
      }),
    );
    draw("table");

    // A blank cell is *no value* and *a value we did not draw* at once, and
    // the whole ingest layer is built on those being different (FR-B.3).
    expect(await screen.findByText("null")).toBeInTheDocument();
  });
});

describe("a report", () => {
  it("shows the reason the tool computed, as written", async () => {
    vi.mocked(api.artifact).mockResolvedValue(
      artifact("report", {
        total_rows: 891,
        scanned: 12,
        findings: [
          { subject: "Cabin", reason: "687 of 891 values are missing (77.1%)", measures: {} },
        ],
        examples: [],
        note: "",
      }),
    );
    draw("report");

    // The prose is the tool's, not the model's — which is what makes a report
    // readable without a narration on top of it.
    expect(await screen.findByText("Cabin")).toBeInTheDocument();
    expect(screen.getByText(/687 of 891 values are missing/)).toBeInTheDocument();
  });

  it("says nothing was found rather than drawing an empty card", async () => {
    vi.mocked(api.artifact).mockResolvedValue(
      artifact("report", { total_rows: 891, scanned: 7, findings: [], examples: [], note: "" }),
    );
    draw("report");

    // *Nothing is wrong* is an answer. An empty card is indistinguishable
    // from a tool that never ran.
    expect(await screen.findByText(/Nothing to report across 7 column/i)).toBeInTheDocument();
  });
});

describe("a matrix", () => {
  const MATRIX = {
    row_column: "Sex",
    column_column: "Survived",
    normalize: "none",
    rows: ["female", "male"],
    columns: ["0", "1"],
    cells: [
      { row: "female", column: "0", count: 81, value: 81 },
      { row: "female", column: "1", count: 233, value: 233 },
      { row: "male", column: "0", count: 468, value: 468 },
      { row: "male", column: "1", count: 109, value: 109 },
    ],
    counted: 891,
    incomplete: 0,
  };

  it("rebuilds the grid from the long form it arrives in", async () => {
    vi.mocked(api.artifact).mockResolvedValue(artifact("matrix", MATRIX));
    draw("matrix");

    // The wire carries `(row, column, value)` because that is what composes
    // with `plot`. A grid is what a person reads.
    const grid = await screen.findByRole("table");
    expect(within(grid).getByRole("rowheader", { name: "female" })).toBeInTheDocument();
    expect(within(grid).getByRole("cell", { name: "233" })).toBeInTheDocument();
  });

  it("says how many rows it could not place", async () => {
    vi.mocked(api.artifact).mockResolvedValue(
      artifact("matrix", { ...MATRIX, counted: 889, incomplete: 2 }),
    );
    draw("matrix");

    // A crosstab that quietly summed to less than the table would have every
    // share computed against the wrong denominator.
    expect(await screen.findByText(/2 row\(s\) had no value/i)).toBeInTheDocument();
  });
});

describe("whatever it is handed", () => {
  it("names the tool and shows no id", async () => {
    vi.mocked(api.artifact).mockResolvedValue(
      artifact("report", { findings: [], scanned: 1, note: "" }),
    );
    const { container } = draw("report");

    // D-099. The id is still how this card fetched itself — it is simply not
    // something a reader is asked to hold.
    expect(await screen.findByText("some_tool")).toBeInTheDocument();
    expect(screen.queryByText("comp-abc")).not.toBeInTheDocument();
    expect(container.querySelector("[data-ref='comp-abcdef12']")).not.toBeNull();
  });

  it("says so when it does not know how to draw something", async () => {
    vi.mocked(api.artifact).mockResolvedValue(artifact("something_new", {}));
    draw("something_new");

    // §14.5: a card that renders nothing and says nothing is indistinguishable
    // from one that failed.
    expect(await screen.findByText(/Nothing here draws a something_new yet/i)).toBeInTheDocument();
  });

  it("says something went wrong rather than sitting on Loading forever", async () => {
    vi.mocked(api.artifact).mockRejectedValue(new ApiError(0, "offline"));
    draw("table");

    // Through `describeFailure`, so the card speaks the same language as every
    // other failure in the product (§14.5): what happened, and what to do.
    expect(await screen.findByText(/Could not reach the server/i)).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });
});
