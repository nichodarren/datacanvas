"use client";

import { useEffect, useRef } from "react";

import { Ellipsis } from "@/components/Ellipsis";

/**
 * The question asked before something is destroyed.
 *
 * ## Why a dialog and not the banner it replaces
 *
 * This was a `.danger-banner` under the page title, and it was chosen over a
 * popup on the grounds that a page has room to ask properly. It did, until a
 * dataset arrived with a 200-character name: the name went into the middle of a
 * sentence — *Delete **name**? The file goes with it* — with nothing bounding
 * it, so the banner grew wider than the window, the page got a horizontal
 * scrollbar, and the title beside it grew with the page and slid its marquee
 * off the edge of the screen. The banner was the only unbounded box on the
 * page and it dragged everything else out with it.
 *
 * A dialog fixes that by construction rather than by a `max-width` somebody has
 * to remember: it is in the top layer, so its size is not the page's problem,
 * and the name is a line of its own rather than a word inside a sentence.
 *
 * It is also the right shape for the question independently of the bug. The
 * banner asked about an irreversible thing while every control that caused it
 * stayed live behind — you could open a tab, start an upload, or press the same
 * Delete again with the question still on screen.
 *
 * ## `<dialog>`, and what it is doing for us
 *
 * `showModal()` and not a `<div>` with a high z-index. Four behaviours come
 * with it that are individually easy to get wrong and collectively almost never
 * hand-written correctly: focus is trapped inside, Escape closes, everything
 * behind is inert to pointer and screen reader alike, and `::backdrop` is a
 * real paintable layer rather than a fixed div in the stacking order.
 *
 * `role="alertdialog"` on top of that. A `dialog` is a container; an
 * `alertdialog` tells a screen reader this one is interrupting for an answer,
 * which is the whole reason it is on screen.
 *
 * ## Open state stays in React
 *
 * `onCancel` calls `preventDefault()` and then tells the parent, instead of
 * letting the element close itself. Two reasons: the element closing itself
 * would leave `open` true in the parent and the two would disagree about
 * whether the question is being asked, and it gives us somewhere to *refuse* —
 * Escape does nothing while the delete is in flight, because there is nothing
 * left to cancel by then and closing the dialog would only hide a request the
 * user can no longer see the outcome of.
 *
 * ## Cancel takes focus, not Confirm
 *
 * `showModal` focuses the first focusable child by default, and the first one
 * here destroys a file. So focus is placed on Cancel explicitly. The buttons
 * keep their reading order — the action first, the way out second, matching the
 * card — because moving Cancel to the front would fix nothing that focus does
 * not already fix and would make the two confirmations disagree in shape.
 */
export function ConfirmDialog({
  open,
  title,
  name,
  detail,
  confirmLabel,
  busyLabel,
  busy = false,
  error = null,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  /** The question, short and complete without the name: *Delete this dataset?* */
  title: string;
  /** The thing being destroyed. Shown on a line of its own, and it may be long. */
  name: string;
  /** What else goes with it, and that it cannot be taken back. */
  detail: string;
  confirmLabel: string;
  busyLabel: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (!element.open) {
      element.showModal();
      cancel.current?.focus();
    }
  }, [open]);

  // Not rendered at all when closed, rather than rendered and hidden. `Ellipsis`
  // measures the text against the box around it, and a box inside a
  // `display: none` dialog measures zero — a long name would decide it fitted
  // and sit still. Mounting it with the dialog means its first measurement
  // happens against a box that exists.
  if (!open) return null;

  return (
    <dialog
      ref={dialog}
      className="confirm-dialog"
      role="alertdialog"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-detail"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
      // The backdrop is the dialog's own box; the panel inside it is what the
      // pointer lands on anywhere else. Dismissing is the safe direction, so a
      // click outside is allowed to take it.
      onClick={(event) => {
        if (event.target === dialog.current && !busy) onCancel();
      }}
    >
      <div className="confirm-panel">
        <h2 id="confirm-title">{title}</h2>

        {/* On its own line, and this is the fix rather than a nicety. Inside a
            sentence the name has no width of its own to be given, so it takes
            whatever it needs and the box around it follows. */}
        <Ellipsis className="confirm-subject">{name}</Ellipsis>

        <p id="confirm-detail">{detail}</p>

        {error ? (
          <p className="error-text" role="alert">
            {error}
          </p>
        ) : null}

        <div className="row">
          <button
            type="button"
            className="danger"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? busyLabel : confirmLabel}
          </button>
          <button
            ref={cancel}
            type="button"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      </div>
    </dialog>
  );
}
