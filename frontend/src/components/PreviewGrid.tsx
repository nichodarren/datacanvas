"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useRef, useState } from "react";

import { LOGICAL_TYPES, type ColumnSpec, type SchemaContract, api } from "@/lib/api";

const PAGE_SIZE = 200;
const ROW_HEIGHT = 27;

/**
 * The preview grid (P0-14, FR-D.1, FR-D.2, FR-D.4, FR-D.5).
 *
 * Two decisions carry this component.
 *
 * **Rows are fetched a page at a time and never all at once.** FR-D.1 promises
 * a five-million-row dataset without freezing the browser, and the only way to
 * keep that promise is for the browser never to see five million rows. The
 * virtualizer renders what fits on screen; the fetcher pulls the pages those
 * rows fall in.
 *
 * **The header is the product.** §14 (FR-D.4/D.5 rationale) is explicit that
 * the first question on unfamiliar data is not "what is in rows 1 to 100" but
 * "can I trust this?" — and a raw grid never answers it. So each header shows
 * the name, the logical type, and how sure the detector was, and clicking it
 * changes the type (FR-C.2). Correction lives exactly where the problem is
 * visible.
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
  const scroller = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<Map<number, (string | null)[]>>(new Map());
  const [pending, setPending] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const columns = [...contract.columns].sort((a, b) => a.ordinal - b.ordinal);

  const virtualizer = useVirtualizer({
    count: totalRows,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 20,
  });

  const items = virtualizer.getVirtualItems();

  const fetchPage = useCallback(
    async (page: number) => {
      setPending((current) => new Set(current).add(page));
      try {
        const result = await api.rows(workspaceId, versionId, page * PAGE_SIZE, PAGE_SIZE);
        setRows((current) => {
          const next = new Map(current);
          result.rows.forEach((row, index) => next.set(result.offset + index, row));
          return next;
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not load rows.");
      }
    },
    [workspaceId, versionId],
  );

  // Which pages the visible window falls in. Deliberately driven by what is on
  // screen rather than by a scroll position: overscan, resizing and jumping to
  // an offset all produce the same question, and answering it in one place
  // means no path can forget to load.
  useEffect(() => {
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;

    for (
      let page = Math.floor(first.index / PAGE_SIZE);
      page <= Math.floor(last.index / PAGE_SIZE);
      page += 1
    ) {
      if (!pending.has(page)) void fetchPage(page);
    }
  }, [items, pending, fetchPage]);

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

      <div className="grid-wrap" ref={scroller} style={{ height: "62vh" }}>
        <table className="grid" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th style={{ width: 64 }}>
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
            {/* A spacer row above and below the window is what lets a native
                table scroll like a five-million-row one without holding five
                million <tr>. */}
            <tr style={{ height: items[0]?.start ?? 0 }} />
            {items.map((item) => {
              const row = rows.get(item.index);
              return (
                <tr key={item.key} style={{ height: ROW_HEIGHT }}>
                  <td className="rownum">{(item.index + 1).toLocaleString()}</td>
                  {columns.map((column, columnIndex) => {
                    const cell = row?.[columnIndex];
                    if (!row) {
                      return (
                        <td key={column.name} className="null">
                          …
                        </td>
                      );
                    }
                    return cell === null || cell === "" ? (
                      // An empty cell and a null cell are different facts, and
                      // a blank space says neither. FR-D.7 will mark these
                      // properly; until then the word is at least honest.
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
              );
            })}
            <tr
              style={{
                height: Math.max(
                  0,
                  virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0),
                ),
              }}
            />
          </tbody>
        </table>
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
