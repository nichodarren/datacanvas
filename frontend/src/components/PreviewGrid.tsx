"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { LOGICAL_TYPES, type ColumnSpec, type SchemaContract, api } from "@/lib/api";

/** What the first screen shows. Deliberately small: a glance, not a session. */
const INITIAL_ROWS = 10;

/**
 * How many rows each "View more" adds.
 *
 * Larger than the opening ten on purpose. Ten per click reads well in a
 * specification and is miserable in the hand — nine clicks to reach row 100. The
 * first screen stays a glance; asking for more should actually give you more.
 */
const MORE_ROWS = 50;

/**
 * The narrowest a column may be before the table scrolls instead.
 *
 * Not a round number, and not a guess. At the 1280px NFR-UX.4 guarantees the
 * workarea leaves 1230px inside the grid's border, and the row-number column
 * takes 48 of it. Twelve columns — what both bundled datasets have, and what
 * the owner signed off on looking at — therefore get 98px each before anything
 * overflows.
 *
 * So the ceiling is 98, and 96 leaves a little slack. Choosing 110 because it
 * sounded comfortable would have put a scrollbar under the exact file this
 * design was approved on, which is the opposite of the promise.
 *
 * The floor is the longest word the header must hold on one line:
 * `categorical` at 11px monospace is about 73px, and `.colhead` spends 20 on
 * padding. 96 clears it.
 */
const MIN_COLUMN_WIDTH = 96;

/**
 * How many columns a wide file opens with.
 *
 * Fifteen at `MIN_COLUMN_WIDTH` is 1488px: a short scroll on a 1280px screen,
 * none at all on a wide one, and readable either way. The rest are one click
 * away in the picker rather than crushed into the same width.
 */
const MAX_DEFAULT_COLUMNS = 15;

/** The row-number column. Fixed, and the origin every pin offset counts from. */
const ROWNUM_WIDTH = 48;

/**
 * The preview: the first rows of a dataset, every column on screen at once, and
 * a button that fetches the next page.
 *
 * ## What this replaced, and what that costs
 *
 * A virtualized grid that scrolled through five million rows while the browser
 * never held more than a screenful. Gate 2 measured it at 94 ms for the first
 * page of the 5,000,000-row fixture and 69 ms to jump to row 2,500,000.
 *
 * **FR-D.2 (P0) — "the number of rows shown can be set by the user" — is met by
 * the button.** The requirement does not prescribe a control, and clicking is a
 * way of setting it.
 *
 * **FR-D.1 is met in half, and the other half cannot be met by this pattern —
 * which is why the requirement was split rather than quietly kept.** Server-side
 * paging is real: each click is one `offset`/`limit` request, and the route still
 * answers any offset in a 5M-row dataset in well under a second (FR-D.1a). What
 * this cannot do is *browse* such a dataset. At fifty rows a click, row 100,000
 * is two thousand clicks away and row 5,000,000 is a hundred thousand — and the
 * rows accumulate in the DOM as you go. That is arithmetic, not polish, so
 * FR-D.1b now says so and waits for a UI that means it.
 *
 * ## The horizontal edge, and how FR-D.3 answers it
 *
 * Ingest accepts a file with any number of columns — there is no cap in
 * NFR-SCALE or anywhere else — and the workarea is about 1230px at the 1280px
 * NFR-UX.4 guarantees. Divided evenly that is 100px a column at twelve, 40px at
 * thirty, and nonsense at sixty. Three things answer it together, and none of
 * them alone:
 *
 * 1. **A column picker** (FR-D.3: hide, reorder). For a wide file, choosing the
 *    five columns you care about beats scrolling past fifty-five you do not.
 * 2. **A sane default.** Beyond `MAX_DEFAULT_COLUMNS` the extras start hidden,
 *    so nobody meets the wall on first open and only then discovers the control.
 * 3. **Horizontal scrolling, but only when it is earning its place.** Each
 *    column gets `MIN_COLUMN_WIDTH`; while the total fits, the table is exactly
 *    what it was before — no scrollbar at all. Past that it overflows and
 *    scrolls, because the alternative is text too narrow to read.
 *
 * The third is a deliberate, partial reversal of "no scrollbars". What was
 * objected to was a scrollbar on a twelve-column file whose content already
 * fitted, and that still cannot happen. A conditional scrollbar is a different
 * object from a permanent one.
 *
 * It also makes the rest of FR-D.3 honest. `pin` freezes a column *while you
 * scroll* and `resize` needs somewhere for the extra pixels to go; with nothing
 * scrolling, both are controls that do nothing — the exact defect this session
 * spent its time removing.
 */
