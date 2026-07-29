"use client";

import Link from "next/link";
import type { ReactNode } from "react";

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
  versionBadge,
  active,
}: {
  children: ReactNode;
  versionBadge?: ReactNode;
  active?: "preview" | "schema";
}) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand" style={{ color: "var(--ink)", textDecoration: "none" }}>
          DataCanvas
        </Link>
        {versionBadge}
        <div className="spacer" />
        {/* NFR-PRIV.2 / UX-6: the privacy mode is visible whenever the copilot
            is. It is shown here already, reading from nothing, because the
            header is where §14.2 puts it and moving it later would be a
            second lesson for the user. */}
        <span className="pill" title="Workspace privacy mode (§13.5). The copilot arrives in Phase 5.">
          🔒 balanced
        </span>
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
        <div className="spacer" style={{ flex: 1 }} />
        <span className="pill">balanced</span>
      </div>
    </div>
  );
}
