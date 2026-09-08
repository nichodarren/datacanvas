"use client";

import { useState } from "react";

import { ColumnPanel } from "@/components/ColumnPanel";

import { Ellipsis } from "@/components/Ellipsis";
import { TypeMenu } from "@/components/TypeMenu";
import { useDisclosure } from "@/hooks/useDisclosure";

import {
  type Bin,
  type ColumnProfile,
  type DatasetProfile,
  type SchemaContract,
  api,
} from "@/lib/api";

/**
 * The Profile tab: one card per column (FR-D.5, §11.8).
 *
 * ## One visual and one line of numbers
 *
 * Every card has the same skeleton — name, type badge, nulls, distinct — and
 * then exactly one shape underneath, chosen by `kind`. That restraint is the
 * design: the tab answers *which column needs attention*, and a card carrying
 * twelve statistics answers nothing at a glance. Depth is the column panel's
 * job, and it is allowed to be slow because it profiles one column at a time.
 *
 * ## Why three shapes ignore the type
 *
 * `empty`, `constant` and `unsupported` override the logical type, because on
 * those the normal shape is *misleading* rather than merely empty. A histogram
 * of a column that is 100% null is one empty frame; it looks like a finding and
 * is not one (§11.7.1).
 *
 * There was a fourth — `identifier` — removed 2026-08-21. A column of serial
 * numbers now draws a histogram and a median like any other numerical column.
 * That reading is misleading and the removal was made knowing it.
 *
 * The server decides which one. Re-deriving it here from `logical_type` plus
 * nulls plus distinct would put the ordering rule in two places, and two places
 * that must agree eventually do not.
 *
 * ## The heading and the receipt above the grid are gone
 *
 * `24 columns × 1,200 rows` and `describe_dataset v3 · ad66be1f` sat in a
 * `.section-head` here until 2026-08-26, removed at the owner's direction.
 *
 * The count is stated again on the dataset's card on the home screen, so only
 * the second one cost anything — and what it cost is named rather than
 * shrugged off. **INV-5** says every number on screen comes from a Computation
 * that can be referenced, and §14.2 already carries one note about a provenance
 * display being pulled: *"Bentuknya boleh berbeda — melekat pada hasil, bukan
 * pada header — tapi ia harus kembali."* This was that display. The fingerprint
 * is still computed, still stored, still returned in `DatasetProfile`; nothing
 * about the model moved. What is gone is the only place a person could read it,
 * and the debt is back on the books in the project notes where the last one was.
 *
 * ## The type badge is a control (FR-C.2, 2026-08-26)
 *
 * Clicking it opens the same menu the preview's column header opens, and picking
 * a type writes a new SchemaContract exactly as it does there. FR-C.2 asks that
 * a user *"can change a column's logical type from the list of supported
 * types"* — it names no surface, so this is a second way to the same P0 rather
 * than a widening of it.
 *
 * The §14 gesture table gave the header `click the type → change` and reserved
 * the *card* click for the full univariate profile (FR-D.5). Those two do not
 * collide today, because the card is not clickable yet — but they will the day
 * FR-D.5's other half lands, and this file is where that has to be got right:
 * the badge is a real `<button>`, a sibling in the card's flow. When the card
 * becomes activatable it must be through an **overlay link**, the way the
 * dataset card on the home screen does it, and not a click handler on the
 * `<article>` — a handler there fires for the badge too unless somebody
 * remembers to stop the event, and "somebody remembers" is the failure mode
 * this project keeps writing tests against.
 */
