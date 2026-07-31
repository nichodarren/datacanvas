"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

/** Anything the browser will let a user tab to, in DOM order. */
const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])';

/**
 * A button that shows a panel, and every keyboard behaviour that implies.
 *
 * ## Why this exists as one thing
 *
 * The app grew three of these — the account menu, the column picker, and the
 * type picker under a column header — and each one implemented a different
 * subset of the same contract:
 *
 * | | Escape | Click outside | Focus into panel | Focus back to trigger |
 * |---|---|---|---|---|
 * | Account menu | yes | yes | yes | yes |
 * | Column picker | yes | yes | **no** | **no** |
 * | Type picker | **no** | **no** | **no** | **no** |
 *
 * The account menu got all four because a previous session went looking, wrote
 * a long note about why a keyboard user must never be able to open a popup they
 * cannot close, and fixed the one widget in front of it. The other two were the
 * same widget with the same defect, a few hundred lines away.
 *
 * The type picker was the worst of the three and the easiest to miss: it floats
 * over the data, and the only way to dismiss it was to click the header again
 * or pick a type. Clicking anywhere else on the page left it open.
 *
 * So the behaviour lives here, once. A fourth popup gets it by construction
 * rather than by whoever builds it remembering this table.
 *
 * ## Why not `role="menu"`
 *
 * ARIA's `menu` means an *application* menu and promises arrow-key navigation,
 * Home/End, typeahead and composite focus management. Declaring it without
 * implementing it tells assistive technology to expect behaviour that is not
 * there — worse than saying nothing. This is the **disclosure** pattern:
 * `aria-expanded` on a real button, native controls inside, nothing invented.
 */
/**
 * The three element types are parameters so each call site gets refs React will
 * accept without a cast: the type picker's container is a `<th>`, the account
 * menu's is a `<div>`, and a shared `RefObject<HTMLElement>` fits neither.
 */
export function useDisclosure<
  Container extends HTMLElement = HTMLDivElement,
  Trigger extends HTMLElement = HTMLButtonElement,
  Panel extends HTMLElement = HTMLDivElement,
>() {
  const [open, setOpen] = useState(false);

  /** Wraps trigger *and* panel, so "outside" can be asked as one question. */
  const container = useRef<Container | null>(null);
  const trigger = useRef<Trigger | null>(null);
  const panel = useRef<Panel | null>(null);
  const panelId = useId();

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    // Escape restores focus; a click elsewhere does not. The user has already
    // chosen where to go, and pulling focus back would fight them.
    if (restoreFocus) trigger.current?.focus();
  }, []);

  const toggle = useCallback(() => setOpen((current) => !current), []);

  useEffect(() => {
    if (!open) return;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(true);
    };
    const onDocument = (event: MouseEvent) => {
      const root = container.current;
      if (root && !root.contains(event.target as Node)) close(false);
    };

    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDocument);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDocument);
    };
  }, [open, close]);

  // Move focus into the panel so the next Tab continues inside it rather than
  // behind it. Without this a keyboard user opens the panel and their focus is
  // still on the trigger, one Tab away from walking straight past the contents.
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  }, [open]);

  return { open, close, toggle, container, trigger, panel, panelId };
}
