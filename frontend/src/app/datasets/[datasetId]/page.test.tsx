import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VersionPage from "@/app/datasets/[datasetId]/page";
import type {
  DatasetProfile,
  Dataset,
  Me,
  SchemaContract,
} from "@/lib/api";
import { api } from "@/lib/api";

/**
 * The dataset page has to say what you are looking at.
 *
 * This file was written for a different failure. Before D-036 the page could
 * not say which project it was in, and the only in-app way off it was the brand
 * link — which goes to `/`, which opened whichever project `localStorage` last
 * held. Opening a dataset belonging to project A from a bookmark while the
 * browser remembered project B put you in project B with nothing on screen
 * having said so.
 *
 * D-039 removed the level rather than the label. The home page lists every
 * dataset the account owns, so there is no project to be moved between, and the
 * two fields these tests were written to justify are gone from the response.
 * What is asserted now is the negative: that the page names no project, and
 * offers no second route home.
 */

// Built inside the factory, not above it. `vi.mock` is hoisted to the top of
// the file, so a top-level `const` it closes over does not exist yet when it
// runs. The router object is also created once and returned on every call:
// Next's own `useRouter` is stable across renders, and a fresh object each time
// changes the identity of `load`'s `useCallback`, which re-fires the effect
// that calls it — the page then reloads forever.
/** What the URL is asking for. Reset per test; empty means the default. */
let searchParams = "";

vi.mock("next/navigation", () => {
  const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
  return {
    useRouter: () => router,
    useParams: () => ({ datasetId: "dataset-1" }),
    // Which tab is showing moved into the URL, so that leaving the full-screen
    // workspace comes back to the tab the reader was on rather than to the
    // page's default.
    useSearchParams: () => new URLSearchParams(searchParams),
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      dataset: vi.fn(),
      schema: vi.fn(),
      profile: vi.fn(),
      rows: vi.fn(),
    },
  };
});

const ME: Me = {
  user: {
    id: "user-1",
    email: "someone@example.com",
    created_at: "2026-01-01T00:00:00Z",
  },
};

const VERSION: Dataset = {
  id: "dataset-1",
  owner_id: "user-1",
  name: "penjualan_q3",
  content_hash: "sha256:fixture",
  row_count: 1,
  column_count: 1,
  byte_size: 128,
  created_at: "2026-01-01T00:00:00Z",
  data_present: true,
};

const CONTRACT: SchemaContract = {
  id: "contract-1",
  dataset_id: "dataset-1",
  version_no: 1,
  columns: [
    {
      name: "alpha",
      ordinal: 0,
      physical_type: "VARCHAR",
      logical_type: "text",
      null_markers: [],
      detection_confidence: 1,
      detection_reason: "fixture",
      overridden: false,
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  derived_from: null,
};

/** The smallest bundle §11.8 can return: one column, one shape. */
const PROFILE: DatasetProfile = {
  computation_id: "00000000-0000-4000-8000-00000000c0de",
  fingerprint: "f".repeat(64),
  tool_name: "describe_dataset",
  tool_version: 1,
  computed_at: "2026-01-01T00:00:00Z",
  duration_ms: 4,
  row_count: 1,
  columns: [
    {
      name: "alpha",
      ordinal: 0,
      physical_type: "VARCHAR",
      logical_type: "text",
      kind: "text",
      total: 1,
      present: 1,
      distinct: 1,
      null_share: 0,
      conforming: 1,
      minimum: null,
      median: null,
      maximum: null,
      earliest: null,
      latest: null,
      bins: [],
      top: [],
      others_count: 0,
      others_distinct: 0,
      length_min: 2,
      length_median: 2,
      length_max: 2,
      samples: ["a1"],
      value: null,
    },
  ],
};

beforeEach(() => {
  searchParams = "";
  vi.mocked(api.me).mockResolvedValue(ME);
  vi.mocked(api.dataset).mockResolvedValue(VERSION);
  vi.mocked(api.schema).mockResolvedValue(CONTRACT);
  // The page opens on the Profile tab, so this call happens on every render
  // whether or not the test is about it.
  vi.mocked(api.profile).mockResolvedValue(PROFILE);
  vi.mocked(api.rows).mockResolvedValue({
    columns: ["alpha"],
    rows: [["a1"]],
    offset: 0,
    limit: 10,
    total_rows: 1,
  });
});

describe("orientation on the dataset page", () => {
  /**
   * Four tests stood here and all four asked the header what it said.
   *
   * D-036 put a breadcrumb there because this page had nothing naming the
   * dataset it showed. The same session then gave the page an `<h1>` carrying
   * that name — so from that day the header repeated a title already on
   * screen, and the breadcrumb was deleted once somebody looked at the two
   * together.
   *
   * The question those tests were really asking survives: *does this page say
   * what you are looking at?* It is asked of the heading now, which is the
   * thing that answers it.
   */

  it("opens the tab the URL asks for", async () => {
    // Reported after the full-screen workspace landed: leaving it came back
    // to Profile, because the page held the tab in `useState` and had no
    // memory of where the reader had been. Which tab you are on is a fact
    // about *where you are*, and that is what a URL is for.
    searchParams = "tab=analysis";
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    expect(screen.getByRole("tab", { name: /analysis/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /profile/i })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("falls back to Profile when the URL asks for nothing, or for nonsense", async () => {
    searchParams = "tab=whatever";
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    // A tab name nobody ships is not an error worth a screen — it is a URL
    // somebody edited, and the honest answer is the default.
    expect(screen.getByRole("tab", { name: /profile/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("names the dataset it is showing", async () => {
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    expect(
      screen.getByRole("heading", { level: 1, name: "penjualan_q3" }),
    ).toBeInTheDocument();
  });

  it("says it once, not twice", async () => {
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    // The whole reason the breadcrumb went. `getAllByText` rather than
    // `getByText` so this reports a duplicate rather than throwing on one.
    expect(screen.getAllByText("penjualan_q3")).toHaveLength(1);
  });

  it("offers two ways out, and they are not two copies of one thing", async () => {
    // This asserted *exactly one* way home until 2026-08-25, and the rule it
    // encoded was right at the time: the sidebar it replaced carried a
    // `Preview` link to `/` beside a mark that already went there, which is a
    // duplicate nav item wearing two labels.
    //
    // A labelled way up is not that. The mark is the constant — same corner,
    // every screen, always home. The `Datasets` control is contextual: it
    // appears only on a page with a parent and it names where it goes, which is
    // the question a bare arrow leaves unanswered. They point at the same place
    // here because the app is two levels deep; they are still different
    // affordances, and only one of them survives a third level.
    //
    // What has to stay true is that there is **one** of each. Three ways out of
    // a page is where the duplicate the old test guarded against comes back.
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    const out = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === "/");

    expect(out).toHaveLength(2);
    expect(out[0]).toHaveAccessibleName("DataCanvas home");
    expect(out[1]).toHaveAccessibleName("Datasets");
  });

  it("does not name a project the product no longer asks anyone to think about", async () => {
    render(<VersionPage />);
    await screen.findByRole("heading", { level: 1 });

    expect(screen.queryByText("Sales")).not.toBeInTheDocument();
    expect(screen.queryByText("Support")).not.toBeInTheDocument();
  });
});
