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
    api: { ...actual.api, me: vi.fn(), projects: vi.fn(), datasets: vi.fn(), samples: vi.fn() },
  };
});

const ME: Me = {
  user: { id: "user-1", email: "someone@example.com", created_at: "2026-01-01T00:00:00Z" },
  workspaces: [
    {
      id: "workspace-1",
      name: "Personal",
      is_personal: true,
      created_at: "2026-01-01T00:00:00Z",
      role: "owner",
    },
  ],
};

beforeEach(() => {
  vi.mocked(api.projects).mockResolvedValue([]);
  vi.mocked(api.datasets).mockResolvedValue([]);
  vi.mocked(api.samples).mockResolvedValue([]);
});

describe("the home page when it cannot load", () => {
  it("replaces the body instead of instructing what it has disabled", async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError(500, "500 Internal Server Error"));

    render(<HomePage />);

    await screen.findByRole("button", { name: "Try again" });
    expect(screen.queryByText("Start by adding data")).not.toBeInTheDocument();
    expect(screen.queryByText(/Confirm how it reads/)).not.toBeInTheDocument();
  });

  it("says what happened without quoting a status code at the user", async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError(500, "500 Internal Server Error"));

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
    expect(await screen.findByText("Start by adding data")).toBeInTheDocument();
  });
});
