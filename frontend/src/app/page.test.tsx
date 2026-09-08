import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import { ApiError, type Me, api } from "@/lib/api";

/**
 * A screen that cannot load must not go on giving instructions.
 *
 * When `/auth/me` answered 500 this page still rendered "Start by adding data"
 * and its three numbered steps — with no drop zone, no samples and no account
 * menu, because every one of those is gated on the identity it had just failed
 * to fetch. It told someone to add data, removed every means of doing so, and
 * left no way out. Above all that sat the words `500 Internal Server Error`.
 *
 * That headline and those steps are both gone from the product now, for
 * unrelated reasons. The shape they made is what this file guards, so the
 * assertions below moved to the affordance that is still there.
 *
 * §14.5 already forbids this shape. The rule was written about the empty state
 * — *a list with no way in is not orientation, it is a dead end* — and nobody
 * had held the error state against it.
 */

// The router object is built once and handed back on every call. Next's own
// `useRouter` is stable across renders; a mock that returns a fresh object each
// time changes the identity of `load`'s `useCallback`, which re-fires the effect
// that calls it — the page then reloads forever and never leaves "Loading…".
vi.mock("next/navigation", () => {
  const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
  return { useRouter: () => router };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      datasets: vi.fn(),
      samples: vi.fn(),
      deleteDataset: vi.fn(),
    },
  };
});

const ME: Me = {
  user: {
    id: "user-1",
    email: "someone@example.com",
    created_at: "2026-01-01T00:00:00Z",
  },
};

beforeEach(() => {
  vi.mocked(api.datasets).mockResolvedValue([]);
  vi.mocked(api.samples).mockResolvedValue([]);
});

describe("the home page when it cannot load", () => {
  it("replaces the body instead of instructing what it has disabled", async () => {
    vi.mocked(api.me).mockRejectedValue(
      new ApiError(500, "500 Internal Server Error"),
    );

    render(<HomePage />);

    await screen.findByRole("button", { name: "Try again" });

    // These two used to name the headline and the numbered steps that the
    // broken screen went on rendering. Neither string exists anywhere now —
    // the steps were removed, and the headline went with the empty-account
    // layout — so asserting their absence had become a test that cannot fail.
    //
    // What the rule is actually about is *instructions the page has already
    // disabled*, and the drop zone is the one that survived. It is also the
    // right thing to check: it is the affordance the old screen told people to
    // use while removing every means of using it.
    expect(
      screen.queryByRole("button", { name: "Upload a new dataset" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Try one of these/ }),
    ).toBeNull();
  });

  it("says what happened without quoting a status code at the user", async () => {
    vi.mocked(api.me).mockRejectedValue(
      new ApiError(500, "500 Internal Server Error"),
    );

    render(<HomePage />);

    await screen.findByRole("button", { name: "Try again" });
    expect(screen.queryByText(/500/)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/fault on our side/);
  });

  it("recovers when the retry succeeds", async () => {
    const user = userEvent.setup();
    vi.mocked(api.me)
      .mockRejectedValueOnce(new ApiError(500, "500 Internal Server Error"))
      .mockResolvedValue(ME);

    render(<HomePage />);

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    // The way in is back, which is the whole point of offering the button.
    //
    // Asserted on the drop zone rather than on a headline. The headline was
    // `Start by adding data`, which existed only on the empty-account layout —
    // and that layout is gone: the page has one shape now. The drop zone is
    // what "the way in" actually means, and it is on the page either way.
    expect(
      await screen.findByRole("button", { name: "Upload a new dataset" }),
    ).toBeInTheDocument();
  });
});

/**
 * Deleting a dataset removes the file, not a row (FR-B.6, NFR-PRIV.3), and
 * there is no undo anywhere in this product. NFR-UX.1 therefore applies at full
 * strength, and these assertions are about the *gap* between the click and the
 * deletion rather than about the deletion.
 *
 * The route has existed since Phase 2 with nothing calling it. That is the
 * safer half of the failure and it is over now, so the guard has to arrive with
 * the button rather than after it.
 */
describe("deleting a dataset", () => {
  const DATASET = {
    id: "ds-1",
    name: "penjualan_q3.csv",
    created_at: "2026-01-01T00:00:00Z",
    row_count: 300,
    column_count: 5,
    schema_version_no: 1,
  };

  beforeEach(() => {
    vi.mocked(api.me).mockResolvedValue(ME);
    vi.mocked(api.datasets).mockResolvedValue([DATASET]);
  });

  it("asks before it deletes anything, and names the file it would delete", async () => {
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(
      await screen.findByRole("button", { name: "Delete penjualan_q3.csv" }),
    );

    expect(api.deleteDataset).not.toHaveBeenCalled();
    // A grid of cards is several near-identical questions; the name is what
    // makes this one answerable (W-2).
    expect(screen.getByRole("alert")).toHaveTextContent("penjualan_q3.csv");
  });

  it("deletes on confirmation, and reloads the list rather than guessing at it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.deleteDataset).mockResolvedValue(undefined);
    render(<HomePage />);

    await user.click(
      await screen.findByRole("button", { name: "Delete penjualan_q3.csv" }),
    );
    // `Delete file`, not `Delete`. The consequence is on the button because the
    // card has no room for a sentence saying it.
    await user.click(screen.getByRole("button", { name: "Delete file" }));

    expect(api.deleteDataset).toHaveBeenCalledWith("ds-1");
    // Two calls: the first render, and again once the server confirmed. The
    // card is not removed locally — a list that edits itself and a server that
    // refused have no way of finding out they disagree.
    expect(vi.mocked(api.datasets).mock.calls.length).toBeGreaterThan(1);
  });

  it("does nothing at all when the question is declined", async () => {
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(
      await screen.findByRole("button", { name: "Delete penjualan_q3.csv" }),
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(api.deleteDataset).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the card openable, and stops offering that while it is asking", async () => {
    // The overlay that makes the whole card a link is removed during the
    // question. Otherwise a click aimed at `Cancel` and landing a few pixels
    // wide navigates away from the thing being decided.
    const user = userEvent.setup();
    render(<HomePage />);

    expect(
      await screen.findByRole("link", { name: "Open penjualan_q3.csv" }),
    ).toHaveAttribute("href", "/datasets/ds-1");

    await user.click(
      screen.getByRole("button", { name: "Delete penjualan_q3.csv" }),
    );

    expect(
      screen.queryByRole("link", { name: "Open penjualan_q3.csv" }),
    ).toBeNull();
  });
});
