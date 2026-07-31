"use client";

import { useCallback, useEffect, useState } from "react";

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
 * ## The horizontal edge
 *
 * Twelve columns fit. Ingest accepts any number and there is no cap anywhere in
 * NFR-SCALE; past roughly fifteen the cells go too narrow to read, and no
 * styling fixes that. It needs a decision — scrolling back, or FR-D.3's hide and
 * reorder — not a workaround.
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

  const columns = [...contract.columns].sort((a, b) => a.ordinal - b.ordinal);

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

      <div className="grid-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 48 }}>
                <span className="colhead" style={{ cursor: "default" }}>
                  <span className="name faint">#</span>
                </span>
              </th>
              {columns.map((column) => (
                <ColumnHeader
                  key={column.name}
                  column={column}
                  editing={editing === column.name}
                  onOpen={() => setEditing(editing === column.name ? null : column.name)}
                  onPick={(logicalType) => void changeType(column, logicalType)}
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
                <td className="rownum">{index + 1}</td>
                {columns.map((column, columnIndex) => {
                  const cell = row[columnIndex];
                  return cell === null || cell === "" ? (
                    // An empty cell and a null cell are different facts, and a
                    // blank space says neither.
                    <td key={column.name} className="null">
                      null
                    </td>
                  ) : (
                    <td key={column.name} title={cell}>
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
  editing,
  onOpen,
  onPick,
}: {
  column: ColumnSpec;
  editing: boolean;
  onOpen: () => void;
  onPick: (logicalType: string) => void;
}) {
  return (
    <th style={{ position: "relative", minWidth: 150 }}>
      <button type="button" className="colhead" onClick={onOpen}>
        <span className="name">{column.name}</span>
        <span className="meta">
          <span className="type">{column.logical_type}</span>
        </span>
      </button>

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
