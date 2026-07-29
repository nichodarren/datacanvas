"use client";

import { useEffect, useRef, useState } from "react";

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
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const box = useRef<HTMLDivElement>(null);

  // Close on an outside click. Without it the menu stays open behind whatever
  // the user clicks next, which reads as the app being stuck.
  useEffect(() => {
    if (!open) return;
    const onDocument = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) {
        setOpen(false);
        setCreating(false);
      }
    };
    document.addEventListener("mousedown", onDocument);
    return () => document.removeEventListener("mousedown", onDocument);
  }, [open]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    await onCreate(name.trim());
    setName("");
    setCreating(false);
    setOpen(false);
  }

  return (
    <div ref={box} style={{ position: "relative" }}>
      <button
        type="button"
        className="picker"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {current?.name ?? "No project"} <span aria-hidden>▾</span>
      </button>

      {open ? (
        <div className="menu" role="menu">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              role="menuitem"
              className={project.id === current?.id ? "menu-item current" : "menu-item"}
              onClick={() => {
                onSelect(project);
                setOpen(false);
              }}
            >
              {project.name}
              {project.id === current?.id ? <span className="faint"> · current</span> : null}
            </button>
          ))}

          <div className="menu-sep" />

          {creating ? (
            <form className="menu-form" onSubmit={create}>
              <input
                autoFocus
                placeholder="Project name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <button className="primary" type="submit">
                Create
              </button>
            </form>
          ) : (
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              onClick={() => setCreating(true)}
            >
              + New project
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
