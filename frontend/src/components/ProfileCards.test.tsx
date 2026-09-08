import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileCards } from "@/components/ProfileCards";
import {
  LOGICAL_TYPES,
  type ColumnProfile,
  type DatasetProfile,
  type ProfileKind,
  type SchemaContract,
  api,
} from "@/lib/api";

/**
 * The summary line under each card has to say *which* number is which.
 *
 * It used to read `0 · 0.2 · 0.5` for a numerical column and `13·20·24 chars`
 * for a text one — the same three quantities, two spellings, and neither said
 * that the middle figure was a median. Anyone who knows the convention reads it
 * correctly; anyone who does not has nowhere to find out, and this tab is the
 * orientation surface.
 *
 * What makes it worth a test rather than a glance: the labels come from a
 * shared `Range` component now, so `numerical` and `text` are one code path
 * where they were two. A change to either silently changes both, and the two
 * are the ones that must **not** drift apart again — matching their spacing is
 * half of why the component exists.
 */

const BASE: ColumnProfile = {
  name: "col",
  ordinal: 0,
  physical_type: "VARCHAR",
  logical_type: "text",
  kind: "text",
  total: 100,
  present: 100,
  distinct: 40,
  null_share: 0,
  conforming: 100,
  minimum: null,
  median: null,
  maximum: null,
  earliest: null,
  latest: null,
  bins: [],
  top: [],
  others_count: 0,
  others_distinct: 0,
  length_min: null,
  length_median: null,
  length_max: null,
  samples: [],
  value: null,
};

function column(kind: ProfileKind, fields: Partial<ColumnProfile>): ColumnProfile {
  return { ...BASE, kind, logical_type: kind, ...fields };
}

function show(...columns: ColumnProfile[]) {
  const profile: DatasetProfile = {
    computation_id: "c0ffee00-0000-4000-8000-000000000000",
    fingerprint: "f".repeat(64),
    tool_name: "describe_dataset",
    tool_version: 3,
    computed_at: "2026-01-01T00:00:00Z",
    duration_ms: 12,
    row_count: 100,
    columns,
  };
  render(
    <ProfileCards
      profile={profile}
      datasetId="dataset-1"
      onContractChanged={() => {}}
    />,
  );
}

/**
 * One card's summary line, with runs of whitespace flattened the way a reader
 * sees it.
 *
 * Reached by class rather than by role or text: the labels and the figures are
 * separate spans, so a text query matches whichever fragment it lands on rather
 * than the sentence the reader actually reads. The whole line is the assertion
 * here, and the line is the element.
 */
function summaryOf(name: string): string {
  const heading = screen.getByRole("heading", { level: 3, name });
  const card = heading.closest("article");
  expect(card).not.toBeNull();
  const line = (card as HTMLElement).querySelector(".col-summary");
  expect(line, `${name} has no summary line`).not.toBeNull();
  return line!.textContent!.replace(/\s+/g, " ").trim();
}

describe("the summary line", () => {
  it("names min, median and max on a numerical column", () => {
    show(
      column("numerical", {
        name: "amount",
        minimum: 0,
        median: 0.2,
        maximum: 0.5,
        bins: [{ lower: 0, upper: 0.5, count: 100 }],
      }),
    );

    expect(summaryOf("amount")).toBe("min 0 · med 0.2 · max 0.5");
  });

  it("names them on a text column too, and spells the spacing the same way", () => {
    // The point of the assertion is the separator, not the numbers. `13·20·24`
    // and `min 13 · med 20 · max 24` describe the same column; only one of them
    // matches the card sitting next to it.
    show(
      column("text", {
        name: "product_name",
        length_min: 13,
        length_median: 20,
        length_max: 24,
        samples: ["compact adapter 11cm"],
      }),
    );

    expect(summaryOf("product_name")).toBe("min 13 · med 20 · max 24 chars");
  });

  it("keeps the unit on the text card and off the numerical one", () => {
    // `chars` is what stops `13 · 20 · 24` being read as a range of values.
    // A numerical column has no unit we know of, so it does not invent one.
    show(
      column("numerical", { name: "qty", minimum: 1, median: 3, maximum: 5 }),
      column("text", {
        name: "note",
        length_min: 4,
        length_median: 9,
        length_max: 90,
        samples: ["a"],
      }),
    );

    expect(summaryOf("qty")).not.toContain("chars");
    expect(summaryOf("note")).toContain("chars");
  });

  it("says nothing rather than guessing when a statistic is missing", () => {
    // A column typed numerical whose values are all unreadable has no minimum.
    // `min undefined` would be worse than an em dash, and `min 0` far worse.
    show(column("numerical", { name: "broken", minimum: null, median: null, maximum: null }));

    expect(summaryOf("broken")).toBe("min n/a · med n/a · max n/a");
  });
});


/**
 * Correcting a type from the card the problem is visible on (FR-C.2).
 *
 * The requirement names no surface — it asks that a user can change a column's
 * logical type from the list of supported types — so this is a second route to
 * one P0 rather than a widening of it. The card is arguably the better of the
 * two: the reason to doubt a type is the histogram or the sample values printed
 * directly under the badge, and until now the only way to act on that doubt was
 * to change tabs.
 */
