"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { type Me, api } from "@/lib/api";

/**
 * Who you are, and the way into everything about your account (FR-A.1, A.2).
 *
 * ## Why this is a disclosure, not a `menu`
 *
 * The first version declared `role="menu"`, `role="menuitem"` and
 * `aria-haspopup="menu"`. That was wrong, and wrong in the direction that does
 * the most damage: ARIA's `menu` role means an *application* menu, and
 * declaring it promises arrow-key navigation, Home/End, first-character
 * typeahead and composite focus management. This widget implemented none of
 * them, so it announced a contract to assistive technology and then broke it —
 * worse than staying silent, because a screen-reader user is told to expect
 * behaviour that is not there.
 *
 * MDN says it plainly for navigation: *do not use the menu role*. The WAI-ARIA
 * Authoring Practices and Adrian Roselli both point at the **disclosure**
 * pattern instead — `aria-expanded` on a real button, native links and buttons
 * inside, no invented semantics. That is all this needs.
 *
 * ## What was missing regardless of the role
 *
 * The popup could only be closed by clicking outside it. A keyboard user could
 * open it and get stuck: Tab walked past the panel into the page behind, and
 * the panel stayed open with no way to dismiss it. Escape, focus moving into
 * the panel on open, and focus returning to the trigger on close are the
 * baseline for *any* popup — this had none of the three.
 *
 * ## Why the email is on the button
 *
 * The usual pattern is an avatar circle, but that assumes one account per
 * person. *Which account am I in?* has to be answerable without a click,
 * because uploading into the wrong account is a real mistake with real cleanup
 * and nothing else on screen would catch it.
 *
 * The workspace is deliberately not named anywhere — see the commit that
 * removed it. One workspace per account, no route to create a second, so the
 * line was identical for every user alive.
 */
export function AccountMenu({ me }: { me: Me }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();

  /** Close and put focus back where it came from. */
  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus();
  }, []);

  // Escape, and an outside click. Escape restores focus to the trigger; a click
  // elsewhere does not, because the user has already chosen where to go and
  // yanking focus back would fight them.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(true);
    };
    const onDocument = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) close(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDocument);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDocument);
    };
  }, [open, close]);

  // Focus the first control when the panel opens, so the next Tab continues
  // inside it rather than behind it.
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, [open]);

  async function signOut() {
    setBusy(true);
    setError(null);
    try {
      await api.logout();
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
        ref={trigger}
        type="button"
        className="picker account"
        onClick={() => (open ? close(true) : setOpen(true))}
        aria-expanded={open}
        aria-controls={panelId}
        title={me.user.email}
      >
        <span className="account-email">{me.user.email}</span> <span aria-hidden>▾</span>
      </button>

      {open ? (
        <div ref={panel} id={panelId} className="menu right">
          <div className="menu-head">
            <strong>{me.user.email}</strong>
          </div>

          {error ? (
            <div className="banner error" style={{ margin: "0 4px 6px" }} role="alert">
              {error}
            </div>
          ) : null}

          <div className="menu-sep" />

          {/* Everything that needs a form or a list lives on the page, not in
              here. A popup that has to scroll is the wrong shape for its
              contents. */}
          <Link href="/settings/account" className="menu-item" onClick={() => close(false)}>
            Account settings
          </Link>

          <button type="button" className="menu-item" disabled={busy} onClick={() => void signOut()}>
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
