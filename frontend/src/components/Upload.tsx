"use client";

import { useRef, useState } from "react";

import { type Dialect, type IngestPreview, api } from "@/lib/api";

/**
 * Upload with a confirmation step (FR-B.3, §10.4 Alur 1, D-025).
 *
 * Two requests, and the split is the whole decision. The first sends **only the
 * first megabyte** and gets back how the file would be read; nothing is stored.
 * The second sends the file with whatever dialect the user confirmed.
 *
 * §10.4 is blunt about why: v1 swallowed files and sometimes parsed them wrong,
 * and fixing that after twenty analyses had run on a bad parse is expensive.
 * Five seconds of confirmation up front saves hours behind.
 *
 * What is shown for correction is the **dialect** — delimiter, encoding, header
 * row — and nothing about types. A prefix cannot honestly say anything about
 * types: FR-B.3 requires inference to scan the whole file, so the schema
 * arrives after commit and is corrected on the grid instead (FR-C.2).
 */
export function Upload({
  workspaceId,
  projectId,
  onCommitted,
}: {
  workspaceId: string;
  projectId: string;
  onCommitted: (versionId: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<IngestPreview | null>(null);
  const [dialect, setDialect] = useState<Dialect | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "commit" | null>(null);
  const [over, setOver] = useState(false);

  async function choose(chosen: File) {
    setFile(chosen);
    setName(chosen.name.replace(/\.[^.]+$/, ""));
    setPreview(null);
    setError(null);
    setBusy("preview");
    try {
      const result = await api.previewUpload(chosen);
      setPreview(result);
      setDialect(result.dialect);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read that file.");
    } finally {
      setBusy(null);
    }
  }

  async function commit() {
    if (!file) return;
    setBusy("commit");
    setError(null);
    try {
      const created = await api.createDataset(workspaceId, projectId, file, { name, dialect });
      reset();
      onCommitted(created.version.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The upload failed.");
    } finally {
      setBusy(null);
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setDialect(null);
    setError(null);
    if (input.current) input.current.value = "";
  }

  if (!file) {
    return (
      <div
        className={over ? "drop over" : "drop"}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          const dropped = event.dataTransfer.files[0];
          if (dropped) void choose(dropped);
        }}
      >
        <p style={{ margin: 0 }}>Drop a file here, or</p>
        <p style={{ margin: "10px 0 0" }}>
          <button type="button" onClick={() => input.current?.click()}>
            choose a file
          </button>
        </p>
        <p className="faint" style={{ marginBottom: 0, fontSize: 12 }}>
          CSV, TSV, Parquet, XLSX or JSON — up to 500 MB.
        </p>
        <input
          ref={input}
          type="file"
          hidden
          onChange={(event) => {
            const chosen = event.target.files?.[0];
            if (chosen) void choose(chosen);
          }}
        />
      </div>
    );
  }

  return (
    <div className="card stack">
      <div className="row">
        <strong>{file.name}</strong>
        <span className="faint">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
        <div style={{ flex: 1 }} />
        <button type="button" onClick={reset} disabled={busy !== null}>
          Cancel
        </button>
      </div>

      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      {busy === "preview" ? <p className="muted">Reading the first rows…</p> : null}

      {preview ? (
        <>
          {preview.warnings.map((warning) => (
            <div className="banner" key={warning}>
              {warning}
            </div>
          ))}

          <div className="row">
            <label className="stack" style={{ gap: 4 }}>
              <span className="faint">Dataset name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>

            <span className="pill">{preview.format}</span>

            {dialect ? (
              <>
                <label className="stack" style={{ gap: 4 }}>
                  <span className="faint">Delimiter</span>
                  <select
                    value={dialect.delimiter}
                    onChange={(event) =>
                      setDialect({ ...dialect, delimiter: event.target.value })
                    }
                  >
                    <option value=",">, comma</option>
                    <option value=";">; semicolon</option>
                    <option value="\t">⇥ tab</option>
                    <option value="|">| pipe</option>
                  </select>
                </label>

                <label className="stack" style={{ gap: 4 }}>
                  <span className="faint">Encoding</span>
                  <select
                    value={dialect.encoding}
                    onChange={(event) => setDialect({ ...dialect, encoding: event.target.value })}
                  >
                    <option value="utf-8">utf-8</option>
                    <option value="utf-8-sig">utf-8 (BOM)</option>
                    <option value="cp1252">cp1252 (Windows)</option>
                    <option value="latin-1">latin-1</option>
                  </select>
                </label>

                <label className="row" style={{ gap: 6, alignSelf: "flex-end" }}>
                  <input
                    type="checkbox"
                    checked={dialect.has_header}
                    onChange={(event) =>
                      setDialect({ ...dialect, has_header: event.target.checked })
                    }
                  />
                  <span>First row is a header</span>
                </label>
              </>
            ) : (
              <span className="faint">
                This format carries its own layout — nothing to confirm.
              </span>
            )}
          </div>

          <div className="grid-wrap" style={{ maxHeight: 260 }}>
            <table className="grid">
              <thead>
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column}>
                      <span className="colhead">
                        <span className="name">{column}</span>
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.sample_rows.slice(0, 20).map((row, index) => (
                  // Sample rows have no identity of their own — they are a
                  // slice of a file, not records — so the index is the key.
                  // eslint-disable-next-line react/no-array-index-key
                  <tr key={index}>
                    {row.map((cell, cellIndex) => (
                      <td key={preview.columns[cellIndex] ?? cellIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="faint" style={{ fontSize: 12, margin: 0 }}>
            Column types are not shown here on purpose: they are worked out by scanning the whole
            file after this is committed (FR-B.3), and you can correct them from the grid.
          </p>

          <div className="row">
            <button className="primary" type="button" onClick={commit} disabled={busy !== null}>
              {busy === "commit" ? "Uploading…" : "Confirm and upload"}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
