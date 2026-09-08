"use client";

import { useEffect, useRef, useState } from "react";

import { Ellipsis } from "@/components/Ellipsis";
import { CloudUpload } from "@/components/Icon";
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
  onCommitted,
}: {
  onCommitted: (datasetId: string) => void;
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

  /**
   * Warn before a navigation that would throw away an upload in flight.
   *
   * Gate 2 timed the 480 MB fixture at 28 seconds end to end. For all of that
   * time a stray click on a link, a middle-click, or a reflexive Ctrl+R
   * cancelled the whole thing with no warning and nothing to resume from — the
   * bytes are gone and the transaction never committed, so the user starts
   * again from the file picker.
   *
   * Only while `busy === "commit"`. Choosing a file, reading its first
   * megabyte, or sitting on the confirmation screen costs nothing to redo, and
   * a browser that questions every navigation is one people learn to dismiss
   * without reading — which would spend the warning exactly when it matters.
   *
   * The browser decides the wording; `preventDefault` is the entire modern API.
   * Returning a string is the legacy form and is ignored.
   */
  useEffect(() => {
    if (busy !== "commit") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

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
      setError(
        cause instanceof Error ? cause.message : "Could not read that file.",
      );
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
      const created = await api.createDataset(file, {
        name,
        dialect,
        onProgress: setSent,
      });
      reset();
      onCommitted(created.dataset.id);
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
        /* The mockup makes the whole zone the target and draws no button
           inside it. A `<div>` that takes a click is only half a control, so
           the other half is here: a role, a tab stop, and the two keys a
           button answers to. Without these the only way to upload would be to
           own a mouse — and `choose a file`, the button this replaces, was
           reachable from the keyboard. */
        role="button"
        tabIndex={0}
        aria-label="Upload a new dataset"
        onClick={() => input.current?.click()}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          // Space scrolls the page otherwise, which is what it does on a
          // `<div>` and not what it does on a button.
          event.preventDefault();
          input.current?.click();
        }}
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
        <span className="disc">
          <CloudUpload size={28} />
        </span>
        <div>
          {/* The `choose a file` button that used to sit here is gone: the
              zone around it does the same job over a far larger target, and
              two nested controls would give the same action two tab stops. */}
          <h2>Upload a new dataset</h2>
          <p className="lede">
            {/* A non-breaking space, so a narrow column never wraps the number
                away from its unit. */}
            CSV, TSV, Parquet, XLSX or JSON. Up to 500&nbsp;MB.
          </p>
        </div>
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
      {/* The file, said once. The format pill used to sit among the controls
          below, between the name field and the delimiter — reading as a fourth
          thing to set. It is not a setting; it is a fact about the file, so it
          belongs beside the file's name. */}
      <div className="confirm-head">
        {/* Cut, not wrapped, with the whole name in `title` — the same bargain
            the grid cells and the account button make. */}
        <Ellipsis as="strong" className="filename">
          {file.name}
        </Ellipsis>
        {preview ? <span className="pill tag">{preview.format}</span> : null}
        <span className="faint">{megabytes(file.size)}&nbsp;MB</span>
        <div className="grow" />
        <button type="button" onClick={reset} disabled={busy !== null}>
          Cancel
        </button>
      </div>

      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      {busy === "preview" ? (
        <p className="muted">Reading the first rows…</p>
      ) : null}

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
          {/* One row, one baseline.
              Every control here used to sit in a `.row` with its own label
              stacked above it, so the four of them landed on four different
              vertical positions — the name field low, the format pill floating
              mid-height, the two selects higher, the checkbox higher still. A
              form whose fields do not line up reads as unfinished before
              anybody has read a word of it.

              A grid with `align-items: end` puts every control on the same
              bottom edge regardless of how tall its label is. */}
          <div className="confirm-controls">
            <label className="labelled">
              <span className="caps">Dataset name</span>
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

            {dialect ? (
              <>
                <label className="labelled">
                  <span className="caps">Delimiter</span>
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

                <label className="labelled">
                  <span className="caps">Encoding</span>
                  <select
                    value={dialect.encoding}
                    onChange={(event) =>
                      setDialect({ ...dialect, encoding: event.target.value })
                    }
                  >
                    <option value="utf-8">utf-8</option>
                    <option value="utf-8-sig">utf-8 (BOM)</option>
                    <option value="cp1252">cp1252 (Windows)</option>
                    <option value="latin-1">latin-1</option>
                  </select>
                </label>

                {/* Its own box rather than a bare checkbox on the panel:
                    the two selects beside it are boxes, and a control that is
                    the odd one out looks like an afterthought. */}
                <label className="check">
                  <input
                    type="checkbox"
                    checked={dialect.has_header}
                    onChange={(event) =>
                      setDialect({
                        ...dialect,
                        has_header: event.target.checked,
                      })
                    }
                  />
                  <span>First row is a header</span>
                </label>
              </>
            ) : (
              <span className="faint self-end">
                This format carries its own layout. Nothing to confirm.
              </span>
            )}
          </div>

          <div className="grid-wrap capped">
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
                      <td key={preview.columns[cellIndex] ?? cellIndex}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* A paragraph explaining why no column types are shown stood here
              until the owner removed it. The reason it gave is still true and
              still recorded — `IngestPreviewResponse` in `api/schemas.py` says
              it, and FR-B.3 requires it — but it was answering a question
              nobody on this screen had asked yet. */}

          <div className="row">
            <button
              className="primary"
              type="button"
              onClick={commit}
              disabled={busy !== null}
            >
              {busy === "commit" ? "Uploading…" : "Confirm and upload"}
            </button>
          </div>

          {busy === "commit" ? (
            <UploadProgress sent={sent} bytes={file.size} />
          ) : null}
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
function UploadProgress({
  sent,
  bytes,
}: {
  sent: number | null;
  bytes: number;
}) {
  const transferring = sent !== null && sent < 1;

  return (
    <div className="stack">
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
      <span className="faint hint" aria-live="polite">
        {transferring
          ? `Sending ${megabytes(bytes * (sent ?? 0))} of ${megabytes(bytes)} MB`
          : "Sent. Reading every row to work out the column types. This is the slow part."}
      </span>
    </div>
  );
}
