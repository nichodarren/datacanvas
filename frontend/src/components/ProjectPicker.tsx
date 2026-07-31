"use client";

import { useEffect, useState } from "react";

import { useDisclosure } from "@/hooks/useDisclosure";
import type { Project } from "@/lib/api";

/**
 * The `Project ▾` control §14.2 puts in the header.
 *
 * **A dropdown, not a gate.** FR-A.4 defines a Project as the thing that
 * *groups* datasets and analyses — a folder, not the work itself. Making the
 * first screen a gallery of projects (the shape Google Flow uses, where a
 * project genuinely is the artefact) would put an administrative choice in
 * front of someone who has not yet done anything real, and would land a new
 * user in a gallery holding exactly one card. §15.2 auto-creates that project
 * at registration precisely so nobody has to make it.
 *
 * So switching projects lives here, out of the way, and the work stays in the
 * middle of the screen.
 *
 * ## Why this is a disclosure, and why that is a correction
 *
 * This shipped as `role="menu"` with `role="menuitem"` children and
 * `aria-haspopup="menu"`, and implemented none of what those promise: arrow
 * keys, Home/End, first-character typeahead, composite focus management. It
 * could not be closed from the keyboard at all — Escape did nothing, Tab walked
 * past the open panel into the page behind it.
 *
 * Every word of that had already been written down. `AccountMenu` carries three
 * paragraphs on why declaring `menu` without its behaviour is worse than
 * declaring nothing, and `useDisclosure` exists precisely so a fourth popup
 * gets the contract by construction. Both were written on 2026-07-31; both
 * listed three popups. This is the fourth, and it was missed because it lives
 * in the header rather than in the grid — a reminder that "we fixed this class
 * of defect" is a claim about the places somebody looked.
 */
export function ProjectPicker({
  projects,
  current,
  onSelect,
  onCreate,
}: {
  projects: Project[];
  current: Project | null;
  onSelect: (project: Project) => void;
  onCreate: (name: string) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  /**
   * Creating a project used to fail in complete silence.
   *
   * `create` awaited `onCreate` and caught nothing, so an API that was down
   * left the form sitting there with the name still in it and no indication
   * that anything had happened — the user's only signal was the absence of a
   * new entry in a list they would have to reopen to check. W-4: say what went
   * wrong.
   */
  const [error, setError] = useState<string | null>(null);

  const { open, close, toggle, container, trigger, panel, panelId } = useDisclosure();

  // The create form is a state *inside* the panel, so it has to end when the
  // panel does. Left alone, reopening the picker would land on a half-filled
  // form the user had already dismissed by clicking away from it.
  useEffect(() => {
    if (open) return;
    setCreating(false);
    setName("");
    setError(null);
  }, [open]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate(trimmed);
      setName("");
      setCreating(false);
      close(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create that project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={container} className="anchor">
      <button
        ref={trigger}
        type="button"
        className="picker"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
      >
        {current?.name ?? "No project"} <span aria-hidden>▾</span>
      </button>

      {open ? (
        <div ref={panel} id={panelId} className="menu">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={project.id === current?.id ? "menu-item current" : "menu-item"}
              // The current project is stated in words as well as weight: the
              // heavier label is invisible to anyone who cannot see it, and
              // NFR-UX.3 does not allow a signal to live in one channel only.
              aria-current={project.id === current?.id}
              onClick={() => {
                onSelect(project);
                close(false);
              }}
            >
              {project.name}
              {/* An explicit whitespace text node, for the same reason the
                  column picker has one: without it the two contributions are
                  concatenated with nothing between them and the accessible name
                  comes out `Sales· current`. Whitespace inside the span is
                  trimmed away by the name computation; whitespace *between*
                  nodes is not. */}
              {project.id === current?.id ? (
                <>
                  {" "}
                  <span className="faint">· current</span>
                </>
              ) : null}
            </button>
          ))}

          <div className="menu-sep" />

          {creating ? (
            <form className="menu-form" onSubmit={create}>
              {/* The name is asked for by the placeholder, which vanishes the
                  moment anyone types into it. `aria-label` is what survives, so
                  the control keeps an accessible name for the whole time it is
                  being filled in. */}
              <input
                autoFocus
                aria-label="Project name"
                placeholder="Project name"
                name="project-name"
                autoComplete="off"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={busy}
              />
              <button className="primary" type="submit" disabled={busy || !name.trim()}>
                {busy ? "Creating…" : "Create"}
              </button>
            </form>
          ) : (
            <button type="button" className="menu-item" onClick={() => setCreating(true)}>
              + New project
            </button>
          )}

          {error ? (
            <div className="banner error compact" role="alert">
              {error}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
