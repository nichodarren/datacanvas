"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ThemePicker } from "@/components/ThemePicker";
import { useDisclosure } from "@/hooks/useDisclosure";
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
 * The panel does not repeat the email. It did, back when the header block also
 * carried the workspace and role and so had something to say; once those went,
 * it was the same string twice, stacked, which reads as carelessness. The
 * button already answers the question, and `title` carries the full address if
 * it truncates — the same bargain the grid cells make.
 *
 * The workspace is deliberately not named anywhere — see the commit that
 * removed it. One workspace per account, no route to create a second, so the
 * line was identical for every user alive.
 */
export function AccountMenu({ me }: { me: Me }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Escape, outside clicks and focus management all live in the hook now. They
  // were written here first, then found missing from the column picker and the
  // type picker — the same widget, the same gap, a few hundred lines away.
  const { open, close, toggle, container, trigger, panel, panelId } = useDisclosure();

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
    <div ref={container} className="anchor">
      <button
        ref={trigger}
        type="button"
        className="picker account"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
        title={me.user.email}
      >
        <span className="account-email">{me.user.email}</span> <span aria-hidden>▾</span>
      </button>

      {open ? (
        <div ref={panel} id={panelId} className="menu right">
          {error ? (
            <div className="banner error compact" role="alert">
              {error}
            </div>
          ) : null}

          {/* Everything that needs a form or a list lives on the page, not in
              here. A popup that has to scroll is the wrong shape for its
              contents. */}
          <Link href="/settings/account" className="menu-item" onClick={() => close(false)}>
            Account settings
          </Link>

          <button type="button" className="menu-item" disabled={busy} onClick={() => void signOut()}>
            {busy ? "Signing out…" : "Sign out"}
          </button>

          {/* The ground belongs to whoever is looking at it, so it belongs to
              the account, so it belongs here — not in a new region of the
              shell. Below the two actions rather than above them: it is a
              preference, and the actions are what people opened this for. */}
          <div className="menu-sep" />
          <ThemePicker />
        </div>
      ) : null}
    </div>
  );
}
