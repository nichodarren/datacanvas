/**
 * Which ground the user reads on.
 *
 * The brief settled this before the session began: *"Tanah bukan keputusan
 * desain — ia milik orang yang menatapnya."* So there are three states and not
 * two, because "follow my machine" is a real answer and the one most people
 * actually want — someone whose OS flips at sunset expects this to flip with
 * it, and a two-way switch quietly overrides that forever after one click.
 */
export type ThemeChoice = "system" | "light" | "dark";

const KEY = "datacanvas.theme";

export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"] as const;

function isChoice(value: string | null): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

/**
 * Applied by stamping `data-theme` on `<html>`, which is all the stylesheet
 * needs: `color-scheme` switches there, and every `light-dark()` token
 * re-resolves — along with the native scrollbars, checkboxes and select menus
 * that follow `color-scheme` rather than our CSS.
 *
 * `system` removes the attribute rather than writing a value, so the root falls
 * back to `color-scheme: light dark` and the OS preference wins again. Writing
 * a computed "light" or "dark" there instead would freeze today's OS setting
 * into the page and stop it ever changing.
 */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function recallTheme(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(KEY);
    return isChoice(stored) ? stored : "system";
  } catch {
    // Private mode, or storage switched off by policy. "Follow the machine" is
    // the right thing to fall back to, and it is also the default.
    return "system";
  }
}

export function rememberTheme(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(KEY, choice);
  } catch {
    // The choice still applies for this page; it just will not outlive it.
  }
}

/**
 * Runs before the first paint, inlined into `<head>`.
 *
 * Without it the page renders in the OS ground, then React mounts and corrects
 * it — a white flash on every navigation for anyone who chose dark on a light
 * machine. This is the one case where a blocking inline script earns its place:
 * it is three lines, it has no dependencies, and the thing it prevents is
 * visible on every single page load.
 *
 * Wrapped in try/catch for the same storage failures as above; if it throws,
 * the page simply renders in the OS ground, which is the documented default.
 */
export const THEME_BOOTSTRAP = `try{var t=localStorage.getItem(${JSON.stringify(KEY)});if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}`;
