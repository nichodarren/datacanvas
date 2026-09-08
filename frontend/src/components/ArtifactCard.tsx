"use client";

import { useEffect, useRef, useState } from "react";

import { api, describeFailure, type Artifact } from "@/lib/api";

/**
 * One computation, drawn as its `output_kind` says (§11.2, §11.4.1).
 *
 * **The card never learns a tool's name.** §11.2 is explicit that the frontend
 * renders from `output_kind` and nothing else, and the payoff is arithmetic:
 * two renderers here cover thirteen of the seventeen tools, and the fourteenth
 * tool to be written needs no change at all as long as its output has a shape
 * somebody has already drawn.
 *
 * | kind | tools | what it is |
 * |---|---|---|
 * | `table` | 8 | rows and columns |
 * | `report` | 5 | a ranked list, one reason per row |
 * | `matrix` | 1 | a labelled grid |
 * | `chart_spec` | 1 | Vega-Lite, drawn in the browser |
 *
 * `column_cards` and `stat_panel` are drawn by the Profile tab and the column
 * panel; they are dead ends by design (§11.4.1) and do not appear here.
 *
 * The id it was built from never reaches the screen (D-099); it is the
 * address this card fetches from, not something a reader is asked to hold.
 *
 * ## It fetches its own result
 *
 * The answer arrives without them. A report is under a kilobyte and a scatter
 * plot at the row ceiling is about a megabyte, so inlining every result would
 * make the sentence wait for the heaviest card in the turn.
 */
export function ArtifactCard({
  datasetId,
  refId,
  tool,
  outputKind,
}: {
  datasetId: string;
  refId: string;
  tool: string;
  outputKind: string;
}) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .artifact(datasetId, refId)
      .then((found) => {
        if (alive) setArtifact(found);
      })
      .catch((cause) => {
        if (alive) setError(describeFailure(cause));
      });
    return () => {
      alive = false;
    };
  }, [datasetId, refId]);

  return (
    <article className="artifact" data-kind={outputKind} data-ref={refId}>
      {/* The tool's name, and no id (D-099). `data-ref` stays: it is how the
          card fetched itself and how a test finds it, neither of which asks a
          person to read a UUID. */}
      <header className="artifact-head">
        <span className="caps">{tool}</span>
      </header>

      {error !== null ? (
        <p className="muted artifact-body">{error}</p>
      ) : artifact === null ? (
        <p className="muted artifact-body">Loading…</p>
      ) : (
        <Body artifact={artifact} />
      )}
    </article>
  );
}

function Body({ artifact }: { artifact: Artifact }) {
  const { output_kind: kind, result } = artifact;

  if (kind === "table") return <TableBody result={result} />;
  if (kind === "report") return <ReportBody result={result} />;
  if (kind === "matrix") return <MatrixBody result={result} />;
  if (kind === "chart_spec") return <ChartBody result={result} />;

  // **Named rather than blank.** A card that renders nothing and says nothing
  // is indistinguishable from one that failed, and §14.5 asks an empty state
  // to say which it is.
  return (
    <p className="muted artifact-body">
      Nothing here draws a {kind || "result of this kind"} yet.
    </p>
  );
}

/* --------------------------------------------------------------- table --- */

type Preview = { columns?: unknown; rows?: unknown };

/**
 * A transform's output: the schema it produced, and the first rows of it.
 *
 * The row count is stated separately from the rows shown, because they differ
 * and the difference matters: a filter that kept 113 rows shows ten of them,
 * and a card that only showed ten would read as a result with ten rows in it.
 */
