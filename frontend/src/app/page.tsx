"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Ellipsis } from "@/components/Ellipsis";
import { FormatIcon, Search, Table, Trash } from "@/components/Icon";
import { LoadFailure } from "@/components/LoadFailure";
import { Shell } from "@/components/Shell";
import { Upload } from "@/components/Upload";
import {
  ApiError,
  type DatasetSummary,
  type Me,
  type SampleDataset,
  api,
  describeFailure,
} from "@/lib/api";

/**
 * The first screen after signing in.
 *
 * Rebuilt after the first person to use it said, in as many words, *"I don't
 * know what I'm supposed to do or in what order."* Three things were wrong, and
 * only one of them was a matter of taste:
 *
 * 1. **The dataset rows were not clickable.** Upload redirected you to the grid,
 *    but coming back later left you looking at a list of your own data with no
 *    way into any of it. A genuine dead end, and most of the confusion.
 * 2. **Nothing named the first action.** "Add data" and "Datasets" were two
 *    headings of equal weight; neither said *start here*.
 * 3. **The empty state was empty.** §14.5 forbids exactly that — *"orang perlu
 *    melihat produknya bekerja sebelum mengunggah data mereka"* — so samples
 *    (FR-B.5) now sit beside the drop zone.
 *
 * What the screen does **not** do is ask the user to create a project first.
 * The project level is no longer named on it either (D-039).
 */
