import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Trail } from "@/components/Trail";
import type { Project } from "@/lib/api";

/**
 * The trail is the same object on every screen, and says only what is true of
 * the screen it is on (D-036).
 *
 * The account page is the case worth a test of its own: it belongs to no
 * project, and naming one there would be a plausible answer to a question the
 * page cannot answer. P6 rules that out for tool results; a header is not
 * exempt.
 */

const PROJECTS: Project[] = [
  {
    id: "p1",
    name: "Sales",
    workspace_id: "w1",
    description: null,
    created_at: "2026-01-01T00:00:00Z",
  },
];

describe("the trail", () => {
  it("does not link the project to the page you are already on", () => {
    render(
      <Trail
        project={PROJECTS[0] ?? null}
        projects={PROJECTS}
        atProject
        onSelect={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    // A control that reloads the page it is on is a control that does nothing.
    expect(screen.queryByRole("link", { name: "Sales" })).not.toBeInTheDocument();
    expect(screen.getByText("Sales")).toHaveAttribute("aria-current", "page");
  });

  it("shows no project, and no picker, on a screen that belongs to none", () => {
    render(<Trail project={null} here="Account" />);

    expect(screen.getByText("Account")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    // No dangling separator either: there is nothing to its left.
    expect(document.querySelector(".trail-sep")).toBeNull();
  });

  it("omits the picker when there is nothing to switch to", () => {
    // The version page renders the trail before its project list has arrived.
    // A caret with an empty menu behind it is the class of control this project
    // keeps removing.
    render(<Trail project={PROJECTS[0] ?? null} here="penjualan_q3" />);

    expect(screen.getByRole("link", { name: "Sales" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
