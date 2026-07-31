"use client";

import { useCallback, useEffect, useState } from "react";

import { LOGICAL_TYPES, type ColumnSpec, type SchemaContract, api } from "@/lib/api";

/** How many rows a preview shows. `head(20)`, and nothing beyond it. */
const PREVIEW_ROWS = 20;

/**
 * The preview: the first rows of a dataset, with every column on screen at once.
 *
 * This was a virtualized, server-paged grid that could scroll through five
 * million rows without the browser ever holding more than a screenful — the
 * thing FR-D.1 asks for, and the thing Gate 2 measured at 94 ms for the first
 * page of the 5,000,000-row fixture. At the owner's direction it is now a
 * fixed `head(20)` with no scrollbars in either axis.
 *
 * Two requirements are knowingly unmet by that, both recorded in the project notes:
 *
 * * **FR-D.1 / FR-D.2 (P0)** — browsing a large dataset. Rows 21 and beyond are
 *   now unreachable from the UI. The server route still pages (`offset`,
 *   `limit`), so the capability is intact; nothing calls for it.
 * * **NFR-PERF.1** — the measurement that closed Gate 2 was taken on the path
 *   this replaces. It stays true of the API and is no longer exercised by the
 *   browser.
 *
 * The horizontal constraint is the one with a hard edge. Twelve columns fit;
 * ingest accepts a file with any number of them, and there is no cap anywhere
 * in NFR-SCALE. Past roughly fifteen the cells become too narrow to read, and
 * no amount of styling fixes that — it needs a decision (scrolling back, or
 * choosing which columns to show), not a workaround.
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
  const [rows, setRows] = useState<(string | null)[][] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const columns = [...contract.columns].sort((a, b) => a.ordinal - b.ordinal);

  const load = useCallback(async () => {
    try {
      const result = await api.rows(workspaceId, versionId, 0, PREVIEW_ROWS);
      setRows(result.rows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load rows.");
    }
  }, [workspaceId, versionId]);

  useEffect(() => {
    void load();
  }, [load]);

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
            {(rows ?? []).map((row, index) => (
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

      {rows !== null && totalRows > PREVIEW_ROWS ? (
        <p className="faint" style={{ fontSize: 12, margin: 0 }}>
          Showing the first {PREVIEW_ROWS} of {totalRows.toLocaleString()} rows.
        </p>
      ) : null}
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
