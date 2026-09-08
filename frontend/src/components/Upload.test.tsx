import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Upload } from "@/components/Upload";
import { type Committed, type IngestPreview, api } from "@/lib/api";

/**
 * The upload has to say what it is doing, and stop saying it once it no longer
 * knows (NFR-UX.2).
 *
 * Gate 2 timed a 480 MB upload at 28 seconds against a 500 ms threshold for
 * showing progress at all, and the screen answered with a button label that
 * never changed. What makes this worth a test rather than a glance is the
 * second half: once the last byte is sent, most of those seconds are still
 * ahead — Parquet normalisation and a full-file type inference the browser
 * cannot see. The tempting fix is a bar that creeps to 99% and waits there,
 * which is a confident claim about a phase nothing is measuring.
 *
 * So the assertion is not "a bar appears". It is: at 100% sent, the indicator
 * **gives up its number** and names the phase instead.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, previewUpload: vi.fn(), createDataset: vi.fn() },
  };
});

const PREVIEW: IngestPreview = {
  format: "csv",
  dialect: {
    delimiter: ",",
    encoding: "utf-8",
    has_header: true,
    confidence: 1,
  },
  columns: ["alpha", "bravo"],
  sample_rows: [["a1", "b1"]],
  partial: true,
  warnings: [],
};

/** Two megabytes, so the reported figures are not all zeroes. */
const FILE = new File(["x".repeat(2 * 1024 * 1024)], "sales.csv", {
  type: "text/csv",
});

function progressBar(): HTMLProgressElement {
  return screen.getByRole("progressbar") as HTMLProgressElement;
}

/** Get to the point where the confirm button exists, and press it. */
async function startUpload(container: HTMLElement) {
  const user = userEvent.setup();
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("the drop zone rendered no file input");

  fireEvent.change(input, { target: { files: [FILE] } });
  await screen.findByRole("button", { name: "Confirm and upload" });
  await user.click(screen.getByRole("button", { name: "Confirm and upload" }));
}

beforeEach(() => {
  vi.mocked(api.previewUpload).mockResolvedValue(PREVIEW);
});

describe("Upload progress", () => {
  it("reports bytes while they are still being sent", async () => {
    let report: ((fraction: number) => void) | undefined;
    vi.mocked(api.createDataset).mockImplementation((_file, options) => {
      report = options.onProgress;
      return new Promise<Committed>(() => {
        // Never settles: this test is about the state *during* the upload.
      });
    });

    const { container } = render(<Upload onCommitted={() => {}} />);
    await startUpload(container);

    await act(async () => report?.(0.5));

    expect(progressBar().value).toBe(0.5);
    expect(screen.getByText(/Sending 1\.0 of 2\.0 MB/)).toBeInTheDocument();
  });

  /**
   * 28 seconds is a long time to lose to a stray click.
   *
   * Gate 2 timed the 480 MB fixture at 28 seconds end to end, and for all of it
   * a link, a middle-click or a reflexive Ctrl+R threw the upload away with no
   * warning and nothing to resume from. The guard is armed only while the bytes
   * are actually moving: a browser that questions every navigation is one people
   * learn to dismiss without reading, which would spend the warning exactly when
   * it matters.
   */
  it("guards against navigating away only while the upload is in flight", async () => {
    vi.mocked(api.createDataset).mockImplementation(
      () => new Promise<Committed>(() => {}),
    );

    const { container } = render(<Upload onCommitted={() => {}} />);

    // Choosing a file and confirming the dialect costs nothing to redo, so
    // nothing is guarded yet.
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the drop zone rendered no file input");
    fireEvent.change(input, { target: { files: [FILE] } });
    await screen.findByRole("button", { name: "Confirm and upload" });

    expect(
      fireEvent(window, new Event("beforeunload", { cancelable: true })),
    ).toBe(true);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Confirm and upload" }));

    // `fireEvent` returns false exactly when something called preventDefault —
    // which is the whole of the modern beforeunload API.
    expect(
      fireEvent(window, new Event("beforeunload", { cancelable: true })),
    ).toBe(false);
  });

  it("stops claiming a number once the bytes are gone", async () => {
    let report: ((fraction: number) => void) | undefined;
    vi.mocked(api.createDataset).mockImplementation((_file, options) => {
      report = options.onProgress;
      return new Promise<Committed>(() => {});
    });

    const { container } = render(<Upload onCommitted={() => {}} />);
    await startUpload(container);

    await act(async () => report?.(1));

    // `position` is -1 exactly when a <progress> has no `value` — the DOM's own
    // word for "indeterminate", and the thing a 99% bar would be lying about.
    expect(progressBar().position).toBe(-1);
    expect(screen.queryByText(/Sending/)).not.toBeInTheDocument();
    expect(screen.getByText(/Reading every row/)).toBeInTheDocument();
  });
});
