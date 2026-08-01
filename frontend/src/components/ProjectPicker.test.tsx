import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectPicker } from "@/components/ProjectPicker";
import type { Project } from "@/lib/api";

/**
 * The fourth popup, and the one that was missed.
 *
 * `AccountMenu` carries three paragraphs on why `role="menu"` without arrow
 * keys, Home/End and typeahead is worse than saying nothing, and
 * `useDisclosure` exists so a new popup gets Escape and focus management by
 * construction. Both were written on 2026-07-31 and both counted three popups.
 * This one lives in the header rather than in the grid, so nobody counted it —
 * it kept the false `menu` contract and had no way out from the keyboard at
 * all.
 *
 * These tests are written against the *behaviour* rather than the attributes,
 * apart from the one case where the attribute is itself the lie.
 */

const PROJECTS: Project[] = [
  {
    id: "p1",
    name: "Sales",
    workspace_id: "w1",
    description: null,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "p2",
    name: "Support",
    workspace_id: "w1",
    description: null,
    created_at: "2026-01-02T00:00:00Z",
  },
];

function renderPicker(onCreate = vi.fn().mockResolvedValue(undefined)) {
  const onSelect = vi.fn();
  const view = render(
    <ProjectPicker
      projects={PROJECTS}
      current={PROJECTS[0] ?? null}
      onSelect={onSelect}
      onCreate={onCreate}
    />,
  );
  return { ...view, onSelect, onCreate };
}

/** The trigger is the caret alone; the project's name lives beside it in the
 *  trail. Its label still carries the name, because "Switch project" on its own
 *  does not say which one you are leaving. */
const TRIGGER = "Switch project, currently Sales";

async function open() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: TRIGGER }));
  return user;
}

describe("the project picker as a disclosure", () => {
  it("closes on Escape and gives focus back to the trigger", async () => {
    renderPicker();
    const user = await open();

    expect(screen.getByRole("button", { name: "Support" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("button", { name: "Support" })).not.toBeInTheDocument();
    // Not merely closed: a popup that closes and drops focus on the document
    // leaves a keyboard user at the top of the page.
    expect(screen.getByRole("button", { name: TRIGGER })).toHaveFocus();
  });

  it("does not claim ARIA menu semantics it has none of", () => {
    renderPicker();

    // The trigger promised an application menu — arrow-key navigation,
    // Home/End, first-character typeahead — and implemented no part of it.
    expect(screen.getByRole("button", { name: TRIGGER })).not.toHaveAttribute("aria-haspopup");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("menuitem")).toHaveLength(0);
  });

  it("names the current project in words, not only in weight", async () => {
    renderPicker();
    await open();

    expect(screen.getByRole("button", { name: /Sales · current/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});

describe("creating a project", () => {
  it("gives the name field an accessible name that survives typing", async () => {
    renderPicker();
    const user = await open();
    await user.click(screen.getByRole("button", { name: "+ New project" }));

    const field = screen.getByRole("textbox", { name: "Project name" });
    await user.type(field, "Q3");

    // The placeholder is gone by now; the label is not.
    expect(screen.getByRole("textbox", { name: "Project name" })).toHaveValue("Q3");
  });

  it("cannot be submitted twice while the first request is in flight", async () => {
    let release: (() => void) | undefined;
    const onCreate = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = () => resolve();
        }),
    );

    renderPicker(onCreate);
    const user = await open();
    await user.click(screen.getByRole("button", { name: "+ New project" }));
    await user.type(screen.getByRole("textbox", { name: "Project name" }), "Q3");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(onCreate).toHaveBeenCalledTimes(1);

    release?.();
  });

  it("says so when the project could not be created", async () => {
    // This used to fail in complete silence: the promise rejected, nothing
    // caught it, and the form sat there looking exactly as it had.
    const onCreate = vi.fn().mockRejectedValue(new Error("The workspace is not reachable."));

    renderPicker(onCreate);
    const user = await open();
    await user.click(screen.getByRole("button", { name: "+ New project" }));
    await user.type(screen.getByRole("textbox", { name: "Project name" }), "Q3");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The workspace is not reachable.");
    // And the panel stays open, with the typed name still in it, so the retry
    // does not begin with retyping.
    expect(screen.getByRole("textbox", { name: "Project name" })).toHaveValue("Q3");
  });
});
