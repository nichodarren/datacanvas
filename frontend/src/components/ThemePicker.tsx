"use client";

import { useEffect, useState } from "react";

import {
  THEME_CHOICES,
  type ThemeChoice,
  applyTheme,
  recallTheme,
  rememberTheme,
  watchSystemGround,
} from "@/lib/theme";

const LABELS: Record<ThemeChoice, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/**
 * Choosing the ground (D-037).
 *
 * ## Why it lives in the account menu
 *
 * Rule ② of this session closes the door on new surfaces, and the door stays
 * closed here: this is not a new region, it is one row inside a launcher that
 * already exists for exactly this kind of thing — settings that belong to the
 * person rather than to the data. A toggle in the top bar would have spent
 * width on every screen for a control most people touch once.
 *
 * ## Why three buttons and not a switch
 *
 * "Follow my machine" is a real state and the default. A two-position switch
 * cannot express it: the first click silently converts a following preference
 * into a fixed one, and there is no way back to following.
 *
 * ## Why not `role="radiogroup"`
 *
 * The same reason `AccountMenu` is a disclosure and not a `menu`, and the same
 * reason `ProjectPicker` had to be corrected: `radiogroup` promises arrow-key
 * navigation and roving focus, and declaring a contract without implementing it
 * tells assistive technology to expect behaviour that is not there. These are
 * three ordinary buttons with `aria-pressed`, which is exactly what they are —
 * Tab reaches each, Space and Enter activate, and nothing is invented.
 */
export function ThemePicker() {
  /**
   * `null` until the effect below has read storage.
   *
   * The stored choice cannot be read during render: this component is rendered
   * on the server too, where `localStorage` does not exist, and reading it on
   * the client's first render would make the two disagree — which React reports
   * as a hydration error. So the first paint marks nothing as pressed, and one
   * frame later the real answer arrives. The *ground* is already correct by
   * then regardless, because the inline bootstrap in `layout.tsx` applied it
   * before this component existed.
   */
  const [choice, setChoice] = useState<ThemeChoice | null>(null);

  useEffect(() => {
    const stored = recallTheme();
    setChoice(stored);
    // Re-applied rather than assumed. The pre-paint bootstrap set `data-theme`
    // before any stylesheet had loaded, so it could not read `--bg` — which
    // means the `theme-color` meta is written here, at the first moment the
    // resolved ground is actually readable.
    applyTheme(stored);
    return watchSystemGround(stored);
  }, []);

  function pick(next: ThemeChoice) {
    setChoice(next);
    rememberTheme(next);
    applyTheme(next);
  }

  return (
    <div className="theme-picker">
      <span className="theme-label" id="theme-picker-label">
        Appearance
      </span>
      <div className="theme-options" role="group" aria-labelledby="theme-picker-label">
        {THEME_CHOICES.map((option) => (
          <button
            key={option}
            type="button"
            className={choice === option ? "theme-option on" : "theme-option"}
            aria-pressed={choice === option}
            onClick={() => pick(option)}
          >
            {LABELS[option]}
          </button>
        ))}
      </div>
    </div>
  );
}