export default function HomePage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [samples, setSamples] = useState<SampleDataset[]>([]);
  /** What the header's field is filtering the list by. Client-side, over the
      datasets already fetched — there is no search route to call. */
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  /** An action failed; the page around it still works. Shown as a banner. */
  const [error, setError] = useState<string | null>(null);

  /**
   * The page itself could not load — which means no identity, and therefore no
   * upload, no samples and no account menu. Kept apart from `error` because the
   * two need opposite treatments: a banner sits above a working page, and this
   * one has to *replace* the body. See `LoadFailure`.
   */
  const [fatal, setFatal] = useState<string | null>(null);

  /**
   * Every dataset the account has, in one call.
   *
   * This was a `Promise.all` across a project list, flattened and re-sorted
   * here — the client compensating for a route that could only answer for one
   * project at a time. D-039 took the level out of the schema, so the server
   * answers the question that was actually being asked, and the compensation
   * goes with it.
   */
  const load = useCallback(async () => {
    setLoading(true);
    setFatal(null);
    try {
      setMe(await api.me());
      setDatasets(await api.datasets());
      setSamples(await api.samples());
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setFatal(describeFailure(cause));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadSample(key: string) {
    setBusy(key);
    setError(null);
    try {
      const created = await api.loadSample(key);
      router.push(`/datasets/${created.dataset.id}`);
    } catch (cause) {
      // A banner, not a `LoadFailure`: the sample did not load, but the page
      // around it — the drop zone, the other samples — still works.
      setError(describeFailure(cause));
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <Shell>
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  if (fatal) {
    // `me` is passed if we have it, so signing out stays reachable from a page
    // that failed. It usually will not be — the call that produces `fatal` is
    // the one that fetches it — and the header is then brand-only, which is
    // still one working control more than this screen used to offer.
    return (
      <Shell me={me}>
        <LoadFailure message={fatal} onRetry={() => void load()} />
      </Shell>
    );
  }

  /**
   * The project breadcrumb used to sit here. It is gone from the screen — the
   * ownership chain the owner settled on is account → dataset, and a level
   * nobody chose is a level nobody should have to read past.
   *
   * The *entity* is still there, and this file still holds one: every dataset
   * route is `/workspaces/{id}/projects/{id}/datasets`, so removing it for
   * real is a migration and a route change, not a render change. What comes
   * off here is the claim that the user has to care.
   */
  const search = (
    <div className="search">
      <span className="glyph">
        <Search size={18} />
      </span>
      <input
        type="search"
        value={query}
        placeholder="Filter datasets by name…"
        aria-label="Filter datasets by name"
        onChange={(event) => setQuery(event.target.value)}
      />
    </div>
  );

  const empty = datasets.length === 0;

  const needle = query.trim().toLowerCase();
  const shown = needle
    ? datasets.filter((dataset) => dataset.name.toLowerCase().includes(needle))
    : datasets;

  return (
    <Shell headerExtras={search} me={me}>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      {/* The mockup gives this screen no title — it opens on the drop zone.
          The heading stays in the document because a page without one cannot
          be navigated by heading, and losing that would be a real cost paid
          for a visual choice. Drawn or not, it is the page's name. */}
      <h1 className="sr-only">Datasets</h1>

      {/* One layout, not two.

          This page used to branch: an account with data got the drop zone, a
          section head and a grid of cards, and an account without got a
          different screen — its own headline, its own measure, its own
          arrangement. Nobody planned that; the empty state was written first
          and the populated one was restyled without it.

          The cost was paid by exactly the wrong person. A first-time user, who
          has the least idea what this product is, met the layout that had been
          designed least, and then watched it rearrange itself the moment they
          uploaded anything. The shape is now the same from the first second:
          drop zone, `Recent datasets`, cards. What changes is only what fills
          the grid. */}
      <Upload
        onCommitted={(datasetId) => router.push(`/versions/${datasetId}`)}
      />

      {/* The mockup pairs this heading with a `View All` button. There is
          nowhere for it to go: the grid below is already every dataset the
          account has, so the link would lead back to the page it was pressed
          on. */}
      <div className="section-head">
        <h2>
          {empty ? "No file to hand? Try one of these" : "Recent datasets"}
        </h2>
      </div>

      {empty ? (
        /* §14.5 forbids an empty empty-state — *"orang perlu melihat produknya
           bekerja sebelum mengunggah data mereka"* — so the grid that will hold
           their datasets holds the bundled samples until it can hold theirs.
           Same grid, same card, same place on the screen. */
        <div className="cards">
          {samples.map((sample) => (
            <button
              key={sample.key}
              type="button"
              className="card sample"
              disabled={busy !== null}
              onClick={() => void loadSample(sample.key)}
            >
              <div className="card-top">
                <span className="type-icon">
                  <Table />
                </span>
              </div>
              <div>
                <h3 className="dataset-name name">{sample.name}</h3>
                <p className="description">{sample.description}</p>
              </div>
              <div className="card-foot">
                <span>Bundled sample</span>
                {busy === sample.key ? (
                  <span className="pill working">Loading…</span>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      ) : shown.length === 0 ? (
        <p className="muted">
          Nothing here matches <strong>{query.trim()}</strong>.
        </p>
      ) : (
        <div className="cards">
          {shown.map((dataset) => (
            <DatasetCard key={dataset.id} dataset={dataset} onDeleted={load} />
          ))}
        </div>
      )}

      {/* Pressing a sample disables every card and drops a pill into the one
          that was pressed — both invisible to someone who cannot see them, and
          the button they just activated goes silent because it is now
          disabled. This says the same thing in the channel that is left. */}
      <p className="sr-only" aria-live="polite">
        {busy === null ? "" : "Loading the sample dataset…"}
      </p>
    </Shell>
  );
}

/**
 * One dataset, as something you can act on.
 *
 * This card used to carry a `n to check` badge counting columns whose detection
 * confidence fell below 0.8. It came out with the signal it pointed at: the
 * grid no longer marks those columns, so a badge here would send someone
 * looking for something they cannot find — the worst kind of warning, since it
 * cannot be satisfied.
 *
 * `schema vN` went too. The card answers *which of these do I want to open* and
 * a schema version number has never helped with that; it belongs on the version
 * page, where it is feedback for a correction you just made.
 *
 * ## The status pill
 *
 * Two states, and both are facts the API already answers rather than a
 * simulation of progress. `latest_dataset_id` is either there or it is not.
 *
 * The mockup drew a third thing under the PROCESSING card — a bar filled to
 * one third and pulsing. It is not here. Nothing in this system knows what
 * fraction of the work is done, so a bar at 33% is a number the interface made
 * up, and P3 is the one promise this product cannot be casual about. The pill
 * says the true thing in a word.
 */
function DatasetCard({
  dataset,
  onDeleted,
}: {
  dataset: DatasetSummary;
  onDeleted: () => void;
}) {
  // Every dataset opens. `latest_version_id` used to decide this and could be
  // null — a dataset with no version at all, which the card drew as `No
  // version`. D-043 made that state unrepresentable: a dataset is its data.
  const target = `/datasets/${dataset.id}`;

  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setDeleting(true);
    setError(null);
    try {
      await api.deleteDataset(dataset.id);
      onDeleted();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not delete that dataset.",
      );
      setDeleting(false);
    }
  }

  return (
    <div className="card dataset">
      {/* The whole card opens the dataset, and it is a link stretched over the
          card rather than a link *around* it.

          It was a link around it until the delete button arrived, and a
          `<button>` inside an `<a>` is invalid HTML with a click that belongs
          to whichever of them wins. The usual fix is to stretch the name's own
          link with `::after`, and that one is unavailable here: the name is a
          marquee, the marquee is a transform, and a transformed element becomes
          the containing block for its own pseudo-element — the overlay would
          slide along with the text.

          So the overlay is its own element. It carries `Open` in front of the
          name, which is what makes it a different thing from the heading rather
          than the heading read out twice. */}
      {target && !asking ? (
        <Link
          href={target}
          className="card-open"
          aria-label={`Open ${dataset.name}`}
        />
      ) : null}

      {/* One block, not three (2026-08-25). The card was a tile on its own row,
          a name below it, and a foot carrying an upload time opposite a `Ready`
          pill. The pill said the same thing about every dataset in the list, so
          it went; and what remained was a divider and one date holding down
          eighty pixels of card.

          The tile now sits beside the name it belongs to and every fact about
          the file shares one line. Nothing was dropped except the pill — the
          mockup's fourth spec, a byte size, is still absent because the list
          route still does not return one. */}
      {asking ? null : (
        <div className="card-head">
          <span className="type-icon">
            <FormatIcon name={dataset.name} />
          </span>
          <div className="card-id">
            <Ellipsis as="h3" className="dataset-name">
              {dataset.name}
            </Ellipsis>
            <div className="specs">
              {dataset.row_count === null ? (
                <span>not read yet</span>
              ) : (
                <>
                  <span>{dataset.row_count.toLocaleString()} rows</span>
                  <span className="dot" aria-hidden="true" />
                  <span>{dataset.column_count} cols</span>
                </>
              )}
              <span className="dot" aria-hidden="true" />
              <span className="ago">{since(dataset.created_at)}</span>
            </div>
          </div>
        </div>
      )}

      {/* `Ready` was removed; this was not. A dataset with no version cannot be
          opened, and the only other thing saying so is that the card has no
          overlay — which is a difference you find by clicking and getting
          nothing. */}
      {target || asking ? null : (
        <div className="card-foot">
          <span className="pill working">No version</span>
        </div>
      )}

      {/* NFR-UX.1: nothing destructive without being asked first, and the
          question names the file so a grid of five cards cannot be confused for
          one another (W-2). The overlay above is not rendered while it is up,
          so a stray click aimed at `Cancel` cannot navigate away instead.

          The name is on a line of its own rather than inside the sentence, and
          that is what fixed it. Set inline, a ninety-character filename wrapped
          to three lines and pushed the buttons out through the bottom of the
          card. On its own line it is one more piece of text too long for its
          box — which this interface already knows how to show. */}
      {asking ? (
        <div className="card-confirm" role="alert">
          {/* Two rows, because the card is a fixed size and this has to live
              inside it. The name sits *in* the question rather than under it,
              and it is the part allowed to shrink — so a ninety-character
              filename slides through the gap instead of adding a line. */}
          <p className="ask">
            <span>Delete</span>
            <Ellipsis className="confirm-name">{dataset.name}</Ellipsis>
            <span aria-hidden="true">?</span>
          </p>
          {error ? (
            <p className="error-text">{error}</p>
          ) : (
            <div className="row">
              {/* `Delete file`, not `Delete`. The consequence belongs at the
                  point of action: NFR-UX.1 wants it said, and a sentence above
                  the button costs a line this card does not have. */}
              <button
                type="button"
                className="danger"
                disabled={deleting}
                onClick={() => void remove()}
              >
                {deleting ? "Deleting…" : "Delete file"}
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => setAsking(false)}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      ) : (
        <button
          type="button"
          className="card-delete"
          onClick={() => setAsking(true)}
          aria-label={`Delete ${dataset.name}`}
        >
          <Trash size={16} />
        </button>
      )}
    </div>
  );
}

/**
 * "2 hours ago", from an ISO timestamp.
 *
 * `Intl.RelativeTimeFormat` rather than a hand-rolled ladder of ifs: it is in
 * every browser this ships to, it knows the plural rules, and it is the one
 * place a locale change would need to reach.
 *
 * Safe to compute during render here because this page is a client component
 * whose data arrives from a `useEffect` — there is no server-rendered markup
 * carrying a different `Date.now()` for React to disagree with.
 */
const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

const STEPS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

function since(iso: string): string {
  const seconds = (Date.parse(iso) - Date.now()) / 1000;
  if (!Number.isFinite(seconds)) return "";
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size)
      return RELATIVE.format(Math.round(seconds / size), unit);
  }
  return "just now";
}
