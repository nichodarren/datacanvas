import { beforeEach, describe, expect, it } from "vitest";

import { loadGridPreferences, saveGridPreferences } from "@/lib/gridPreferences";

/**
 * Stored grid choices must survive a reload — and must not survive a change in
 * what they mean.
 *
 * The schema version came from the `client-localstorage-schema` rule in the
 * `react-best-practices` skill, applied to this file on the day that skill was
 * vendored (D-035). The shape check that was already here is not a substitute:
 * it asks whether `hidden` and `pinned` are arrays, so a later version of this
 * module that kept those names and changed their meaning would read old entries
 * as valid and restore the wrong columns.
 */

const KEY = "datacanvas.grid.version-1";

beforeEach(() => {
  window.localStorage.clear();
});

describe("gridPreferences", () => {
  it("returns what was stored", () => {
    saveGridPreferences("version-1", { hidden: ["a"], pinned: ["b"], widths: { c: 120 } });

    expect(loadGridPreferences("version-1")).toEqual({
      hidden: ["a"],
      pinned: ["b"],
      widths: { c: 120 },
    });
  });

  it("keeps versions apart", () => {
    saveGridPreferences("version-1", { hidden: ["a"], pinned: [], widths: {} });

    expect(loadGridPreferences("version-2")).toBeNull();
  });

  it("ignores an entry written under a different schema version", () => {
    // Exactly the shape this module writes, with a version it does not know.
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ v: 99, hidden: ["a"], pinned: [], widths: {}, at: Date.now() }),
    );

    expect(loadGridPreferences("version-1")).toBeNull();
  });

  it("ignores an entry carrying no version at all", () => {
    // What this module wrote before the rule was applied.
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ hidden: ["a"], pinned: [], widths: {}, at: Date.now() }),
    );

    expect(loadGridPreferences("version-1")).toBeNull();
  });

  it("ignores junk without throwing", () => {
    window.localStorage.setItem(KEY, "not json at all");

    expect(loadGridPreferences("version-1")).toBeNull();
  });

  it("clears entries it can no longer read on the next save", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ v: 99, hidden: [], pinned: [], widths: {} }));

    // Pruning runs on save. An unreadable entry sorts oldest and goes first,
    // so a stale schema does not sit in storage until the quota runs out.
    saveGridPreferences("version-2", { hidden: [], pinned: [], widths: {} });

    expect(window.localStorage.getItem(KEY)).toBeNull();
  });
});
