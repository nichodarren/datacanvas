"use client";

import Link from "next/link";

import { ProjectPicker } from "@/components/ProjectPicker";
import type { Project } from "@/lib/api";

/**
 * Where you are, and the way out of it (D-036).
 *
 * ## The two things that were wrong
 *
 * `ProjectPicker` was rendered on the home page and nowhere else, so the one
 * screen that could not answer *which project is this* was the one where the
 * answer was not already on the page. And the only in-app way back from a
 * version was the brand link, which goes to `/` — where the home page opens
 * whichever project the browser last remembered. Open a version belonging to
 * another project from a bookmark, press the brand, and the app moved you into
 * a different project with nothing on screen saying so. That is an orientation
 * *error*, not a missing affordance, and it could not be fixed in the frontend
 * until `DatasetVersionResponse` began carrying the project it belongs to.
 *
 * ## Why this costs nothing, and why that matters
 *
 * D-032 removed the left rail over **width**: 190px of every 1280px screen for
 * one duplicated link and one broken one. That argument is untouched here. This
 * goes into `headerExtras`, a slot `Shell` already has and only the home page
 * was using — no new region, no new row, zero extra width and zero extra
 * height. A second header row was considered and rejected for costing ~32px on
 * every screen to hold something an empty slot already fits.
 *
 * ## Why the name and the caret are two controls
 *
 * If the whole chip were the picker, leaving a version page would cost two
 * clicks: open the menu, then choose the project you are already in. An exit
 * must not be more expensive than the rarer move it sits beside. Split, the
 * exit is one click and switching is two. It costs one extra tab stop — in the
 * header, not in a list of sixty columns, so the arithmetic that removed the
 * reorder buttons and the resize handles does not reach this.
 *
 * ## The third segment is deliberately absent
 *
 * The full trail is `Project › Dataset › Version`. Today a Dataset always has
 * exactly one reachable version — there is no route that lists them — so
 * *Dataset* and *Version* are one thing, and drawing them as two would render a
 * hierarchy nobody can walk. The third segment arrives with FR-B.2 and P4,
 * which are already scheduled as a single piece of work.
 */
export function Trail({
  project,
  projects,
  atProject,
  here,
  onSelect,
  onCreate,
}: {
  /**
   * The project everything to the right of it lives in, or `null` on a screen
   * that belongs to no project. The account page is the latter, and says so by
   * showing no project rather than showing a plausible one.
   */
  project: { id: string; name: string } | null;
  /** For the picker. Empty is fine: the caret is simply not drawn. */
  projects?: Project[];
  /** True when the project *is* the current page, so its name is not a link to it. */
  atProject?: boolean;
  /** The leaf — a dataset name, or a word for a screen that has no object. */
  here?: string | null;
  onSelect?: (project: Project) => void;
  onCreate?: (name: string) => Promise<void>;
}) {
  const switchable = projects !== undefined && onSelect !== undefined && onCreate !== undefined;

  return (
    <nav className="trail" aria-label="Breadcrumb">
      <ol>
        {project ? (
          <li>
            {atProject ? (
              // You are here, so it is not a link to here. A control that
              // reloads the page you are on is a control that does nothing.
              // `aria-current` only when nothing sits to the right of it —
              // otherwise the leaf is the current page and this is its parent.
              <span className="trail-here" aria-current={here ? undefined : "page"}>
                {project.name}
              </span>
            ) : (
              <Link href="/">{project.name}</Link>
            )}
            {switchable ? (
              <ProjectPicker
                projects={projects}
                current={project}
                onSelect={onSelect}
                onCreate={onCreate}
              />
            ) : null}
          </li>
        ) : null}

        {here ? (
          <li>
            {/* In the DOM so it is drawn, hidden from the accessibility tree so
                it is not read. A separator is a fact about the layout, and the
                nesting it depicts is already carried by the list. */}
            {project ? (
              <span className="trail-sep" aria-hidden="true">
                ›
              </span>
            ) : null}
            <span className="trail-here" aria-current="page">
              {here}
            </span>
          </li>
        ) : null}
      </ol>
    </nav>
  );
}
