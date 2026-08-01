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
  paintBrowserChrome();
}

/**
 * `<meta name="theme-color">`, kept in step with the ground.
 *
 * It colours the browser's own furniture — the address bar on Android, the
 * title bar in an installed PWA — and a page whose surroundings stay white
 * while it is dark reads as a page that has not finished loading.
 *
 * **Written from JavaScript rather than declared in the document, and that is
 * forced rather than chosen.** The static form supports a `media` attribute, so
 * two tags can follow the OS. Neither can follow *our* toggle: `data-theme` is
 * an attribute on `<html>`, and no media query can see it. Since the toggle
 * exists precisely so the OS does not get the last word, the meta has to be
 * computed from the same answer the stylesheet uses.
 *
 * Values are read from the stylesheet's own `--bg` rather than repeated here.
 * A hardcoded pair would be a second copy of the palette, and the first thing
 * a second copy does is fall out of step with the first.
 */
function paintBrowserChrome(): void {
  // Read *after* `data-theme` has been set, so `light-dark()` has already
  // resolved and this is the ground actually in force — whether the choice or
  // the OS decided it.
  const ground = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();

  // No answer, no tag. `--bg` comes back empty if the stylesheet has not landed
  // yet, and `<meta name="theme-color" content="">` is not a smaller version of
  // this feature — it is a declaration that the page has no colour, which the
  // browser is entitled to act on. Saying nothing leaves it to the platform
  // default, which is the honest fallback (P6).
  if (!ground) return;

  let tag = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!tag) {
    tag = document.createElement("meta");
    tag.name = "theme-color";
    document.head.appendChild(tag);
  }
  tag.content = ground;
}

/**
 * Keeps the browser chrome honest when the *machine* changes its mind.
 *
 * Only matters while the choice is `system`: an OS that flips at sunset moves
 * the page's own colours through CSS, but the meta tag was computed once and
 * would sit at yesterday's answer until something else re-rendered.
 *
 * Returns its own teardown, so the caller unsubscribes the way it would from
 * any other listener.
 */
export function watchSystemGround(choice: ThemeChoice): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (choice === "system") paintBrowserChrome();
  };
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
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
