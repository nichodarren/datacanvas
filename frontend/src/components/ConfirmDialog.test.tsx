import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/ConfirmDialog";

/**
 * What can honestly be asserted about a `<dialog>` in jsdom, and what cannot.
 *
 * jsdom parses `<dialog>` and operates none of it, so `vitest.setup.ts` stubs
 * `showModal` and `close` down to the one thing they do that this component
 * reads: the `open` attribute. The focus trap, the top layer, the inert
 * background and `::backdrop` are not modelled, and deliberately not faked —
 * they are the reasons the component uses a real `<dialog>` rather than a
 * `<div>`, and a stub that pretended to provide them would let this file claim
 * they work when nothing had checked.
 *
 * So these are about the decisions the component makes: what it renders, when
 * it refuses, and which control it hands the keyboard to.
 */
function open(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const props = {
    open: true,
    title: "Delete this dataset?",
    name: "quarterly_sales.csv",
    detail: "The file goes with it, and nothing here can be undone.",
    confirmLabel: "Delete file",
    busyLabel: "Deleting…",
    onConfirm,
    onCancel,
    ...overrides,
  };
  const view = render(<ConfirmDialog {...props} />);
  return { ...view, onConfirm, onCancel };
}

describe("the question before something is destroyed", () => {
  it("says what is about to go, by name", () => {
    open();

    expect(
      screen.getByRole("alertdialog", { name: "Delete this dataset?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("quarterly_sales.csv")).toBeInTheDocument();
  });

  it("is not in the document at all until it is asked for", () => {
    open({ open: false });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // The name in particular. `Ellipsis` measures its text against the box
    // around it, and a box inside a hidden dialog measures zero — so a long
    // name mounted early would decide it fitted and never slide.
    expect(screen.queryByText("quarterly_sales.csv")).not.toBeInTheDocument();
  });

  it("gives the keyboard to the way out, not to the destructive button", () => {
    open();

    // `showModal` focuses the first focusable child, and the first one here
    // deletes a file. Pressing Enter on a dialog you have just opened must not
    // be how a dataset goes.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("asks the parent to close rather than closing itself", () => {
    const { onCancel } = open();

    fireEvent(
      screen.getByRole("alertdialog"),
      new Event("cancel", { bubbles: false, cancelable: true }),
    );

    // The element staying open is the assertion: if it had closed itself, the
    // parent would still think the question was on screen and the two would
    // disagree about what the user is looking at.
    expect(onCancel).toHaveBeenCalledOnce();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("takes a click on the backdrop as a way out", () => {
    const { onCancel } = open();

    // The backdrop is the dialog's own box; anywhere inside the question, the
    // panel is what the pointer lands on. Dismissing is the safe direction.
    fireEvent.click(screen.getByRole("alertdialog"));

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does not take a click inside the panel as one", () => {
    const { onCancel } = open();

    fireEvent.click(screen.getByText("Delete this dataset?"));

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("stops offering a way out once there is nothing left to cancel", () => {
    const { onCancel } = open({ busy: true });

    expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    fireEvent.click(screen.getByRole("alertdialog"));
    fireEvent(
      screen.getByRole("alertdialog"),
      new Event("cancel", { bubbles: false, cancelable: true }),
    );

    // Escape and the backdrop are the two ways round a disabled button, and
    // both are refused for the same reason: the request is already in flight,
    // and closing the dialog would only hide an outcome the user still needs.
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("shows a failed attempt without taking the question away", () => {
    open({ error: "Could not delete that dataset." });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not delete that dataset.",
    );
    expect(screen.getByRole("button", { name: "Delete file" })).toBeEnabled();
  });
});