export function ProfileCards({
  profile,
  datasetId,
  onContractChanged,
}: {
  profile: DatasetProfile;
  datasetId: string;
  onContractChanged: (next: SchemaContract) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  /**
   * Which column's panel is open (FR-D.5, §11.7).
   *
   * Held here rather than inside the card, so ← and → in the panel can walk to
   * a column whose card is not the one that opened it. A card that owned its
   * own panel could only ever show itself.
   */
  const [open, setOpen] = useState<string | null>(null);

  /**
   * Correcting a type here re-reads the whole tab, and that is not waste.
   *
   * §11.8.1: the bundle has one `computation_id`, and §9.4 builds its
   * fingerprint from `schema_contract_id` — so a correction invalidates every
   * card, not only the one that was corrected. The page keys the profile fetch
   * on the contract id for exactly this reason, so handing the new contract up
   * is the whole of what this has to do.
   */
  async function correct(column: ColumnProfile, logicalType: string) {
    if (logicalType === column.logical_type) return;
    setError(null);
    try {
      onContractChanged(
        await api.correctSchema(datasetId, [
          { name: column.name, logical_type: logicalType },
        ]),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not change the type.",
      );
    }
  }

  if (profile.columns.length === 0) {
    return <p className="muted">This dataset has no columns.</p>;
  }

  return (
    <>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="profile-cards">
        {profile.columns.map((column) => (
          <ProfileCard
            key={column.name}
            column={column}
            onOpen={() => setOpen(column.name)}
            onCorrect={(type) => void correct(column, type)}
          />
        ))}
      </div>

      {open !== null ? (
        <ColumnPanel
          datasetId={datasetId}
          column={open}
          columns={profile.columns.map((c) => c.name)}
          onClose={() => setOpen(null)}
          onNavigate={setOpen}
        />
      ) : null}
    </>
  );
}

function ProfileCard({
  column,
  onOpen,
  onCorrect,
}: {
  column: ColumnProfile;
  onOpen: () => void;
  onCorrect: (logicalType: string) => void;
}) {
  const menu = useDisclosure<HTMLDivElement, HTMLButtonElement, HTMLDivElement>();

  return (
    // `data-type` rather than a class per type: the stylesheet owns the hue,
    // and the component owns the fact. A `className` computed here would put
    // the list of types in two places.
    //
    // It sits on the *card* rather than on the badge, which is the whole of
    // what changed on 2026-08-26. The badge still reads `--type`; it just
    // inherits it now, and so does everything else in the card — the bars, the
    // rule beside the sample values, the border. One attribute, one hue, every
    // element that should be wearing it.
    //
    // `logical_type`, not `kind`. A constant column is still a date column, and
    // the badge above it says so; painting its border grey would make the card
    // disagree with its own label.
    <article className="card profile typed" data-type={column.logical_type}>
      {/* An overlay button rather than a click handler on the `<article>`.
          The badge below opens the type picker (FR-C.2, D-046), and a handler
          on the card would fire for badge clicks too unless somebody
          remembered to stop the event — *"somebody remembers"* is the failure
          mode this project keeps writing tests against.

          Same shape the dataset card on the home screen uses, and it earns its
          keep the same way: two sibling controls, no event plumbing. It sits
          under the badge and the menu in the stacking order, so whichever the
          pointer is actually over is the one that answers. */}
      <button
        type="button"
        className="card-open"
        onClick={onOpen}
        aria-label={`Profile ${column.name}`}
      />

      <div className="card-top">
        <Ellipsis as="h3" className="col-name">
          {column.name}
        </Ellipsis>
        {/* The anchor is its own element rather than `.card-top`, so the menu
            hangs off the badge instead of off the whole row — and so the card
            keeps one containing block per popup when a second control ever
            joins this row. */}
        <div className="type-anchor" ref={menu.container}>
          <button
            type="button"
            ref={menu.trigger}
            className="pill tag"
            onClick={menu.toggle}
            aria-expanded={menu.open}
            aria-controls={menu.panelId}
            // Named, because the badge and one of the options it opens would
            // otherwise both be a button called `text`. It leads with the
            // visible word so the accessible name still contains the label
            // (SC 2.5.3, Label in Name) and says what pressing it does.
            aria-label={`${column.logical_type}, change how ${column.name} is read`}
            title={`Stored as ${column.physical_type} · click to change how it is read`}
          >
            {column.logical_type}
          </button>
          {menu.open ? (
            <TypeMenu
              panelRef={menu.panel}
              panelId={menu.panelId}
              current={column.logical_type}
              onPick={(type) => {
                // Focus returns to the badge, which is about to be re-rendered
                // rather than unmounted — the option that was clicked is not.
                menu.close(true);
                onCorrect(type);
              }}
            />
          ) : null}
        </div>
      </div>

      {/* Two facts that apply to any column whatever it holds: how complete it
          is, and how varied. Everything below them depends on the type. */}
      <div className="col-facts">
        <Fact label="nulls" value={formatShare(column.null_share)} />
        <Fact label="unique" value={column.distinct.toLocaleString("en")} />
      </div>

      <Shape column={column} />
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span className="caps">{label}</span>
      <strong className="mono">{value}</strong>
    </div>
  );
}

/** The one visual and one summary line this column gets (§11.8.3). */
function Shape({ column }: { column: ColumnProfile }) {
  switch (column.kind) {
    case "numerical":
      return (
        <>
          <Histogram bins={column.bins} />
          <Range
            min={compact(column.minimum)}
            mid={compact(column.median)}
            max={compact(column.maximum)}
          />
        </>
      );

    case "date":
      return (
        <>
          <Histogram bins={column.bins} />
          <p className="col-summary mono">
            {day(column.earliest)} → {day(column.latest)}
          </p>
        </>
      );

    case "categorical":
      return (
        <>
          <Bars column={column} />
          <p className="col-summary">
            {column.others_distinct > 0
              ? `+${column.others_distinct.toLocaleString("en")} more`
              : "all values shown"}
          </p>
        </>
      );

    case "boolean":
      return (
        <>
          <Bars column={column} />
          <p className="col-summary mono">
            {formatShare(shareOfTrue(column))} true
          </p>
        </>
      );

    case "text":
      return (
        <>
          {/* Values, not a chart. A frequency chart of 891 distinct values in
              891 rows draws three full-length bars of `1` — the eye reads a
              pattern that is not there. Three real values say more. */}
          <ul className="col-samples mono">
            {column.samples.map((sample) => (
              <Ellipsis as="li" key={sample}>
                {sample}
              </Ellipsis>
            ))}
          </ul>
          <Range
            min={round(column.length_min)}
            mid={round(column.length_median)}
            max={round(column.length_max)}
            unit="chars"
          />
        </>
      );

    case "constant":
      return (
        <Note>
          one value: <strong className="mono">{column.value}</strong>
        </Note>
      );

    case "empty":
      return <Note>every row is empty</Note>;

    case "unsupported":
      return (
        <Note>
          <span className="mono">{column.physical_type}</span>, not a flat
          column
        </Note>
      );
  }
}

/**
 * Three numbers that describe a spread, each said out loud.
 *
 * The line used to be `0 · 0.2 · 0.5` and `13·20·24 chars` — the same three
 * quantities in two spellings, neither of which said which number was which.
 * A reader who knows the convention reads them correctly; a reader who does not
 * has no way to find out from the card, and the card is the orientation
 * surface. Six tokens is barely wider than three and removes the guess.
 *
 * The labels are sans and dimmer while the numbers stay mono. That is not
 * decoration: mono is what makes `0.2` line up under `12.2` down a column of
 * cards, and giving the captions the same weight as the values would turn one
 * fact into six things to read.
 */
function Range({
  min,
  mid,
  max,
  unit,
}: {
  min: string;
  mid: string;
  max: string;
  unit?: string;
}) {
  return (
    <p className="col-summary mono">
      <span className="tick">min</span> {min} ·{" "}
      <span className="tick">med</span> {mid} ·{" "}
      <span className="tick">max</span> {max}
      {unit ? <span className="tick"> {unit}</span> : null}
    </p>
  );
}

/**
 * What a card says when a chart would mislead.
 *
 * Three of the four cases that land here — empty, constant, unsupported — could
 * all be drawn. A column that is 100% null has a histogram: one empty frame. A
 * constant column has a bar chart: one bar at 100%. Both look like findings and
 * neither is one, so the card says the fact in words instead.
 */
function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="col-note">
      <p>{children}</p>
    </div>
  );
}

