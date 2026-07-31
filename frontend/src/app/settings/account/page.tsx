"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Shell } from "@/components/Shell";
import { ApiError, type Me, type UserSession, api } from "@/lib/api";

/**
 * The account page (FR-A.1, FR-A.2, OWASP Session Management).
 *
 * Split from the header dropdown on purpose. A dropdown is a launcher: it
 * holds identity and the one action people take often. Anything that needs a
 * form, a list, or a sentence of explanation belongs on a page — a popup that
 * has to scroll is the wrong shape for its contents.
 *
 * What is deliberately absent, because the roster of "things a SaaS account
 * page usually has" would otherwise smuggle them in:
 *
 * * **Billing / plan** — §19 names billing as the worked example of scope creep
 *   justified by "we might go external one day" (R-3).
 * * **MFA / SSO** — FR-A.7, priority P3. §16 waits for a tenant to ask.
 * * **Members / invitations** — that is a workspace surface, and the workspace
 *   is deliberately unnamed in this UI.
 * * **Delete account** — in no requirement.
 */
export default function AccountPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMe(await api.me());
      setSessions(await api.sessions());
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not load your account.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Shell>
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  return (
    <Shell me={me}>
      <div>
        <h1>Account</h1>

        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}

        {me ? (
          <>
            <h2>Signed in as</h2>
            <div className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong className="mono">{me.user.email}</strong>
                <span className="faint">
                  since {new Date(me.user.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>

            <PasswordSection onChanged={() => void load()} />
            <SessionSection
              sessions={sessions}
              onChanged={() => void load()}
              onSignedOut={() => router.replace("/login")}
            />
          </>
        ) : null}
      </div>
    </Shell>
  );
}

/**
 * Changing a password from inside a live session.
 *
 * The current password is asked for even though the caller is already
 * authenticated. It looks redundant and is not: it is what stops a borrowed
 * unlocked laptop from becoming a permanent account takeover.
 *
 * The consequence — every other session ends — is stated *before* the button,
 * not reported after. A security action whose effects you learn about
 * afterwards is one people stop trusting.
 */
function PasswordSection({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && next !== confirm;

  /**
   * Ties the mismatch message to the field it is about.
   *
   * It was rendered as a sibling `<span>`, which puts it next to the input on
   * screen and nowhere at all for anyone who reaches the input by keyboard: the
   * field announced itself as valid and the reason the submit button had gone
   * dead was written in a colour they may not be able to see (NFR-UX.3).
   */
  const mismatchId = useId();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const result = await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(
        result.revoked_sessions === 0
          ? "Password changed. No other sessions were signed in."
          : `Password changed. ${result.revoked_sessions} other ${
              result.revoked_sessions === 1 ? "session was" : "sessions were"
            } signed out.`,
      );
      onChanged();
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "That is not your current password."
          : cause instanceof Error
            ? cause.message
            : "Could not change the password.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>Password</h2>
      <form className="card stack" onSubmit={submit}>
        {/* The card fills the page; the inputs do not. A password box the width
            of a 1900px monitor is not "fuller", it is harder to use. */}
        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}
        {done ? (
          <div className="banner ok" role="status">
            {done}
          </div>
        ) : null}

        <label className="stack field" style={{ gap: 4 }}>
          <span className="faint">Current password</span>
          <input
            type="password"
            name="current-password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </label>

        <label className="stack field" style={{ gap: 4 }}>
          <span className="faint">New password</span>
          <input
            type="password"
            name="new-password"
            autoComplete="new-password"
            required
            minLength={12}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <span className="faint" style={{ fontSize: 12 }}>
            At least 12 characters.
          </span>
        </label>

        {/* The message sits outside the `<label>` on purpose. Inside it, its
            text would be swallowed into the input's accessible *name* — so the
            field would introduce itself as "Confirm new password These do not
            match" — and then be read a second time as its description. */}
        <div className="stack field" style={{ gap: 4 }}>
          <label className="stack" style={{ gap: 4 }}>
            <span className="faint">Confirm new password</span>
            <input
              type="password"
              name="confirm-password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              aria-invalid={mismatch}
              aria-describedby={mismatch ? mismatchId : undefined}
            />
          </label>
          {/* Rendered whether or not it says anything: a live region has to
              exist before the text arrives, or the change lands in an element
              nothing is watching. Polite, because it corrects what is being
              typed rather than interrupting it. */}
          <span id={mismatchId} className="field-error" aria-live="polite">
            {mismatch ? "These do not match." : ""}
          </span>
        </div>

        <p className="faint" style={{ margin: 0, fontSize: 12 }}>
          Changing your password signs out every other device. This one stays signed in.
        </p>

        <div className="row">
          <button className="primary" type="submit" disabled={busy || mismatch}>
            {busy ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </>
  );
}

/**
 * Active sessions (OWASP Session Management).
 *
 * OWASP asks that a user be able to see their live sessions — address, client,
 * when it started, when it was last used — and end any of them remotely. Every
 * column that needs has been on `user_session` since Phase 1; nothing but the
 * query and this list was missing.
 *
 * The bulk action lives here rather than in the dropdown, and that is the
 * point. "Sign out everywhere" in a two-item menu is a blind action sitting one
 * line below one that reads almost the same. Beside the list it is an informed
 * one, and its confirmation (NFR-UX.1) can say what it will actually end.
 */
