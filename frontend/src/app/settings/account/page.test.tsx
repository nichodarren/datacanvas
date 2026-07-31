import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AccountPage from "@/app/settings/account/page";
import { type Me, type UserSession, api } from "@/lib/api";

/**
 * UX-7 does not have a size threshold.
 *
 * The session of 2026-07-31 found "sign out everywhere" shipping as a bare menu
 * item with no confirmation, called it a violation of NFR-UX.1 / UX-7, moved it
 * here and gave it one. Thirty lines above that fix — in the same component,
 * under the same heading — a per-row `End session` button ended a remote
 * session on a single click with nothing to undo it. The comment recording the
 * rule sits directly beneath the button that broke it.
 *
 * Ending one session is not a smaller act than ending five. It is the same act,
 * aimed, and the device it signs out may be somewhere the user is not.
 */

vi.mock("next/navigation", () => {
  const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
  return { useRouter: () => router };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, me: vi.fn(), sessions: vi.fn(), revokeSession: vi.fn() },
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

/** Fixed timestamps: a fixture that drifts with the clock fails on its own one day. */
const SESSIONS: UserSession[] = [
  {
    id: "session-here",
    created_at: "2026-01-01T09:00:00Z",
    last_seen_at: "2026-01-01T09:30:00Z",
    expires_at: "2026-02-01T09:00:00Z",
    ip_created: "203.0.113.1",
    user_agent: "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
    is_current: true,
  },
  {
    id: "session-elsewhere",
    created_at: "2026-01-01T08:00:00Z",
    last_seen_at: "2026-01-01T08:30:00Z",
    expires_at: "2026-02-01T08:00:00Z",
    ip_created: "203.0.113.9",
    user_agent: "Mozilla/5.0 (iPhone) Safari/605.1",
    is_current: false,
  },
];

beforeEach(() => {
  vi.mocked(api.me).mockResolvedValue(ME);
  vi.mocked(api.sessions).mockResolvedValue(SESSIONS);
  vi.mocked(api.revokeSession).mockResolvedValue(undefined);
});

describe("ending one remote session", () => {
  it("asks before it ends anything", async () => {
    const user = userEvent.setup();
    render(<AccountPage />);

    await user.click(await screen.findByRole("button", { name: "End session" }));

    expect(api.revokeSession).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Yes, end it" })).toBeInTheDocument();
  });

  it("names the device it is about", async () => {
    const user = userEvent.setup();
    render(<AccountPage />);

    await user.click(await screen.findByRole("button", { name: "End session" }));

    // "End this?" beside a table of devices is the one question the row it sits
    // in is answering.
    expect(screen.getByText(/End Safari · iOS\?/)).toBeInTheDocument();
  });

  it("ends the session that was confirmed, and only on confirmation", async () => {
    const user = userEvent.setup();
    render(<AccountPage />);

    await user.click(await screen.findByRole("button", { name: "End session" }));
    await user.click(screen.getByRole("button", { name: "Yes, end it" }));

    expect(api.revokeSession).toHaveBeenCalledExactlyOnceWith("session-elsewhere");
  });

  it("leaves the session alone when the question is declined", async () => {
    const user = userEvent.setup();
    render(<AccountPage />);

    await user.click(await screen.findByRole("button", { name: "End session" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(api.revokeSession).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "End session" })).toBeInTheDocument();
  });

  it("never offers to end the session doing the asking", async () => {
    render(<AccountPage />);
    await screen.findByRole("button", { name: "End session" });

    // Two sessions, one of them current: exactly one button, and the current
    // row is labelled instead.
    expect(screen.getAllByRole("button", { name: "End session" })).toHaveLength(1);
    expect(screen.getByText("this device")).toBeInTheDocument();
  });
});

describe("the confirm-password field", () => {
  it("ties its mismatch message to the input rather than leaving it beside it", async () => {
    const user = userEvent.setup();
    render(<AccountPage />);

    // Anchored, not exact: the "At least 12 characters." hint sits inside the
    // same label and joins the field's accessible name.
    const next = await screen.findByLabelText(/^New password/);
    const confirm = screen.getByLabelText("Confirm new password");
    await user.type(next, "correct horse battery");
    await user.type(confirm, "correct horse batteru");

    expect(confirm).toHaveAccessibleDescription("These do not match.");
    expect(confirm).toBeInvalid();
  });
});
