import { StrictMode } from "react";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewGrid } from "@/components/PreviewGrid";
import {
  LOGICAL_TYPES,
  type ColumnSpec,
  type SchemaContract,
  api,
} from "@/lib/api";

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
  return {
    ...actual,
    api: { ...actual.api, rows: vi.fn(), correctSchema: vi.fn() },
  };
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
    null_markers: [],
    detection_confidence: 1,
    detection_reason: "fixture",
    overridden: false,
  };
}

const CONTRACT: SchemaContract = {
  id: "contract-1",
  dataset_id: "version-1",
  version_no: 1,
  columns: NAMES.map((name, index) => spec(name, index)),
  created_at: "2026-01-01T00:00:00Z",
  derived_from: null,
};

function renderGrid() {
  return render(
    <PreviewGrid
      datasetId="version-1"
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
  return within(body)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

/** The contract, with some columns given a type other than the default. */
function typed(types: Record<string, string>): SchemaContract {
  return {
    ...CONTRACT,
    columns: CONTRACT.columns.map((column) =>
      types[column.name]
        ? { ...column, logical_type: types[column.name] as string }
        : column,
    ),
  };
}

/** One column's `<th>`, found through the button that names it. */
function header(name: string): HTMLElement {
  const cell = screen
    .getByRole("button", { name: new RegExp(`^${name}`) })
    .closest("th");
  if (cell === null) throw new Error(`no header cell for ${name}`);
  return cell;
}

async function openPicker() {
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Columns" }));
}

/** Untick one column. The picker must already be open — it stays open. */
async function untick(name: string) {
  // Anchored at the start only: the checkbox's accessible name is its label's
  // text, the column name followed by its logical type.
  await userEvent
    .setup()
    .click(screen.getByRole("checkbox", { name: new RegExp(`^${name}`) }));
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
        datasetId="version-2"
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
    // `numerical` is the first of the five types the menu offers — it was
    // `integer` until the vocabulary narrowed on 2026-08-21.
    expect(screen.getByRole("button", { name: "numerical" })).toHaveFocus();

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
    expect(
      screen.getByRole("checkbox", { name: /^alpha/ }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});

/**
 * The grid scrolls sideways, and a scroll container has to be reachable.
 *
 * FR-D.3 answered the sixty-column file with a picker, a default, and a
 * conditional horizontal scrollbar. The scrollbar was reachable by mouse, by
 * finger, and by nothing else: the cells are deliberately not focusable — five
 * million values must not be five million tab stops — so there was no way to
 * put the keyboard's arrow keys anywhere that would move it. Column sixty could
 * not be read without a pointer at all (WCAG 2.1.1).
 *
 * `tabIndex` on the container is the standard answer, and it costs exactly one
 * tab stop. `role="region"` with a name is the other half: making an element
 * focusable puts it in front of a screen reader user, and an unnamed box is a
 * worse thing to meet than none.
 */
/**
 * Q-4, closed: no emoji stands in for an icon (D-037).
 *
 * `📌` renders as a different picture on every platform and is announced by its
 * Unicode name — "pushpin" — inside a button whose label already says what it
 * does. Its replacement is deliberately not a drawing of a pushpin either: a
 * pushpin means *attach*, and this freezes a column at the edge while the rest
 * scroll past.
 */
describe("the pin control", () => {
  it("carries no emoji", async () => {
    renderGrid();
    await screen.findByText("a1");
    await openPicker();

    const pin = screen.getByRole("button", { name: "Pin alpha" });
    // Pinned to the defect rather than to the markup: any emoji here fails,
    // not merely the one that was there.
    expect(pin.textContent).toBe("");
    expect(pin.querySelector("svg")).toBeInTheDocument();
  });

  it("hides the mark from assistive technology, which already has the label", async () => {
    renderGrid();
    await screen.findByText("a1");
    await openPicker();

    const icon = screen
      .getByRole("button", { name: "Pin alpha" })
      .querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("says whether the column is pinned in a channel other than colour", async () => {
    const user = userEvent.setup();
    renderGrid();
    await screen.findByText("a1");
    await openPicker();

    await user.click(screen.getByRole("button", { name: "Pin alpha" }));

    // The chip inverts, and `aria-pressed` carries the same fact for anyone who
    // cannot see the inversion (NFR-UX.3).
    expect(screen.getByRole("button", { name: "Unpin alpha" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("reaching the grid from the keyboard", () => {
  it("makes the scrolling region focusable and names it", async () => {
    renderGrid();
    await screen.findByText("a1");

    const region = screen.getByRole("region", { name: "Data preview" });
    expect(region).toHaveAttribute("tabindex", "0");
  });

  it("puts the region in the tab order, ahead of the table it holds", async () => {
    const user = userEvent.setup();
    renderGrid();
    await screen.findByText("a1");

    screen.getByRole("button", { name: "Columns" }).focus();
    await user.tab();

    expect(screen.getByRole("region", { name: "Data preview" })).toHaveFocus();
  });
});

describe("what a column says it is", () => {
  /**
   * Two facts a header now carries that it did not, and both are one attribute.
   *
   * The stylesheet turns `data-type` into `--type`, which colours the label —
   * the same hue the profile card's badge uses, so one column reads the same on
   * both tabs — and which decides that a numerical column aligns right. Asserted
   * here rather than in the stylesheet tests because it is the *component's*
   * half: `test_preview_grid_layout.py` checks that a rule exists for every
   * type, and nothing there can see whether anything ever sets the attribute.
   */
  it("names the type of every column in its header", async () => {
    render(
      <PreviewGrid
        datasetId="version-1"
        totalRows={ROWS.length}
        contract={typed({ alpha: "numerical", bravo: "categorical" })}
        onContractChanged={() => {}}
      />,
    );
    await screen.findByText("a1");

    expect(header("alpha")).toHaveAttribute("data-type", "numerical");
    expect(header("bravo")).toHaveAttribute("data-type", "categorical");
    expect(within(header("alpha")).getByText("numerical")).toBeInTheDocument();
  });

  /**
   * The menu behind the header, where every row is a type.
   *
   * The one it is currently set to used to be a filled white chip — the single
   * row in a list of types with no type colour on it. It wears its own hue now
   * and keeps `aria-current`, which is what carries the same fact to anyone who
   * cannot see the colour (NFR-UX.3).
   */
  it("colours every option in the type picker, the current one included", async () => {
    render(
      <PreviewGrid
        datasetId="version-1"
        totalRows={ROWS.length}
        contract={typed({ alpha: "date" })}
        onContractChanged={() => {}}
      />,
    );
    await screen.findByText("a1");
    await userEvent.setup().click(screen.getByRole("button", { name: /^alpha/ }));

    for (const type of LOGICAL_TYPES) {
      expect(screen.getByRole("button", { name: type })).toHaveAttribute(
        "data-type",
        type,
      );
    }
    const current = screen.getByRole("button", { name: "date" });
    expect(current).toHaveClass("current");
    expect(current).toHaveAttribute("aria-current", "true");
  });

  /**
   * Alignment describes the column, not the value.
   *
   * So it is taken from the contract and put on every cell of a numerical
   * column — including the nulls, and including a value that does not parse.
   * §11.8.4 says a numerical column may hold both, and a column that aligned
   * cell by cell would come out ragged at exactly the rows worth noticing.
   */
  it("stands the numbers of a numeric column on the same edge", async () => {
    vi.mocked(api.rows).mockResolvedValue({
      columns: [...NAMES],
      rows: [["88400.00", "b1", "c1", "d1"], [null, "b2", "c2", "d2"]],
      offset: 0,
      limit: 10,
      total_rows: 2,
    });
    render(
      <PreviewGrid
        datasetId="version-1"
        totalRows={2}
        contract={typed({ alpha: "numerical" })}
        onContractChanged={() => {}}
      />,
    );
    await screen.findByText("88400.00");

    expect(screen.getByText("88400.00")).toHaveClass("numeric");
    // The null in the same column, which is not a number and aligns like one
    // anyway.
    expect(screen.getAllByText("null")[0]).toHaveClass("numeric");
    // And a text column left alone.
    expect(screen.getByText("b1")).not.toHaveClass("numeric");
  });
});

describe("coming back to the tab", () => {
  /**
   * Switching tabs unmounts this grid, so everything it holds in state is gone
   * on the way back: the reader who had paged to row 300 and scrolled to
   * column forty came back to ten rows at the left edge, every time.
   *
   * Hidden columns, pins and widths already survived. These two did not, and
   * they are the ones that cost the reader the most to redo.
   */
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("reopens with the rows that had been loaded", async () => {
    const many = Array.from({ length: 60 }, (_, index) => [
      `a${index}`,
      `b${index}`,
      `c${index}`,
      `d${index}`,
    ]);
    vi.mocked(api.rows).mockImplementation(async (_id, offset, limit) => ({
      columns: [...NAMES],
      rows: many.slice(offset, offset + limit),
      offset,
      limit,
      total_rows: many.length,
    }));

    const first = render(
      <PreviewGrid
        datasetId="version-1"
        totalRows={many.length}
        contract={CONTRACT}
        onContractChanged={() => {}}
      />,
    );
    await screen.findByText("a0");
    await userEvent.setup().click(screen.getByRole("button", { name: /more/i }));
    await screen.findByText("a59");
    first.unmount();

    // **Inside `StrictMode`, because that is where this broke.** React runs a
    // mount effect twice in development, and the first version of this flipped
    // its `restored` flag as soon as preferences were read — so the save
    // effect wrote `rows: 0` over the stored 60 while the request for those 60
    // was still open, the second run read the 0 it had just written and asked
    // for 10, and the smaller answer arrived last. Rendered once, the test saw
    // none of it and passed against a grid that forgot in the browser.
    vi.mocked(api.rows).mockClear();
    render(
      <StrictMode>
        <PreviewGrid
          datasetId="version-1"
          totalRows={many.length}
          contract={CONTRACT}
          onContractChanged={() => {}}
        />
      </StrictMode>,
    );
    await screen.findByText("a59");

    // Every opening request asks for the remembered page. The count is not
    // asserted: StrictMode's second pass is React's, not the grid's.
    for (const call of vi.mocked(api.rows).mock.calls) {
      expect(call[1]).toBe(0);
      expect(call[2]).toBe(60);
    }
  });

  it("reopens where the table was scrolled to", async () => {
    vi.mocked(api.rows).mockResolvedValue({
      columns: [...NAMES],
      rows: ROWS,
      offset: 0,
      limit: 10,
      total_rows: ROWS.length,
    });

    const first = renderGrid();
    await screen.findByText("a1");
    const wrap = first.container.querySelector<HTMLElement>(".grid-wrap");
    if (wrap === null) throw new Error("no scroll container");

    // jsdom has no layout, so `scrollLeft` is whatever it is set to. The value
    // is what this test is about: the grid must read it from the node and hand
    // it back, and never hold it in state — a horizontal scroll fires
    // continuously and a `useState` behind it would re-render the table on
    // every frame of a drag.
    wrap.scrollLeft = 640;
    wrap.dispatchEvent(new Event("scroll", { bubbles: true }));
    // Waited for rather than slept through: the write is debounced, and a
    // fixed sleep just longer than the debounce is a test that passes on this
    // machine and flakes on a loaded one.
    await waitFor(() => {
      const raw = window.localStorage.getItem("datacanvas.grid.version-1") ?? "";
      expect(JSON.parse(raw).scrollLeft).toBe(640);
    });
    first.unmount();

    const scrollTo = vi.fn();
    const again = renderGrid();
    const second = again.container.querySelector<HTMLElement>(".grid-wrap");
    if (second === null) throw new Error("no scroll container");
    second.scrollTo = scrollTo;
    await screen.findByText("a1");

    expect(scrollTo).toHaveBeenCalledWith({ left: 640 });
  });
});