function SessionSection({
  sessions,
  onChanged,
  onSignedOut,
}: {
  sessions: UserSession[];
  onChanged: () => void;
  onSignedOut: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * The one session whose row is currently asking before it acts.
   *
   * `Sign out on all devices` got its confirmation on 2026-07-31, and the
   * comment recording NFR-UX.1 / UX-7 was written thirty lines below a per-row
   * button that had none — one click, one remote session gone, nothing to undo
   * it with. The rule does not distinguish between ending five sessions and
   * ending one; a device you did not mean to sign out has to be signed back in
   * from wherever it is, which may not be where you are.
   */
  const [confirmingOne, setConfirmingOne] = useState<string | null>(null);

  const others = sessions.filter((session) => !session.is_current).length;

  async function revoke(id: string) {
    setBusy(id);
    setError(null);
    try {
      await api.revokeSession(id);
      setConfirmingOne(null);
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not end that session.");
    } finally {
      setBusy(null);
    }
  }

  async function revokeAll() {
    setBusy("all");
    setError(null);
    try {
      await api.logoutAll();
      onSignedOut();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not sign out everywhere.");
      setBusy(null);
    }
  }

  return (
    <>
      <h2>Where you are signed in</h2>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="card">
        <table className="plain">
          <thead>
            <tr>
              <th scope="col">Device</th>
              <th scope="col">Address</th>
              <th scope="col">Last active</th>
              {/* The action column has no visible heading — a word above two
                  buttons would be noise. It still needs one for anyone reading
                  the table through its headers, hence a named but hidden th
                  rather than an empty cell announcing "blank". */}
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.id}>
                <td>
                  {describeClient(session.user_agent)}
                  {session.is_current ? (
                    <span className="pill ok" style={{ marginLeft: 8 }}>
                      this device
                    </span>
                  ) : null}
                  <div className="faint" style={{ fontSize: 11 }}>
                    started {new Date(session.created_at).toLocaleString()}
                  </div>
                </td>
                <td className="mono faint">{session.ip_created ?? "unknown"}</td>
                <td className="faint">{new Date(session.last_seen_at).toLocaleString()}</td>
                <td style={{ textAlign: "right" }}>
                  {/* The current session is not offered here. Ending it is
                      "Sign out", and dressing that up as revoking a remote
                      device would surprise whoever clicked. */}
                  {session.is_current ? null : confirmingOne === session.id ? (
                    // The question names the device it is about, because the
                    // row it sits in is the only thing that would otherwise say
                    // which of several this is (W-2).
                    <span className="row confirm-inline">
                      <span className="faint">End {describeClient(session.user_agent)}?</span>
                      <button
                        type="button"
                        className="primary"
                        disabled={busy !== null}
                        onClick={() => void revoke(session.id)}
                      >
                        {busy === session.id ? "Ending…" : "Yes, end it"}
                      </button>
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => setConfirmingOne(null)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => setConfirmingOne(session.id)}
                    >
                      End session
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* NFR-UX.1 / UX-7: no destructive action without a confirmation. The
          first version of this shipped as a bare menu item with none, one line
          below an item that reads almost identically. */}
      {confirming ? (
        <div className="banner" role="alert">
          <strong>Sign out everywhere?</strong>{" "}
          <span className="muted">
            {others === 0
              ? "This will sign out this device."
              : `This will end ${others} other ${
                  others === 1 ? "session" : "sessions"
                } and sign out this device too.`}{" "}
            You will need to sign in again.
          </span>
          <div className="row" style={{ marginTop: 10 }}>
            <button
              type="button"
              className="primary"
              disabled={busy !== null}
              onClick={() => void revokeAll()}
            >
              {busy === "all" ? "Signing out…" : "Yes, sign out everywhere"}
            </button>
            <button type="button" disabled={busy !== null} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button type="button" onClick={() => setConfirming(true)}>
          Sign out on all devices
        </button>
      )}
    </>
  );
}

/**
 * A user agent, in words a person recognises.
 *
 * Deliberately crude. A full parser is a dependency and a maintenance burden
 * for a string whose only job here is to help someone answer "is that me?" —
 * and the address and timestamp beside it carry most of that weight anyway.
 * Anything unrecognised is shown as-is rather than guessed at.
 */
function describeClient(userAgent: string | null): string {
  if (!userAgent) return "Unknown client";

  const browser =
    /Edg\//.test(userAgent) ? "Edge"
    : /OPR\//.test(userAgent) ? "Opera"
    : /Chrome\//.test(userAgent) ? "Chrome"
    : /Safari\//.test(userAgent) ? "Safari"
    : /Firefox\//.test(userAgent) ? "Firefox"
    : null;

  const platform =
    /Windows/.test(userAgent) ? "Windows"
    : /Android/.test(userAgent) ? "Android"
    : /iPhone|iPad/.test(userAgent) ? "iOS"
    : /Mac OS X/.test(userAgent) ? "macOS"
    : /Linux/.test(userAgent) ? "Linux"
    : null;

  if (browser && platform) return `${browser} · ${platform}`;
  if (browser) return browser;
  if (platform) return platform;
  return userAgent.slice(0, 40);
}
