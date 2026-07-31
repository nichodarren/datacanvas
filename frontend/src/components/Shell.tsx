"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/AccountMenu";
import type { Me } from "@/lib/api";

/**
 * The workspace layout from §14.2.
 *
 * Only the Phase 2 surfaces are live. The rest — Library, Steps, Findings, the
 * Run Log, the copilot composer — are **present and visibly empty**, each
 * saying which phase it belongs to.
 *
 * That is a deliberate choice over hiding them. §14.1 says the user must
 * understand the mental model in the first thirty seconds: *"I work with data,
 * every step is recorded, and I can go back to any of them."* A layout that
 * grows new regions later teaches that model twice. Showing the shape now, with
 * honest empty states (§14.5), teaches it once — and keeps us from quietly
 * discovering in Phase 3 that the space was never there.
 *
 * What it must never do is *fake* them. Placeholder rows in the Run Log would
 * imply traceability that does not exist yet, and P3 is the one promise this
 * product cannot be casual about.
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

        <aside className="runlog">
          <div style={{ color: "var(--ink-dim)", fontWeight: 600, marginBottom: 8 }}>Run log</div>
          <p>
            Every tool call will appear here — arguments, origin, duration, cache hit — and each
            entry opens the step it came from.
          </p>
          <p style={{ marginTop: 10 }}>
            Nothing runs tools yet. The executor is Phase 3, so this panel is empty rather than
            populated with examples.
          </p>
        </aside>
      </div>

      <div className="composer">
        <span aria-hidden>💬</span>
        <span>Ask about this data — the copilot arrives in Phase 5.</span>
        {/* A second hardcoded `balanced` pill lived here. Same defect, and
            easier to miss than the one in the header. */}
      </div>
    </div>
  );
}
