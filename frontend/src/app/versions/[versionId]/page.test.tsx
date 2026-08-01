import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VersionPage from "@/app/versions/[versionId]/page";
import type { DatasetVersion, Me, Project, SchemaContract } from "@/lib/api";
import { api } from "@/lib/api";

/**
 * The version page has to say which project it is in, and get you back to it.
 *
 * Before D-036 it said neither, and the second half was not merely a missing
 * affordance. The only in-app way off this page was the brand link, which goes
 * to `/` — and `/` opens whichever project `localStorage` last held. Open a
 * version belonging to project A from a bookmark while the browser remembers
 * project B, press the brand, and the app puts you in project B with nothing on
 * screen having said so.
 *
 * That could not be fixed from the frontend at all: `DatasetVersionResponse`
 * carried `dataset_id` and `dataset_name` and nothing about the project, so the
 * page had no way to know what to link to. These tests are the reason the two
 * fields were added.
 */

// Built inside the factory, not above it. `vi.mock` is hoisted to the top of
// the file, so a top-level `const` it closes over does not exist yet when it
// runs. The router object is also created once and returned on every call:
// Next's own `useRouter` is stable across renders, and a fresh object each time
// changes the identity of `load`'s `useCallback`, which re-fires the effect
// that calls it — the page then reloads forever.
vi.mock("next/navigation", () => {
  const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
  return { useRouter: () => router, useParams: () => ({ versionId: "version-1" }) };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      version: vi.fn(),
      schema: vi.fn(),
      projects: vi.fn(),
      rows: vi.fn(),
    },
  };
});

const ME: Me = {
  user: { id: "user-1", email: "someone@example.com", created_at: "2026-01-01T00:00:00Z" },
  workspaces: [
    {
      id: "workspace-1",
      name: "Personal",
      is_personal: true,
      created_at: "2026-01-01T00:00:00Z",
      role: "owner",
    },
  ],
};

const PROJECTS: Project[] = [
  {
    id: "project-a",
    name: "Sales",
    workspace_id: "workspace-1",
    description: null,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "project-b",
    name: "Support",
    workspace_id: "workspace-1",
    description: null,
    created_at: "2026-01-02T00:00:00Z",
  },
];

/** Belongs to project A — the case that used to send people to project B. */
const VERSION: DatasetVersion = {
  id: "version-1",
  dataset_id: "dataset-1",
  dataset_name: "penjualan_q3",
  project_id: "project-a",
  project_name: "Sales",
  version_no: 1,
  content_hash: "sha256:fixture",
  row_count: 1,
  column_count: 1,
  byte_size: 128,
  ingested_at: "2026-01-01T00:00:00Z",
  data_present: true,
};

const CONTRACT: SchemaContract = {
  id: "contract-1",
  dataset_version_id: "version-1",
  version_no: 1,
  columns: [
    {
      name: "alpha",
      ordinal: 0,
      physical_type: "VARCHAR",
      logical_type: "text",
      role: null,
      null_markers: [],
      detection_confidence: 1,
      detection_reason: "fixture",
      overridden: false,
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  derived_from: null,
};

function trail() {
  return screen.getByRole("navigation", { name: "Breadcrumb" });
}

beforeEach(() => {
  // The browser remembers a *different* project. This is the whole setup.
  window.localStorage.setItem("datacanvas.project", "project-b");
  vi.mocked(api.me).mockResolvedValue(ME);
  vi.mocked(api.version).mockResolvedValue(VERSION);
  vi.mocked(api.schema).mockResolvedValue(CONTRACT);
  vi.mocked(api.projects).mockResolvedValue(PROJECTS);
  vi.mocked(api.rows).mockResolvedValue({
    columns: ["alpha"],
    rows: [["a1"]],
    offset: 0,
    limit: 10,
    total_rows: 1,
  });
});

describe("orientation on the version page", () => {
  it("names the project this dataset is actually in", async () => {
    render(<VersionPage />);
    await screen.findByText("a1");

    // Not the remembered one. `Support` is what the brand link would have
    // delivered, and it must not be what the page claims to be in.
    expect(within(trail()).getByRole("link", { name: "Sales" })).toBeInTheDocument();
    expect(within(trail()).queryByText("Support")).not.toBeInTheDocument();
  });

  it("offers a way back to that project without the browser's back button", async () => {
    render(<VersionPage />);
    await screen.findByText("a1");

    // A real `<a href>`, so Cmd-click and middle-click work — a button with an
    // onClick would be an exit that only answers a plain left click.
    expect(within(trail()).getByRole("link", { name: "Sales" })).toHaveAttribute("href", "/");
  });

  it("marks the dataset as where you are, not as somewhere to go", async () => {
    render(<VersionPage />);
    await screen.findByText("a1");

    const here = within(trail()).getByText("penjualan_q3");
    expect(here).toHaveAttribute("aria-current", "page");
    expect(within(trail()).queryByRole("link", { name: "penjualan_q3" })).not.toBeInTheDocument();
  });

  it("does not read the separator out as content", async () => {
    render(<VersionPage />);
    await screen.findByText("a1");

    expect(trail().querySelector(".trail-sep")).toHaveAttribute("aria-hidden", "true");
  });
});
