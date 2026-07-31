import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewGrid } from "@/components/PreviewGrid";
import { type ColumnSpec, type SchemaContract, api } from "@/lib/api";

/**
 * The preview grid must show each column's own values — including after a
 * column is hidden.
 *
 * This is the test the defect was found by. `GET .../rows` answers with one
 * cell per column **in the file**, in file order; the grid renders the columns
 * the user has left **visible**. Those are two different index spaces, and the
 * first version of this component used one number for both. Hide any column but
 * the last and every column to its right silently drew its neighbour's values.
 *
 * Nothing else in the project could have caught it. The code is type-correct —
 * both sides are `(string | null)[]` — so `tsc` is satisfied, `next build`
 * succeeds, and `test_frontend_wiring.py` only asks whether `api.rows` is called
 * somewhere, not what is done with the answer.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  // `LOGICAL_TYPES` and the exported types stay real; only the network does not.
  return { ...actual, api: { ...actual.api, rows: vi.fn(), correctSchema: vi.fn() } };
});

const NAMES = ["alpha", "bravo", "charlie", "delta"] as const;

/** Values chosen so a cell drawn from the wrong column is obvious on sight. */
const ROWS: (string | null)[][] = [
  ["a1", "b1", "c1", "d1"],
  ["a2", "b2", "c2", "d2"],
];

function spec(name: string, ordinal: number): ColumnSpec {
  return {
    name,
    ordinal,
    physical_type: "VARCHAR",
    logical_type: "text",
    role: null,
    null_markers: [],
    detection_confidence: 1,
    detection_reason: "fixture",
    overridden: false,
  };
}

const CONTRACT: SchemaContract = {
  id: "contract-1",
  dataset_version_id: "version-1",
  version_no: 1,
  columns: NAMES.map((name, index) => spec(name, index)),
  created_at: "2026-01-01T00:00:00Z",
  derived_from: null,
};

function renderGrid() {
  return render(
    <PreviewGrid
      workspaceId="workspace-1"
      versionId="version-1"
      totalRows={ROWS.length}
      contract={CONTRACT}
      onContractChanged={() => {}}
    />,
  );
}

/** The visible cells of the first body row, row-number column included. */
function firstBodyRow(): (string | null)[] {
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  const body = rows[1];
  if (!body) throw new Error("the grid rendered no body rows");
  return within(body).getAllByRole("cell").map((cell) => cell.textContent);
}

async function openPicker() {
  await userEvent.setup().click(screen.getByRole("button", { name: "Columns" }));
}

/** Untick one column. The picker must already be open — it stays open. */
async function untick(name: string) {
  // Anchored at the start only: the checkbox's accessible name is its label's
  // text, the column name followed by its logical type.
  await userEvent.setup().click(screen.getByRole("checkbox", { name: new RegExp(`^${name}`) }));
}

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(api.rows).mockResolvedValue({
    columns: [...NAMES],
    rows: ROWS,
    offset: 0,
    limit: 10,
    total_rows: ROWS.length,
  });
});

describe("PreviewGrid", () => {
  it("shows every column's own values when nothing is hidden", async () => {
    renderGrid();
    await screen.findByText("a1");

    expect(firstBodyRow()).toEqual(["1", "a1", "b1", "c1", "d1"]);
  });

  it("keeps values with their own column after one is hidden", async () => {
    renderGrid();
    await screen.findByText("a1");

    await openPicker();
    await untick("bravo");

    // The defect produced ["1", "a1", "b1", "c1"] here: charlie's header over
    // bravo's value, and delta's over charlie's.
    expect(firstBodyRow()).toEqual(["1", "a1", "c1", "d1"]);
  });

  it("keeps values with their own column after several are hidden", async () => {
    renderGrid();
    await screen.findByText("a1");

    await openPicker();
    await untick("alpha");
    await untick("charlie");

    expect(firstBodyRow()).toEqual(["1", "b1", "d1"]);
  });
});

/**
 * Choosing which columns to look at is work, and on a wide file it is the only
 * way to read the thing at all (FR-D.3). Making somebody redo it on every
 * reload charges them for it every visit — the argument the home page already
 * makes for remembering the last project, applied where it costs more.
 */
describe("remembering the column choice", () => {
  it("restores what was hidden last time", async () => {
    const { unmount } = renderGrid();
    await screen.findByText("a1");
    await openPicker();
    await untick("bravo");
    expect(firstBodyRow()).toEqual(["1", "a1", "c1", "d1"]);

    unmount();
    renderGrid();
    await screen.findByText("a1");

    expect(firstBodyRow()).toEqual(["1", "a1", "c1", "d1"]);
  });

  it("keeps a different version's choice separate", async () => {
    const { unmount } = renderGrid();
    await screen.findByText("a1");
    await openPicker();
    await untick("bravo");
    unmount();

    // Column names belong to a version. Another version sharing a name must not
    // inherit a hidden set and quietly lose a column because of it.
    render(
      <PreviewGrid
        workspaceId="workspace-1"
        versionId="version-2"
        totalRows={ROWS.length}
        contract={CONTRACT}
        onContractChanged={() => {}}
      />,
    );
    await screen.findByText("a1");

    expect(firstBodyRow()).toEqual(["1", "a1", "b1", "c1", "d1"]);
  });

  it("still renders when localStorage refuses to co-operate", async () => {
    // Safari in private mode throws on write; enterprise policy can disable it
    // outright. Neither is worth breaking a grid over.
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });

    renderGrid();
    await screen.findByText("a1");
    await openPicker();
    await untick("bravo");

    expect(firstBodyRow()).toEqual(["1", "a1", "c1", "d1"]);
  });
});

/**
 * Every popup on this screen must be closable from the keyboard, and must hand
 * focus back when it closes.
 *
 * The type picker had none of it — no Escape, no outside click. It opened over
 * the data and stayed there until the same header was clicked again or a type
 * was chosen, which for a keyboard user is a trap: focus moves into a panel
 * that cannot be dismissed. The account menu had been given all of this in an
 * earlier session, and the fix stopped at the widget in front of whoever wrote
 * it. `useDisclosure` is where it lives now, so these assertions cover the
 * column picker in the same breath.
 */
describe("popups", () => {
  it("closes the type picker on Escape and returns focus to the header", async () => {
    const user = userEvent.setup();
    renderGrid();
    await screen.findByText("a1");

    const header = screen.getByRole("button", { name: /^alpha/ });
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    // Focus moved into the panel, so the next Tab continues inside it.
    expect(screen.getByRole("button", { name: "integer" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(header).toHaveFocus();
  });

  it("closes the type picker when something else is clicked", async () => {
    const user = userEvent.setup();
    renderGrid();
    await screen.findByText("a1");

    const header = screen.getByRole("button", { name: /^alpha/ });
    await user.click(header);
    await user.click(screen.getByRole("button", { name: "Columns" }));

    expect(header).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the column picker on Escape and returns focus to its trigger", async () => {
    const user = userEvent.setup();
    renderGrid();
    await screen.findByText("a1");

    const trigger = screen.getByRole("button", { name: "Columns" });
    await user.click(trigger);
    expect(screen.getByRole("checkbox", { name: /^alpha/ })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});
