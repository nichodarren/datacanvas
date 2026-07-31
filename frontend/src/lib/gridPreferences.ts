/**
 * What the user chose to look at in one dataset version's grid, remembered.
 *
 * ## Why this is worth storing
 *
 * The home page already remembers the last project, and the comment there
 * argues the case: *"a tool that always drops you in the same place regardless
 * of what you were doing makes you re-navigate every visit, and that cost is
 * paid every single time."*
 *
 * The same argument is stronger here, and it had not been applied. FR-D.3 exists
 * because a wide file is unusable without hiding columns — sixty columns share
 * about 1230px, which is twenty pixels each. Picking the five that matter is not
 * a preference, it is the only way to read the file. Losing that on every reload
 * makes the person do the necessary work again, from a list of sixty.
 *
 * ## Scoped per version, on purpose
 *
 * Column names belong to a dataset version. Keying on the version means a
 * different dataset never inherits a hidden set that would silently blank
 * columns it happens to share a name with.
 *
 * ## What is deliberately not stored
 *
 * Nothing from the data — only column names, which the user typed or their file
 * did. No values, no counts, no ids beyond the version already in the URL.
 */

const PREFIX = "datacanvas.grid.";

/**
 * The shape version of a stored entry. Raise it whenever the meaning of a field
 * changes; entries written under a different number are ignored and pruned.
 *
 * Found by the `react-best-practices` skill's `client-localstorage-schema` rule
 * on the day that skill was vendored (D-035), in code written hours earlier.
 *
 * The shape check alone was not enough, and the gap is subtle. It validates that
 * `hidden` and `pinned` are arrays and `widths` is an object — so a *future*
 * version of this file that keeps those names while changing what they mean
 * would read old entries as valid and act on them. A grid silently restoring the
 * wrong columns is exactly the class of failure the cell-lookup fix removed.
 */
const SCHEMA_VERSION = 1;

/** Ninety days. Long enough to come back to a piece of work, short enough that
 *  a browser profile does not accumulate choices about files that are gone. */
const MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000;

/** Beyond this, the oldest go. Storage is a fixed budget shared with the rest
 *  of the origin, and an unbounded key space eventually takes it all. */
const MAX_ENTRIES = 50;

export interface GridPreferences {
  hidden: string[];
  pinned: string[];
  widths: Record<string, number>;
}

interface StoredPreferences extends GridPreferences {
  /** Shape version. Entries carrying anything else are ignored. */
  v: number;
  /** Epoch milliseconds, used only to decide what to prune. */
  at: number;
}

/**
 * `localStorage` is not always there to be used: Safari in private mode throws
 * on write, enterprise policy can disable it, and a full quota throws too.
 * None of that is worth breaking a grid over, so every path degrades to "this
 * session only" rather than propagating.
 */
function storage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function isPreferences(value: unknown): value is StoredPreferences {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<StoredPreferences>;
  return (
    candidate.v === SCHEMA_VERSION &&
    Array.isArray(candidate.hidden) &&
    Array.isArray(candidate.pinned) &&
    typeof candidate.widths === "object" &&
    candidate.widths !== null
  );
}

export function loadGridPreferences(versionId: string): GridPreferences | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(PREFIX + versionId);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    // Anything can be written to a key by anything. A shape check here is the
    // difference between ignoring junk and rendering a grid from it.
    if (!isPreferences(parsed)) return null;
    return { hidden: parsed.hidden, pinned: parsed.pinned, widths: parsed.widths };
  } catch {
    return null;
  }
}

export function saveGridPreferences(versionId: string, preferences: GridPreferences): void {
  const store = storage();
  if (!store) return;
  try {
    const entry: StoredPreferences = { ...preferences, v: SCHEMA_VERSION, at: Date.now() };
    store.setItem(PREFIX + versionId, JSON.stringify(entry));
    prune(store);
  } catch {
    // Quota, private mode, disabled storage. The grid still works; it just
    // will not remember. Failing the render over it would be the worse trade.
  }
}

/** Drop what is old, then what is oldest, until the budget holds. */
function prune(store: Storage): void {
  const entries: { key: string; at: number }[] = [];
  for (let index = 0; index < store.length; index += 1) {
    const key = store.key(index);
    if (!key?.startsWith(PREFIX)) continue;
    let at = 0;
    try {
      const parsed: unknown = JSON.parse(store.getItem(key) ?? "");
      at = isPreferences(parsed) ? parsed.at : 0;
    } catch {
      // Unparseable: `at` stays 0, so it sorts oldest and goes first.
    }
    entries.push({ key, at });
  }

  const cutoff = Date.now() - MAX_AGE_MS;
  const survivors = entries.filter((entry) => {
    if (entry.at >= cutoff) return true;
    store.removeItem(entry.key);
    return false;
  });

  survivors.sort((a, b) => a.at - b.at);
  for (const entry of survivors.slice(0, Math.max(0, survivors.length - MAX_ENTRIES))) {
    store.removeItem(entry.key);
  }
}
