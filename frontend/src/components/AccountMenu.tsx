"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { type Me, api } from "@/lib/api";

/**
 * Who you are, and how to stop being them (FR-A.1, FR-A.2).
 *
 * This closes a **P0 requirement that had no surface at all**. FR-A.2 —
 * *"Sesi pengguna dapat dicabut (logout, logout semua perangkat)"* — was
 * implemented end to end in the backend (one `Session` row per device, tokens
 * hashed, both routes live) and then never given a button. From where the user
 * stands that is not an unpolished feature; it is a missing one. The only way
 * to sign out was to delete the cookie by hand in DevTools, which is not a
 * thing anyone can be asked to do on a shared machine.
 *
 * The email sits **on the button, not only inside the menu**. The usual pattern
 * is an avatar circle, but that pattern assumes one account per person. The
 * question this control exists to answer — *which account am I in?* — has to be
 * answerable without a click, because uploading into the wrong account is a
 * real mistake with real cleanup, and nothing else on screen would catch it.
 *
 * **The workspace is deliberately not named here.** It was, for a day. Every
 * account gets exactly one workspace at registration and there is no route to
 * create a second, so the line read `Personal workspace · owner` for every user
 * alive — identical, unchangeable, and therefore not information. Worse, naming
 * it here while the header named the *project* made the two read as the same
 * thing, and the first person to see it asked which was which.
 *
 * The concept stays in the data model, where it separates policy from work
 * (§7) and carries every authorization decision (INV-7). It just stops being a
 * word the user has to place. If invitations ever land, one workspace becomes
 * several, and *that* is when a name earns a place on screen — not before.
 */
export function AccountMenu({ me }: { me: Me }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocument = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocument);
    return () => document.removeEventListener("mousedown", onDocument);
  }, [open]);

  async function signOut(everywhere: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (everywhere) await api.logoutAll();
      else await api.logout();
      // `replace`, not `push`: leaving a signed-out session on the back stack
      // invites the browser to render it again from cache.
      router.replace("/login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not sign out.");
      setBusy(false);
    }
  }

  return (
    <div ref={box} style={{ position: "relative" }}>
      <button
        type="button"
        className="picker account"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
        title={me.user.email}
      >
        <span className="account-email">{me.user.email}</span> <span aria-hidden>▾</span>
      </button>

      {open ? (
        <div className="menu right" role="menu">
          <div className="menu-head">
            <strong>{me.user.email}</strong>
          </div>

          {error ? (
            <div className="banner error" style={{ margin: "0 4px 6px" }} role="alert">
              {error}
            </div>
          ) : null}

          <div className="menu-sep" />

          <button
            type="button"
            role="menuitem"
            className="menu-item"
            disabled={busy}
            onClick={() => void signOut(false)}
          >
            Sign out
          </button>
          {/* The other half of FR-A.2. One line, and the requirement is whole. */}
          <button
            type="button"
            role="menuitem"
            className="menu-item"
            disabled={busy}
            onClick={() => void signOut(true)}
          >
            Sign out on all devices
          </button>
        </div>
      ) : null}
    </div>
  );
}
