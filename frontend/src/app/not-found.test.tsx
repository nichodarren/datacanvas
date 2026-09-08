import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound from "@/app/not-found";

/**
 * §14.5 applied to the one screen nobody had held it up against.
 *
 * The rule — *always provide a way forward* — was written on 2026-07-31 from a
 * real 500 that told someone to add data and removed every means of doing it.
 * Next's built-in 404 fails the same rule more plainly: no shell, no header, no
 * link anywhere, and a light background under a dark app. The only exit was the
 * browser's own back button.
 */
describe("the not-found page", () => {
  it("offers a way out", () => {
    render(<NotFound />);

    expect(
      screen.getByRole("link", { name: "Go to your datasets" }),
    ).toHaveAttribute("href", "/");
  });

  it("says what happened without quoting a status code", () => {
    render(<NotFound />);

    // "404" is not information to most people; it is a number that implies they
    // broke something.
    expect(screen.queryByText(/404/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "There is nothing at this address",
    );
  });

  it("keeps the shell, so the header is still there to leave by", () => {
    render(<NotFound />);

    // The mark carries the name now that the wordmark is not drawn beside it,
    // so the accessible name is the image's `alt` rather than link text.
    expect(
      screen.getByRole("link", { name: "DataCanvas home" }),
    ).toHaveAttribute("href", "/");
    expect(
      screen.getByRole("link", { name: "Skip to content" }),
    ).toBeInTheDocument();
  });
});
