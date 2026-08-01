"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, api } from "@/lib/api";

/**
 * Sign in or register (FR-A.1).
 *
 * Registration is on the same screen rather than behind a second route: at this
 * stage every user is their first user, and a login form that offers no way in
 * is the emptiest of empty states (§14.5).
 *
 * The failure message is deliberately identical for a wrong password and an
 * unknown address. §13.9 records that member-adding may reveal registration
 * status to a workspace owner; login is public and unauthenticated, so it holds
 * to the stricter standard and reveals nothing.
 */
export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await api.login(email, password);
      else await api.register(email, password);
      router.push("/");
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "Those credentials did not work."
          : cause instanceof Error
            ? cause.message
            : "Something went wrong.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card narrow stack" onSubmit={submit}>
        <h1>DataCanvas</h1>
        <p className="muted tight">
          {mode === "login" ? "Sign in to continue." : "Create an account."}
        </p>

        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}

        <label className="labelled">
          <span className="faint">Email</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            // An address is not prose. Left on, the browser underlines most of
            // them in red and offers corrections for a string it cannot know
            // anything about.
            spellCheck={false}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="labelled">
          <span className="faint">Password</span>
          <input
            type="password"
            name="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? 12 : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {mode === "register" ? (
            <span className="faint hint">
              At least 12 characters.
            </span>
          ) : null}
        </label>

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
        </button>

        {/* A button that looks like a link, because it changes this form rather
            than going anywhere. The look is a class rather than three inline
            declarations — it is the same affordance the rest of the app spends
            `--accent` on, and it has to move when that token does. */}
        <button
          type="button"
          className="linkish"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Create an account instead" : "I already have an account"}
        </button>
      </form>
    </div>
  );
}