function TableBody({ result }: { result: Record<string, unknown> }) {
  const preview = (result.preview ?? {}) as Preview;
  const columns = Array.isArray(preview.columns) ? (preview.columns as string[]) : [];
  const rows = Array.isArray(preview.rows) ? (preview.rows as (string | null)[][]) : [];
  const total = typeof result.row_count === "number" ? result.row_count : null;
  const note = typeof result.note === "string" ? result.note : "";

  if (columns.length === 0) {
    return <p className="muted artifact-body">This step produced no columns.</p>;
  }

  return (
    <div className="artifact-body">
      {note ? <p className="artifact-note muted">{note}</p> : null}
      <div className="artifact-scroll">
        <table className="artifact-table">
          <thead>
            <tr>
              {columns.map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              // The index is the key because a row has no id and two rows may
              // be identical — which `duplicate_report` exists to find.
              <tr key={index}>
                {columns.map((name, cell) => (
                  <td key={name}>
                    {row[cell] === null ? <span className="faint">null</span> : row[cell]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total !== null && total > rows.length ? (
        <p className="artifact-foot muted">
          {rows.length} of {total.toLocaleString("en")} rows
        </p>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------- report --- */

type Finding = { subject?: unknown; reason?: unknown };

/**
 * A ranked list with one reason per row (§11.4.1).
 *
 * The reason is prose the **tool** computed, not the model — so it is shown as
 * written. That is what makes a report readable without a narration on top of
 * it, and it is why five tools share one renderer.
 */
function ReportBody({ result }: { result: Record<string, unknown> }) {
  const findings = Array.isArray(result.findings) ? (result.findings as Finding[]) : [];
  const note = typeof result.note === "string" ? result.note : "";
  const scanned = typeof result.scanned === "number" ? result.scanned : null;

  return (
    <div className="artifact-body">
      {findings.length === 0 ? (
        // *Nothing was found* is an answer, and an empty card would read as a
        // tool that had not run.
        <p className="muted">
          Nothing to report{scanned !== null ? ` across ${scanned} column(s)` : ""}.
        </p>
      ) : (
        <ol className="findings">
          {findings.map((finding, index) => (
            <li key={`${String(finding.subject)}-${index}`}>
              <span className="finding-subject">{String(finding.subject ?? "")}</span>
              <span className="finding-reason muted">{String(finding.reason ?? "")}</span>
            </li>
          ))}
        </ol>
      )}
      {note ? <p className="artifact-foot muted">{note}</p> : null}
    </div>
  );
}

/* -------------------------------------------------------------- matrix --- */

type Cell = { row?: unknown; column?: unknown; count?: unknown; value?: unknown };

/**
 * A labelled grid, rebuilt from long form (§11.4.1).
 *
 * The wire carries `(row, column, value)` because that is what composes with
 * `plot`; a grid is what a person reads. Both are the same numbers, and the
 * conversion belongs here rather than on the wire.
 */
function MatrixBody({ result }: { result: Record<string, unknown> }) {
  const rows = Array.isArray(result.rows) ? (result.rows as string[]) : [];
  const columns = Array.isArray(result.columns) ? (result.columns as string[]) : [];
  const cells = Array.isArray(result.cells) ? (result.cells as Cell[]) : [];
  const normalize = typeof result.normalize === "string" ? result.normalize : "none";
  const incomplete = typeof result.incomplete === "number" ? result.incomplete : 0;

  const at = new Map<string, Cell>();
  for (const cell of cells) at.set(`${String(cell.row)} ${String(cell.column)}`, cell);

  return (
    <div className="artifact-body">
      <div className="artifact-scroll">
        <table className="artifact-table matrix">
          <thead>
            <tr>
              <th scope="col">
                {String(result.row_column ?? "")} \ {String(result.column_column ?? "")}
              </th>
              {columns.map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <th scope="row">{row}</th>
                {columns.map((column) => {
                  const cell = at.get(`${row} ${column}`);
                  const count = typeof cell?.count === "number" ? cell.count : 0;
                  const value = typeof cell?.value === "number" ? cell.value : count;
                  return (
                    <td key={column}>
                      {normalize === "none"
                        ? count.toLocaleString("en")
                        : `${(value * 100).toFixed(1)}%`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {incomplete > 0 ? (
        // Said out loud: a crosstab that quietly summed to less than the table
        // would have every share computed against the wrong denominator.
        <p className="artifact-foot muted">
          {incomplete.toLocaleString("en")} row(s) had no value in one of the two columns and are
          not counted.
        </p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------- chart_spec --- */

/**
 * Vega-Lite, compiled in the browser (D-016).
 *
 * **Loaded on demand.** `vega-embed` pulls Vega and Vega-Lite with it — about
 * a megabyte, larger than everything else this app ships — and most questions
 * never produce a chart. A dynamic import means the reader who never asks for
 * one never downloads it.
 *
 * `plot` computed nothing to get here: the numbers were a Computation before
 * they were a mark, which is what keeps INV-5 true of a picture.
 */
function ChartBody({ result }: { result: Record<string, unknown> }) {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const spec = result.spec;
    const node = host.current;
    if (node === null || spec === undefined || spec === null) return;

    let alive = true;
    let dispose: (() => void) | null = null;

    void import("vega-embed")
      .then(async ({ default: embed }) => {
        if (!alive) return;
        const view = await embed(
          node,
          // The page is dark; a chart on its own white plate would be the one
          // thing on screen that did not read as part of it. `background` is a
          // property of the **spec**, not of the embed — set as an option it
          // type-errors, which is the library saying where it belongs.
          { background: "transparent", ...(spec as object) },
          { actions: false, renderer: "canvas", theme: "dark" },
        );
        if (!alive) {
          view.finalize();
          return;
        }
        dispose = () => view.finalize();
      })
      .catch((cause: unknown) => {
        if (alive) setFailed(cause instanceof Error ? cause.message : "the chart did not draw");
      });

    return () => {
      alive = false;
      dispose?.();
    };
  }, [result]);

  if (failed !== null) {
    return <p className="muted artifact-body">{failed}</p>;
  }
  return <div className="artifact-body artifact-chart" ref={host} />;
}