describe("changing how a column is read, from its card", () => {
  afterEach(() => vi.restoreAllMocks());

  /**
   * The badge, by the name it announces rather than the word it shows.
   *
   * They differ on purpose: the badge and one of the five options it opens
   * would otherwise both be a button called `text`, which is ambiguous to a
   * screen reader before it is ambiguous to a query.
   */
  function badge(): HTMLElement {
    return screen.getByRole("button", { name: /change how/ });
  }

  function show(logicalType: string) {
    const profile: DatasetProfile = {
      computation_id: "c0ffee00-0000-4000-8000-000000000000",
      fingerprint: "f".repeat(64),
      tool_name: "describe_dataset",
      tool_version: 3,
      computed_at: "2026-01-01T00:00:00Z",
      duration_ms: 12,
      row_count: 100,
      columns: [{ ...BASE, name: "shipped_at", logical_type: logicalType }],
    };
    const onContractChanged = vi.fn();
    render(
      <ProfileCards
        profile={profile}
        datasetId="dataset-1"
        onContractChanged={onContractChanged}
      />,
    );
    return { onContractChanged };
  }

  it("opens the same five options the preview offers", async () => {
    show("text");
    await userEvent.setup().click(badge());

    for (const type of LOGICAL_TYPES) {
      expect(screen.getByRole("button", { name: type })).toHaveAttribute(
        "data-type",
        type,
      );
    }
    expect(screen.getByRole("button", { name: "date" })).not.toHaveClass(
      "current",
    );
  });

  it("writes a new contract and hands it up", async () => {
    const contract = { id: "contract-2" } as SchemaContract;
    const correct = vi
      .spyOn(api, "correctSchema")
      .mockResolvedValue(contract);
    const { onContractChanged } = show("text");
    const user = userEvent.setup();

    await user.click(badge());
    await user.click(screen.getByRole("button", { name: "date" }));

    expect(correct).toHaveBeenCalledWith("dataset-1", [
      { name: "shipped_at", logical_type: "date" },
    ]);
    // Handed up rather than kept: §9.4 folds `schema_contract_id` into the
    // bundle's fingerprint, so a correction invalidates every card and the page
    // has to re-read the tab, not just this one.
    expect(onContractChanged).toHaveBeenCalledWith(contract);
  });

  it("does not ask the server to set the type it already has", async () => {
    const correct = vi.spyOn(api, "correctSchema");
    show("text");
    const user = userEvent.setup();

    await user.click(badge());
    // The option for the type it already has, which is the one marked current.
    await user.click(screen.getByRole("button", { name: "text" }));

    expect(correct).not.toHaveBeenCalled();
  });

  it("says so when the correction is refused, and keeps the card", async () => {
    vi.spyOn(api, "correctSchema").mockRejectedValue(
      new Error("That type would discard 412 values."),
    );
    show("text");
    const user = userEvent.setup();

    await user.click(badge());
    await user.click(screen.getByRole("button", { name: "boolean" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That type would discard 412 values.",
    );
    expect(screen.getByText("shipped_at")).toBeInTheDocument();
  });
});

/**
 * The card is a way in now (FR-D.5), and the badge inside it still is not.
 *
 * This is the collision §14's gesture table set up and D-046 flagged as owed:
 * clicking the card opens the full profile, clicking the badge opens the type
 * picker, and they sit inside one another. The resolution is structural — an
 * overlay button that is a *sibling* of the badge rather than a handler on the
 * `<article>` — so there is no event to stop and nothing for anyone to
 * remember. These two assertions are what says the structure is still there.
 */
describe("opening a column", () => {
  function cards(logicalType = "text") {
    const profile: DatasetProfile = {
      computation_id: "c0ffee00-0000-4000-8000-000000000000",
      fingerprint: "f".repeat(64),
      tool_name: "describe_dataset",
      tool_version: 3,
      computed_at: "2026-01-01T00:00:00Z",
      duration_ms: 12,
      row_count: 100,
      columns: [{ ...BASE, name: "shipped_at", logical_type: logicalType }],
    };
    render(
      <ProfileCards
        profile={profile}
        datasetId="dataset-1"
        onContractChanged={() => {}}
      />,
    );
  }

  it("gives the card its own control rather than a handler on the card", () => {
    cards();

    // A `<button>`, not an `onClick` on the `<article>`. A handler there fires
    // for the badge too unless somebody stops the event, and *"somebody
    // remembers"* is the failure mode this project keeps writing tests against.
    const open = screen.getByRole("button", { name: "Profile shipped_at" });
    expect(open).toHaveClass("card-open");
    expect(open.closest("article")).toHaveClass("card", "profile");
  });

  it("does not open the panel when the badge is pressed", async () => {
    const fetched = vi.spyOn(api, "columnProfile");
    cards();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /change how/ }));

    // The badge opens the type picker. If the panel had opened too, the profile
    // would have been fetched — which is the cheapest thing to assert and the
    // one that fails if the overlay ever becomes a handler on the card.
    expect(screen.getByRole("button", { name: "date" })).toBeInTheDocument();
    expect(fetched).not.toHaveBeenCalled();
  });
});
