"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

/* Imported rather than named by path, and the difference is not style.
   `src="/logo.png"` is a URL that stays the same when the file behind it
   changes, so a browser holding the old bytes has no way to learn it should
   stop. That happened on 2026-08-25: the mark went from cyan to white, the
   favicon updated because it is fetched differently, and the header kept
   serving the old one out of cache while the server was answering correctly.

   A static import makes the URL content-addressed —
   `/_next/static/media/logo.<hash>.png` — so new bytes are always a new
   address. It also hands `next/image` the intrinsic dimensions, which is why
   `width`/`height` are gone from the element below. */
import logo from "../../public/logo.png";

import { AccountMenu } from "@/components/AccountMenu";
import { ArrowLeft } from "@/components/Icon";
import type { Me } from "@/lib/api";

/**
 * The workspace layout from §14.2 — the parts of it that do something.
 *
 * This used to render the whole shape ahead of its contents: a Run Log panel on
 * the right and a copilot composer along the bottom, both empty, each saying
 * which phase it belonged to. The argument was §14.1 — the user should grasp
 * the mental model in thirty seconds, and a layout that grows new regions later
 * teaches it twice.
 *
 * Both are gone, and the argument did not survive contact with the numbers.
 * The sidebar takes 190px, the Run Log took 260px, the composer took a strip
 * across the bottom of every screen. At the 1280px NFR-UX.4 guarantees, that is
 * roughly a third of the width spent on chrome that could not be used — and the
 * thing it crowded is the preview grid, the one surface that works today and
 * the one that most wants room (FR-D.1).
 *
 * The reasoning was also weaker than it looked. "Teach the layout once" applies
 * to *regions*; a chat input is a control everyone already recognises, and it
 * teaches nothing by appearing early. The Run Log had the better case — it
 * describes traceability (P3), which is genuinely unfamiliar — but describing a
 * feature is not the same as priming a layout, and a paragraph of prose sat
 * there permanently to do it.
 *
 * The left navigation rail went the same way, and its case was the strongest of
 * the three even though navigation is exactly the kind of thing you would
 * normally introduce early. The principle held; the object did not live up to
 * it. In 190px of every screen it carried one link that duplicated the brand
 * (both went to `/`), one that was broken, and three phase labels.
 *
 * The broken one was `Schema`, and it was worse than a placeholder. It rendered
 * as a `<Link>` styled identically to the live item — not as the greyed spans
 * Library and Steps used — so it promised to work, went to `href="#"`, and
 * named a feature that *does* exist as a tab on the version page. Its
 * `aria-disabled` did not disable anything either: the anchor stayed focusable
 * and clickable while announcing itself as disabled.
 *
 * Underneath that was a category error. A schema belongs to one dataset
 * version — *schema of what?* has no answer from a global rail on the home
 * screen, which is why it pointed nowhere. The version page answered it with a
 * pair of tabs, and those have since gone too: the schema is now read straight
 * off the column headers, which is the only place a type can be corrected.
 *
 * The app has two destinations today: the dataset list and a version. Brand →
 * home, card → version is complete navigation for two destinations.
 *
 * All of them come back when they hold something. What none may ever do is
 * *fake* content: placeholder rows in a Run Log would imply traceability that
 * does not exist, and P3 is the one promise this product cannot be casual about.
 */
export function Shell({
  children,
  headerExtras,
  me,
  up,
}: {
  children: ReactNode;
  /**
   * The middle of the header. It held the `Project ▾` control until 2026-08-21,
   * when the project level came off the screen; the dataset list now puts its
   * search field here.
   */
  headerExtras?: ReactNode;
  /** Absent only while the page is still finding out who is signed in. */
  me?: Me | null;
  /**
   * Where this page's parent is, for the pages that have one.
   *
   * ## Why it is a way *up* and not a Back button
   *
   * The browser already has Back, in the corner every browser puts it in, and a
   * control that calls `history.back()` adds a second copy of it. What the
   * browser cannot do is the thing that is actually missing: arriving at a
   * dataset from a link, a bookmark or a fresh tab leaves Back pointing at
   * whatever came before — another site, or nothing. *Up* always works, because
   * it is a fact about this page rather than about how someone got here.
   *
   * ## Why it is not in the top-left corner
   *
   * That corner is the mark, and the mark is the anchor: it is on every screen,
   * in the same place, and it is already a link home. Putting a back arrow to
   * its left would give the corner two jobs and demote the one thing that is
   * constant. So this sits immediately *after* the mark, behind a divider —
   * the mark says where you are, the divider says the next thing is about this
   * page, and the label says where it goes.
   *
   * ## Why it carries a word
   *
   * A bare `←` is only readable as "back", which is the thing it is not. The
   * label names the destination, so the control answers *where does this go*
   * before it is pressed rather than after.
   */
  up?: { href: string; label: string };
}) {
  return (
    <div className="shell">
      {/* Invisible until it is focused, and then the first thing Tab reaches.
          The header is small, but it is between the keyboard and the work on
          every single screen — and the grid below it is the surface people
          come here for. Deferred out of the mechanical pass on purpose: a skip
          link is a navigation affordance, and it belongs with the rest of
          them (D-036). */}
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <header className="topbar">
        <Link href="/" className="brand">
          {/* The mockup's header carries the mark and no wordmark, so the
              product's name lives in this link's accessible name rather than
              on the screen. `alt=""` was right while the word sat beside it and
              is wrong now: this is the whole of the link's content, and an
              empty `alt` would leave a control with no name at all. */}
          <Image src={logo} alt="DataCanvas home" className="mark" priority />
          {/* The wordmark and the way up share this slot, and they are mutually
              exclusive by design: the home page says what this is, every page
              under it says how to get back. */}
          {up ? null : (
            <span className="wordmark" aria-hidden="true">
              DataCanvas
            </span>
          )}
        </Link>
        {up ? (
          <>
            <span className="topbar-divide" aria-hidden="true" />
            <Link href={up.href} className="up">
              <ArrowLeft size={16} />
              {up.label}
            </Link>
          </>
        ) : null}
        {/* A spacer either side, so the middle stays centred whether or not
            anything is in it and whether or not the two ends match in width. */}
        <div className="spacer" />
        {headerExtras}
        <div className="spacer" />
        {/* The privacy-mode pill (NFR-PRIV.2 / UX-6, §14.2) used to sit here,
            reading `🔒 balanced` out of the JSX. It is gone until Phase 5.

            The rest of this shell shows empty regions on purpose — see the
            note above — but a security indicator is a different class of
            thing. An empty panel that says "the executor is Phase 3" is
            honest; a padlock next to a mode name *asserts a state*, and no
            tooltip undoes that reading. It is harmless today because nothing
            is sent to any LLM, and that is exactly the danger: the habit
            survives to the day the copilot lands, and then the label is a lie
            about a live system.

            It comes back with the three things that make it mean anything: a
            route that returns `workspace_policy.llm_privacy_mode` (the column
            is real and defaults to `balanced`), the Privacy Gate that enforces
            it (§13.5), and a control to change it. */}
        {me ? <AccountMenu me={me} /> : null}
      </header>

      <div className="body">
        {/* `tabIndex={-1}` so the skip link can actually land focus here.
            Without it the browser scrolls to the anchor and leaves focus at the
            top of the document, which is the half-working version of this
            control that is easy to ship and impossible to notice. */}
        <main id="main" tabIndex={-1} className="workarea">
          {children}
        </main>
      </div>
    </div>
  );
}
