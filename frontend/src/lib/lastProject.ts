/**
 * Which project the user was last working in.
 *
 * This lived as a bare `localStorage` key inside the home page, which was fine
 * while the home page was the only screen that knew what a project was. It is
 * not any more: switching project from a version page has to write the same
 * key, or pressing the brand afterwards would return the user to the project
 * they had just left.
 *
 * ## Why it is remembered at all
 *
 * The argument is the one already written beside the original key: *a tool that
 * always drops you in the same place regardless of what you were doing makes
 * you re-navigate every visit, and that cost is paid every single time.*
 *
 * ## What it is not
 *
 * Not authorization, and never treated as such. It is a hint about where to
 * open; the id in it is checked against the list the server returned before
 * anything is done with it, so a stale or hand-edited value degrades into
 * "open the first project" rather than into an error — or into a request for
 * something that is not the reader's.
 */

const KEY = "datacanvas.project";

/**
 * Storage can be absent or refuse to answer — Safari's private mode throws on
 * write, enterprise policy can switch it off, and server rendering has no
 * `window` at all. None of that is worth breaking a page over, so both
 * functions here fail into "we do not know", which every caller already
 * handles because it is the same state as a first visit.
 */
export function recallProject(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function rememberProject(projectId: string): void {
  try {
    window.localStorage.setItem(KEY, projectId);
  } catch {
    // Nothing to do and nothing to report: the next visit opens the first
    // project instead, which is where this user already starts today.
  }
}
