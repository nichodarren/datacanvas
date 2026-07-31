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
 * They come back when they hold something. Until then the space belongs to the
 * work. What none of them may ever do is *fake* content: placeholder rows in a
 * Run Log would imply traceability that does not exist, and P3 is the one
 * promise this product cannot be casual about.
 */
export function Shell({
  children,
  headerExtras,
  versionBadge,
  active,
  me,
}: {
  children: ReactNode;
  /** The `Project ▾` control §14.2 places next to the brand. */
  headerExtras?: ReactNode;
  versionBadge?: ReactNode;
  active?: "preview" | "schema";
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
        <nav className="sidebar">
          <div className="group">Data</div>
          <Link href="/" className={active === "preview" ? "active" : ""}>
            Preview
          </Link>
          <Link href="#" className={active === "schema" ? "active" : ""} aria-disabled>
            Schema
          </Link>

          <div className="group">Explore</div>
          <span className="item disabled">Library</span>
          <span className="item disabled">Steps</span>
          <div className="phase">Phase 3 — the tool catalogue</div>

          <div className="group">Findings</div>
          <span className="item disabled">Board</span>
          <div className="phase">Phase 4</div>
        </nav>

        <main className="workarea">{children}</main>
      </div>
    </div>
  );
}