function Histogram({ bins }: { bins: Bin[] }) {
  const tallest = Math.max(1, ...bins.map((b) => b.count));

  return (
    <div className="histogram" aria-hidden="true">
      {bins.map((bin) => (
        <span
          key={bin.lower}
          className="bar"
          // Percentage of the tallest bar, not of the row count: a column where
          // one bucket holds 98% would otherwise render as one visible bar and
          // nine invisible ones, which is true and unreadable.
          style={{ height: `${Math.max(2, (bin.count / tallest) * 100)}%` }}
          title={`${compact(bin.lower)} – ${compact(bin.upper)}: ${bin.count.toLocaleString("en")}`}
        />
      ))}
    </div>
  );
}

/**
 * Top values as labelled bars.
 *
 * Labelled, and that is the whole difference from the mockup this replaces.
 * Bars without their values make the eye believe there is a pattern it cannot
 * read; `male 577` over `female 314` says the same thing and can be checked.
 */
function Bars({ column }: { column: ColumnProfile }) {
  const widest = Math.max(1, ...column.top.map((t) => t.count));

  return (
    <ul className="value-bars">
      {column.top.map((item) => (
        <li key={item.value}>
          <Ellipsis className="label">{item.value}</Ellipsis>
          <span className="track">
            <span
              className="fill"
              style={{ width: `${(item.count / widest) * 100}%` }}
            />
          </span>
          <span className="mono count">{item.count.toLocaleString("en")}</span>
        </li>
      ))}
    </ul>
  );
}

function shareOfTrue(column: ColumnProfile): number {
  const counts = Object.fromEntries(column.top.map((t) => [t.value, t.count]));
  const total = (counts.true ?? 0) + (counts.false ?? 0);
  return total === 0 ? 0 : (counts.true ?? 0) / total;
}

function formatShare(share: number): string {
  if (share === 0) return "0%";
  // Below a tenth of a percent, one decimal place rounds to `0.0%`, which reads
  // as none. `<0.1%` says the true thing in the same width.
  if (share < 0.001) return "<0.1%";
  return `${(share * 100).toFixed(1)}%`;
}

/**
 * A number short enough for a card.
 *
 * `512.3292` and `2350619.5` both have to fit the same slot, so magnitude
 * decides the form. `Intl.NumberFormat` with `notation: "compact"` gives `2.4M`
 * for the second without inventing precision the first does not have.
 */
function compact(value: number | null): string {
  if (value === null) return "n/a";
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude >= 100_000 || magnitude < 0.001)) {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(
    value,
  );
}

function round(value: number | null): string {
  return value === null ? "n/a" : String(Math.round(value));
}

/** A timestamp as the card shows it: the day, without the time nobody reads. */
function day(iso: string | null): string {
  return iso === null ? "n/a" : iso.slice(0, 10);
}
