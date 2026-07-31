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

  /**
   * Fraction of the file that has left the browser, or `null` before sending
   * starts.
   *
   * Reaching 1 does not mean the upload is done — it means the bytes are gone
   * and the server has begun the part nobody can see: normalising to Parquet
   * and inferring a type for every column by reading every row (FR-B.3). On the
   * 480 MB fixture that second half is most of the 28 seconds. So at 1 the bar
   * stops claiming a number and says what is actually happening.
   */
  const [sent, setSent] = useState<number | null>(null);

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
    setSent(0);
    setError(null);
    try {
      const created = await api.createDataset(workspaceId, projectId, file, {
        name,
        dialect,
        onProgress: setSent,
      });
      reset();
      onCommitted(created.version.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The upload failed.");
    } finally {
      setBusy(null);
      setSent(null);
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setDialect(null);
    setError(null);
    setSent(null);
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
          {/* A non-breaking space, so a narrow column never wraps the number
              away from its unit. */}
          CSV, TSV, Parquet, XLSX or JSON — up to 500&nbsp;MB.
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
        {/* Cut, not wrapped, with the whole name in `title` — the same bargain
            the grid cells and the account button make. */}
        <strong className="ellipsis" title={file.name}>
          {file.name}
        </strong>
        <span className="faint">{megabytes(file.size)}&nbsp;MB</span>
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

      {/* The warnings arrive with the preview response, a second or two after
          the file was chosen and with nothing changing near where the user is
          looking. This is what makes them arrive for somebody not watching that
          spot — and it is outside the `preview` branch below because a live
          region has to be on the page *before* its contents change. Mounted
          together with what it announces, it announces nothing.
          `polite`, not `alert`: they describe how the file will be read, and
          there is still a confirmation step ahead of any of it mattering. */}
      <div aria-live="polite">
        {preview?.warnings.map((warning) => (
          <div className="banner" key={warning}>
            {warning}
          </div>
        ))}
      </div>

      {preview ? (
        <>

          <div className="row">
            <label className="stack" style={{ gap: 4 }}>
              <span className="faint">Dataset name</span>
              {/* `autoComplete="off"`: this is not a field about the person
                  filling it in, and a password manager offering to remember a
                  dataset name is a prompt with no right answer. */}
              <input
                name="dataset-name"
                autoComplete="off"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
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

          {busy === "commit" ? <UploadProgress sent={sent} bytes={file.size} /> : null}
        </>
      ) : null}
    </div>
  );
}

function megabytes(bytes: number): string {
  return (bytes / 1024 / 1024).toFixed(1);
}

/**
 * What is happening during the one operation here that can run for half a
 * minute (NFR-UX.2 asks for an indicator above 500 ms).
 *
 * **Two states, and the split is the whole point.** Sending the bytes is
 * measurable, so it gets a real bar with real numbers. What follows — Parquet
 * normalisation and a full-file type inference (FR-B.3) — is not observable
 * from the browser at all, so the bar stops pretending: it goes indeterminate
 * and the text says which of the two is running.
 *
 * The alternative, and the reason this is written down: let the bar creep to
 * 99% and hold. That reads as "almost done" when the truth is "roughly half
 * done, and the half you cannot see is the slow one" — on the 480 MB fixture,
 * most of the 28 seconds sits after the last byte has left. A progress
 * indicator that asserts a state it cannot observe belongs with the hardcoded
 * privacy pill this project removed for the same reason.
 */
function UploadProgress({ sent, bytes }: { sent: number | null; bytes: number }) {
  const transferring = sent !== null && sent < 1;

  return (
    <div className="stack" style={{ gap: 6 }}>
      <progress
        className="upload-progress"
        max={1}
        // Omitting `value` is what makes a `<progress>` indeterminate, and
        // indeterminate is the truthful rendering of "the server is working and
        // will not tell us how far along it is".
        value={transferring ? sent : undefined}
        aria-label={transferring ? "Upload progress" : "Preparing the dataset"}
      />
      {/* Polite, not assertive: the change from one phase to the next is worth
          announcing, but not worth interrupting whatever is being read. */}
      <span className="faint" style={{ fontSize: 12 }} aria-live="polite">
        {transferring
          ? `Sending ${megabytes(bytes * (sent ?? 0))} of ${megabytes(bytes)} MB`
          : "Sent. Reading every row to work out the column types — this is the slow part."}
      </span>
    </div>
  );
}
