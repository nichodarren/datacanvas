import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ThemePicker } from "@/components/ThemePicker";
import { THEME_BOOTSTRAP } from "@/lib/theme";

/**
 * The ground belongs to whoever is reading (D-037).
 *
 * Three states, not two. "Follow my machine" is a real answer and the default,
 * and a two-position switch cannot express it — the first click would silently
 * convert a following preference into a fixed one with no way back.
 */

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

describe("choosing a ground", () => {
  it("starts on whatever the machine says", async () => {
    render(<ThemePicker />);

    expect(await screen.findByRole("button", { name: "System", pressed: true })).toBeInTheDocument();
    // Nothing stamped: `color-scheme: light dark` is left to follow the OS.
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("applies the choice to the document, not just to itself", async () => {
    const user = userEvent.setup();
    render(<ThemePicker />);
    await screen.findByRole("button", { name: "System" });

    await user.click(screen.getByRole("button", { name: "Dark" }));

    // One attribute is the whole mechanism: `color-scheme` switches there and
    // every `light-dark()` token re-resolves with it.
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("survives coming back tomorrow", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ThemePicker />);
    await screen.findByRole("button", { name: "System" });
    await user.click(screen.getByRole("button", { name: "Light" }));
    unmount();

    render(<ThemePicker />);

    expect(await screen.findByRole("button", { name: "Light", pressed: true })).toBeInTheDocument();
  });

  it("goes back to following the machine, rather than freezing today's answer", async () => {
    const user = userEvent.setup();
    render(<ThemePicker />);
    await screen.findByRole("button", { name: "System" });

    await user.click(screen.getByRole("button", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "System" }));

    // The attribute is *removed*, not set to a computed "light". Writing one
    // would pin today's OS setting into the page forever.
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("does not claim ARIA semantics it has not implemented", async () => {
    render(<ThemePicker />);
    await screen.findByRole("button", { name: "System" });

    // `radiogroup` would promise arrow-key navigation and roving focus — the
    // same contract `ProjectPicker` had to be corrected for declaring.
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });
});

describe("the pre-paint bootstrap", () => {
  it("applies a stored ground before React exists", () => {
    window.localStorage.setItem("datacanvas.theme", "dark");

    // Exactly what `layout.tsx` inlines into <head>. Running it here is the
    // only way to test that the white flash on load is actually prevented.
    new Function(THEME_BOOTSTRAP)();

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("leaves the document alone when the choice is to follow the machine", () => {
    window.localStorage.setItem("datacanvas.theme", "system");

    new Function(THEME_BOOTSTRAP)();

    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("does not throw when storage refuses to answer", () => {
    // Safari private mode throws on read; enterprise policy can switch storage
    // off entirely. A blocking script in <head> that throws takes the page with
    // it, so this is the one that actually matters.
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("storage is disabled");
      },
    });

    expect(() => new Function(THEME_BOOTSTRAP)()).not.toThrow();

    if (original) Object.defineProperty(window, "localStorage", original);
  });
});
