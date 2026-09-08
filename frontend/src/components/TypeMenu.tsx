"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { LOGICAL_TYPES } from "@/lib/api";

/**
 * The five logical types, as a menu (FR-C.2).
 *
 * ## One implementation, two surfaces
 *
 * It opens from the column header in the preview grid and from the type badge
 * on a profile card. Those are different triggers in different layouts, but the
 * *menu* is the same object — the same five options, the same hues, the same
 * statement of which one is current — and this project has already paid for
 * getting that wrong once. 0.13.0 records three popups that turned out to
 * implement three different levels of the same contract, one of which could not
 * be closed at all. The dismissal half of that was fixed by sharing
 * `useDisclosure`; this is the other half.
 *
 * Each call site keeps its own trigger and its own container, because those
 * genuinely differ: the header's trigger also carries a name, a resize handle
 * and a keyboard gesture, and the badge's is a badge.
 *
 * ## It flips rather than overflowing, on both axes
 *
 * **Sideways.** The panel is 260px and the column it hangs under can be 96px,
 * so left-aligned it always reaches 164px past its own column — invisible in
 * the middle of a table and, on the last column, the popup hanging out over the
 * edge of the grid. `.grid-wrap` scrolls horizontally, so it does not even clip
 * it: it grows the scrollable width instead, and the table gains somewhere new
 * to scroll to every time the menu opens.
 *
 * **Downwards.** The same shape of bug one axis over, and reported the same
 * way: a card on the last row opened its menu 33px past the bottom of the
 * window, with `boolean` half off the screen. Nothing grew and nothing scrolled
 * — the option was simply not there to click.
 *
 * Both are measured once, on open, against **the nearest ancestor that actually
 * clips** rather than against the window. Inside the grid that is `.grid-wrap`;
 * on a profile card there is no clipping ancestor and the answer is the
 * viewport. Found by walking up and reading `overflow`, not by naming those two
 * elements — a boundary identified by class name stops being true the day
 * something else scrolls. Each axis is asked separately, because `.grid-wrap`
 * declares only `overflow-x` and the used value of `overflow-y` follows it,
 * which is the kind of thing that is true and easy to forget.
 *
 * ## Upwards only when there is room upwards
 *
 * The vertical flip has a condition the horizontal one does not need: it moves
 * only if the menu **does not fit below and does fit above**. Flipping on the
 * first test alone would take a menu that is clipped by 30px at the bottom of a
 * short scroll container and clip it by 150 at the top instead — which is the
 * failure this is meant to remove, moved rather than fixed. Where neither side
 * has room, it stays where it was: an imperfect placement beats a worse one.
 */
export function TypeMenu({
  panelRef,
  panelId,
  current,
  onPick,
}: {
  panelRef: React.RefObject<HTMLDivElement | null>;
  panelId: string;
  /** The type the column is being read as now. */
  current: string;
  onPick: (logicalType: string) => void;
}) {
  const [placement, setPlacement] = useState({ flipped: false, above: false });
  const measured = useRef(false);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    // Measured once. Re-measuring after a flip would read the flipped box and
    // could send it back, which is a menu that oscillates on open.
    if (panel === null || measured.current) return;
    measured.current = true;

    const box = panel.getBoundingClientRect();
    // The element the panel is positioned against — the header cell, or the
    // badge's anchor. `top: 100%` puts the panel's top on its bottom edge, so
    // this is what says how much room is above.
    const anchor = panel.offsetParent?.getBoundingClientRect() ?? box;
    const room = edgesOf(panel);

    setPlacement({
      flipped: box.right > room.right,
      above:
        anchor.bottom + box.height > room.bottom &&
        anchor.top - box.height >= room.top,
    });
  }, [panelRef]);

  return (
    <div
      ref={panelRef}
      id={panelId}
      className={[
        "card type-popup",
        placement.flipped ? "flipped" : "",
        placement.above ? "above" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="type-menu">
        {LOGICAL_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            // Each option in its own hue, the same way the trigger that opened
            // this menu carries the current one.
            data-type={type}
            className={type === current ? "typed current" : "typed"}
            // The current type is marked by colour and weight. `aria-current`
            // carries the same fact to anyone who cannot see either, so the
            // "· current" label that used to trail it costs nothing to drop
            // (NFR-UX.3 — never colour *only*).
            aria-current={type === current}
            onClick={() => onPick(type)}
          >
            {type}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Where this element runs out of room, on each axis independently. */
function edgesOf(element: HTMLElement): {
  right: number;
  top: number;
  bottom: number;
} {
  const view = document.documentElement;
  const edges = {
    right: view.clientWidth,
    top: 0,
    bottom: view.clientHeight,
  };
  let horizontal = false;
  let vertical = false;

  for (
    let node = element.parentElement;
    node !== null && !(horizontal && vertical);
    node = node.parentElement
  ) {
    const style = getComputedStyle(node);
    // Asked separately, and read as *used* values rather than as authored: a
    // box that declares only `overflow-x: auto` gets `overflow-y: auto` too,
    // which is exactly what `.grid-wrap` does and exactly what would be missed
    // by looking for the property somebody wrote down.
    if (!horizontal && style.overflowX !== "visible") {
      edges.right = node.getBoundingClientRect().right;
      horizontal = true;
    }
    if (!vertical && style.overflowY !== "visible") {
      const box = node.getBoundingClientRect();
      edges.top = box.top;
      edges.bottom = box.bottom;
      vertical = true;
    }
  }
  return edges;
}