export function PreviewGrid({
  workspaceId,
  versionId,
  totalRows,
  contract,
  onContractChanged,
}: {
  workspaceId: string;
  versionId: string;
  totalRows: number;
  contract: SchemaContract;
  onContractChanged: (next: SchemaContract) => void;
}) {
  const [rows, setRows] = useState<(string | null)[][]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  /**
   * Columns the user has hidden — or that started hidden because the file is
   * wide. Storing the *hidden* set rather than the visible one means a column
   * added by a later contract shows up by default instead of vanishing.
   */
  const [hidden, setHidden] = useState<Set<string>>(
    () =>
      new Set(
        [...contract.columns]
          .sort((a, b) => a.ordinal - b.ordinal)
          .slice(MAX_DEFAULT_COLUMNS)
          .map((column) => column.name),
      ),
  );

  const [picking, setPicking] = useState(false);

  /**
   * Explicit widths, set by dragging a header edge — and only for columns that
   * were actually dragged. The rest stay unset so `table-layout: fixed` keeps
   * sharing the remaining space evenly, which is what makes a narrow file fill
   * the page instead of huddling to the left.
   */
  const [widths, setWidths] = useState<Record<string, number>>({});

  /**
   * Columns frozen against the left edge while the rest scroll past.
   *
   * Only meaningful because scrolling came back — a pin with nothing to scroll
   * under it is a control that does nothing. Pinning is *ordered by the file*,
   * not by when you clicked: two pinned columns keep their original relative
   * position, because a pin is a promise to keep something in view, not an
   * instruction to rearrange the table.
   */
  const [pinned, setPinned] = useState<Set<string>>(new Set());

  /** Header cells, so a column can be measured at the moment it is pinned. */
  const headers = useRef(new Map<string, HTMLTableCellElement>());

  // Always the file's own order. Reordering was built and then removed at the
  // owner's direction: the arrows were two more controls on every row of a
  // sixty-row list, and the order a file already has is the order the person
  // who made it chose.
  const ordered = [...contract.columns].sort((a, b) => a.ordinal - b.ordinal);
  const columns = ordered.filter((column) => !hidden.has(column.name));

  /**
   * Where each pinned column comes to rest, in pixels from the left.
   *
   * A pinned column needs an explicit width or there is nothing to stack the
   * next one against, which is why `pin` measures and stores one. The
   * row-number column is always first and always 48.
   */
  const offsets = new Map<string, number>();
  let running = ROWNUM_WIDTH;
  for (const column of columns) {
    if (!pinned.has(column.name)) continue;
    offsets.set(column.name, running);
    running += widths[column.name] ?? MIN_COLUMN_WIDTH;
  }

  const tableMinWidth =
    ROWNUM_WIDTH +
    columns.reduce((total, column) => total + (widths[column.name] ?? MIN_COLUMN_WIDTH), 0);

  function toggle(name: string) {
    setHidden((current) => {
      const next = new Set(current);
      // Never hide the last one: an empty grid is not a view of anything, and
      // the way back would be a control the user can no longer see beside data.
      if (!next.has(name) && current.size >= ordered.length - 1) return current;
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
    // A pin on a column nobody can see is a promise about nothing, and it would
    // leave a gap in the sticky offsets of the columns that are still shown.
    setPinned((current) => {
      if (!current.has(name)) return current;
      const next = new Set(current);
      next.delete(name);
      return next;
    });
  }

  function togglePin(name: string) {
    setPinned((current) => {
      const next = new Set(current);
      if (next.has(name)) {
        next.delete(name);
        return next;
      }
      next.add(name);
      // Freeze the width it has *right now*. Without this the column would jump
      // to some default the instant it is pinned — the one moment a user is
      // watching it closely.
      const measured = headers.current.get(name)?.offsetWidth;
      if (measured) {
        setWidths((sizes) => (sizes[name] ? sizes : { ...sizes, [name]: measured }));
      }
      return next;
    });
  }

  function resize(name: string, width: number) {
    setWidths((current) => ({ ...current, [name]: Math.max(MIN_COLUMN_WIDTH, Math.round(width)) }));
  }

  /**
   * Fetch one page and append it.
   *
   * `offset` is passed in rather than read from `rows.length` so this does not
   * close over the list it appends to — the version that did could fire twice
   * on the same offset and duplicate a page.
   */
  const fetchFrom = useCallback(
    async (offset: number, limit: number) => {
      setBusy(true);
      setError(null);
      try {
        const result = await api.rows(workspaceId, versionId, offset, limit);
        setRows((current) => (offset === 0 ? result.rows : [...current, ...result.rows]));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not load rows.");
      } finally {
        setBusy(false);
      }
    },
    [workspaceId, versionId],
  );

  useEffect(() => {
    void fetchFrom(0, INITIAL_ROWS);
  }, [fetchFrom]);

  async function changeType(column: ColumnSpec, logicalType: string) {
    setEditing(null);
    if (logicalType === column.logical_type) return;
    try {
      const next = await api.correctSchema(workspaceId, versionId, [
        { name: column.name, logical_type: logicalType },
      ]);
      onContractChanged(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not change the type.");
    }
  }

  return (
    <div className="stack">
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="row" style={{ position: "relative" }}>
        <button type="button" onClick={() => setPicking(!picking)} aria-expanded={picking}>
          Columns
        </button>
        <span className="faint" style={{ fontSize: 12 }}>
          {hidden.size === 0
            ? `${columns.length} columns`
            : `${columns.length} of ${ordered.length} columns`}
        </span>
        {picking ? (
          <ColumnPicker
            columns={ordered}
            hidden={hidden}
            onToggle={toggle}
            pinned={pinned}
            onTogglePin={togglePin}
            onShowAll={() => setHidden(new Set())}
            onClose={() => setPicking(false)}
          />
        ) : null}
      </div>

      <div className="grid-wrap">
        {/* `width: 100%` while the columns fit, `min-width` once they do not.
            That single pair is the whole conditional-scrollbar rule: a
            twelve-column file looks exactly as it did with scrolling removed,
            and a sixty-column one scrolls instead of becoming unreadable. */}
        <table className="grid" style={{ minWidth: tableMinWidth }}>
          <thead>
            <tr>
              <th className="sticky-col" style={{ width: ROWNUM_WIDTH, left: 0 }}>
                <span className="colhead" style={{ cursor: "default" }}>
                  <span className="name faint">#</span>
                </span>
              </th>
              {columns.map((column) => (
                <ColumnHeader
                  key={column.name}
                  column={column}
                  width={widths[column.name]}
                  pinnedAt={offsets.get(column.name)}
                  editing={editing === column.name}
                  registerRef={(node) => {
                    if (node) headers.current.set(column.name, node);
                    else headers.current.delete(column.name);
                  }}
                  onOpen={() => setEditing(editing === column.name ? null : column.name)}
                  onPick={(logicalType) => void changeType(column, logicalType)}
                  onResize={(width) => resize(column.name, width)}
                />
              ))}
            </tr>
          </thead>

          <tbody>
            {rows.map((row, index) => (
              // A preview row has no identity of its own — it is a slice of a
              // file, not a record — so the offset is the key.
              // eslint-disable-next-line react/no-array-index-key
              <tr key={index}>
                <td className="rownum sticky-col" style={{ left: 0 }}>
                  {index + 1}
                </td>
                {columns.map((column, columnIndex) => {
                  const cell = row[columnIndex];
                  const at = offsets.get(column.name);
                  // A sticky cell needs its own background, or the columns
                  // scrolling underneath show straight through it.
                  const sticky = at === undefined ? undefined : { left: at };
                  const className = [at === undefined ? "" : "sticky-col", cell ? "" : "null"]
                    .filter(Boolean)
                    .join(" ");
                  return cell === null || cell === "" ? (
                    // An empty cell and a null cell are different facts, and a
                    // blank space says neither.
                    <td key={column.name} className={className} style={sticky}>
                      null
                    </td>
                  ) : (
                    <td key={column.name} className={className} style={sticky} title={cell}>
                      {cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The count is stated whether or not there is more to fetch. "10 of 891"
          and "891 of 891" answer different questions, and the second is the one
          that tells you there is nothing left to look for. */}
      <div className="row">
        {rows.length < totalRows ? (
          <button type="button" disabled={busy} onClick={() => void fetchFrom(rows.length, MORE_ROWS)}>
            {busy ? "Loading…" : `View ${Math.min(MORE_ROWS, totalRows - rows.length)} more`}
          </button>
        ) : null}
        <span className="faint" style={{ fontSize: 12 }}>
          {rows.length.toLocaleString()} of {totalRows.toLocaleString()} rows
        </span>
      </div>
    </div>
  );
}

/**
 * Choose which columns are shown (FR-D.3, the `hide` half).
 *
 * Reordering was built here and taken out again at the owner's direction. It
 * cost two buttons on every row — on a sixty-column file, a hundred and twenty
 * controls in a list whose job is to let you tick five boxes — to rearrange
 * something the file already ordered deliberately. FR-D.3 keeps `reorder` on
 * the books; this surface does not carry it.
 *
 * The last visible column cannot be hidden. A grid of nothing is not a view,
 * and the control that would undo it sits above data that is no longer there.
 */
function ColumnPicker({
  columns,
  hidden,
  onToggle,
  pinned,
  onTogglePin,
  onShowAll,
  onClose,
}: {
  columns: ColumnSpec[];
  hidden: Set<string>;
  onToggle: (name: string) => void;
  pinned: Set<string>;
  onTogglePin: (name: string) => void;
  onShowAll: () => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const onDocument = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDocument);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDocument);
    };
  }, [onClose]);

  const visible = columns.length - hidden.size;

  return (
    <div ref={box} className="menu column-picker">
      {/* One action, deliberately. "Select none" is a state this refuses, and a
          "back to the default" button was built and then removed — the way back
          is unticking, and one control beats two on a panel whose whole point is
          to be quicker than the boxes below it. */}
      <div className="picker-actions">
        <button type="button" onClick={onShowAll} disabled={hidden.size === 0}>
          Select all
        </button>
        <span className="faint" style={{ fontSize: 12, marginLeft: "auto" }}>
          {visible}/{columns.length}
        </span>
      </div>

      {columns.map((column) => {
        const isHidden = hidden.has(column.name);
        return (
          <div key={column.name} className="picker-row">
            <label>
              <input
                type="checkbox"
                checked={!isHidden}
                disabled={!isHidden && visible <= 1}
                onChange={() => onToggle(column.name)}
              />
              <span className="picker-name">{column.name}</span>
              <span className="faint mono" style={{ fontSize: 11 }}>
                {column.logical_type}
              </span>
            </label>
            {/* A toggle button, not a second checkbox. Two checkboxes on one
                row would read as two halves of the same choice, and these are
                unrelated: one decides whether a column is shown at all, the
                other whether it stays put while the rest scroll past. */}
            <button
              type="button"
              className={pinned.has(column.name) ? "pin on" : "pin"}
              aria-pressed={pinned.has(column.name)}
              aria-label={`${pinned.has(column.name) ? "Unpin" : "Pin"} ${column.name}`}
              title="Keep this column in view while scrolling"
              disabled={isHidden}
              onClick={() => onTogglePin(column.name)}
            >
              📌
            </button>
          </div>
        );
      })}
    </div>
  );
}

/**
 * One column header: the name, and what the column is being read as.
 *
 * It used to carry two more signals — a `check` pill when detection confidence
 * fell below 0.8, and a `✓ set` badge once a user had overridden the type.
 * Across twelve columns of a wide table that is twelve small decisions asked of
 * someone who came here to look at their data, and the owner's call was that
 * the type alone is the information.
 *
 * FR-C.6 (warn when detection is risky) is **P1**, so this is a product
 * decision rather than a dropped P0 — recorded in the project notes so it is a choice
 * on the record and not an omission nobody noticed.
 *
 * `detection_reason` survives in the popup below. That is not a label: it is
 * only read once someone has decided to change a type, which is exactly the
 * moment "numeric, but only 7 distinct values in 891 rows" is worth having.
 */
function ColumnHeader({
  column,
  width,
  pinnedAt,
  editing,
  registerRef,
  onOpen,
  onPick,
  onResize,
}: {
  column: ColumnSpec;
  width: number | undefined;
  pinnedAt: number | undefined;
  editing: boolean;
  registerRef: (node: HTMLTableCellElement | null) => void;
  onOpen: () => void;
  onPick: (logicalType: string) => void;
  onResize: (width: number) => void;
}) {
  const cell = useRef<HTMLTableCellElement | null>(null);

  /**
   * Drag the right edge to set this column's width.
   *
   * Listeners go on `document`, not the handle: once dragging starts the
   * pointer routinely leaves the four-pixel strip it began on, and a handler
   * bound to the strip would drop the drag the moment it did.
   */
  function startResize(event: React.MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = cell.current?.offsetWidth ?? MIN_COLUMN_WIDTH;

    const onMove = (moved: MouseEvent) => onResize(startWidth + moved.clientX - startX);
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.classList.remove("resizing");
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    // Holds the col-resize cursor across the whole page for the duration, so it
    // does not flicker back to a text caret as the pointer crosses cells.
    document.body.classList.add("resizing");
  }

  return (
    <th
      ref={(node) => {
        cell.current = node;
        registerRef(node);
      }}
      className={pinnedAt === undefined ? undefined : "sticky-col"}
      style={{
        position: pinnedAt === undefined ? "relative" : "sticky",
        left: pinnedAt,
        width,
        minWidth: MIN_COLUMN_WIDTH,
      }}
    >
      <button type="button" className="colhead" onClick={onOpen}>
        <span className="name">{column.name}</span>
        <span className="meta">
          <span className="type">{column.logical_type}</span>
        </span>
      </button>

      <span
        className="resize-handle"
        role="presentation"
        onMouseDown={startResize}
        onDoubleClick={() => onResize(MIN_COLUMN_WIDTH)}
        title="Drag to resize · double-click to reset"
      />

      {editing ? (
        <div
          className="card"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 5,
            width: 260,
            margin: 0,
            boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
          }}
        >
          <div className="type-menu">
            {LOGICAL_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                className={type === column.logical_type ? "current" : ""}
                // The current type is marked by colour instead of the words
                // "· current" that used to trail it. `aria-current` carries the
                // same fact to anyone who cannot see the colour, so dropping
                // the label costs nothing there (NFR-UX.3).
                aria-current={type === column.logical_type}
                onClick={() => onPick(type)}
              >
                {type}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </th>
  );
}
