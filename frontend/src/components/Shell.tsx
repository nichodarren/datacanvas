"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/AccountMenu";
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
  versionBadge,
  me,
}: {
  children: ReactNode;
  /** The `Project ▾` control §14.2 places next to the brand. */
  headerExtras?: ReactNode;
  versionBadge?: ReactNode;
  /** Absent only while the page is still finding out who is signed in. */
  me?: Me | null;
}) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand" style={{ color: "var(--ink)", textDecoration: "none" }}>
          DataCanvas
        </Link>
        {headerExtras}
        {versionBadge}
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
        <main className="workarea">{children}</main>
      </div>
    </div>
  );
}
