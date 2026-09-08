"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LoadFailure } from "@/components/LoadFailure";
import { PreviewGrid } from "@/components/PreviewGrid";
import { AnalysisBoard } from "@/components/AnalysisBoard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Ellipsis } from "@/components/Ellipsis";
import { Trash } from "@/components/Icon";
import { ProfileCards } from "@/components/ProfileCards";
import { Shell } from "@/components/Shell";
import {
  ApiError,
  type DatasetProfile,
  type Dataset,
  type Me,
  type SchemaContract,
  api,
  describeFailure,
} from "@/lib/api";

/**
 * One Dataset: its rows, read according to its schema contract.
 *
 * This was two tabs and a warning banner. The Schema tab listed every column
 * with its confidence and a sentence explaining the guess; the banner named the
 * columns whose confidence fell below 0.8 and asked the user to look at them.
 *
 * Both are gone at the owner's direction. The reasoning against them is the
 * same one that emptied the shell: the product currently asks a first-time
 * visitor to make a dozen small judgements before they have looked at a single
 * row. The type under each column name is the detection, and the detection is
 * what FR-B.3 requires be shown for correction — the rest was commentary.
 *
 * FR-C.6 ("warn when detection is risky") is **P1**. Skipping a P1 is a product
 * decision; it is recorded in the project notes rather than left as something nobody
 * noticed. `detection_confidence` and `detection_reason` are still computed and
 * still stored on the contract — this removes a display, not a fact.
 *
 * The `v1 · schema v4` badge and the "Dataset dataset N" heading went the same
 * way. §14.2 put them in the header for P4 — *never be unsure which dataset you
 * are looking at* — and that requirement is now unmet in the UI on purpose,
 * recorded in the project notes rather than forgotten.
 *
 * **Nothing about the model changed.** A Dataset is still immutable
 * (INV-2) and a correction still produces a new SchemaContract instead of
 * overwriting one (INV-3), both enforced by Postgres triggers. They have to be:
 * §9.4 builds every step fingerprint from `dataset_id` and
 * `schema_contract_id`, and INV-6 — same fingerprint, same result — is what
 * makes the cache safe to trust. Take versioning out of the model and a step
 * computed under `qty: integer` and one computed under `qty: categorical` share
 * a fingerprint and disagree about the answer.
 */
/**
 * What each tab is called on screen.
 *
 * `Analysis` and not `Canvas`, though the product is DataCanvas: **D-014**
 * removed the free whiteboard and §16 keeps it a non-goal, so the word is
 * spoken for. What is built here is not one — the system lays results out and
 * nobody drags them — but a tab wearing that name invites the next person to
 * add dragging and to feel they are finishing it. `Analysis` is the term §9.2
 * already uses for exactly this thing.
 */
const TABS = ["profile", "preview", "analysis"] as const;
type Tab = (typeof TABS)[number];

const TAB_NAMES = {
  profile: "Profile",
  preview: "Preview",
  analysis: "Analysis",
} as const;

export default function VersionPage() {
  const router = useRouter();
  const params = useParams<{ datasetId: string }>();
  const datasetId = params.datasetId;

  const [me, setMe] = useState<Me | null>(null);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [contract, setContract] = useState<SchemaContract | null>(null);
  /**
   * Which tab is showing lives in the URL.
   *
   * It was `useState("profile")`, and the cost appeared the moment the
   * full-screen workspace existed: leaving it and coming back landed on
   * Profile, because the page had no memory of where the reader had been.
   * Which tab you are on is a fact about *where you are*, and that is what a
   * URL is for — it survives a reload, it survives back, and it can be sent
   * to somebody.
   */
  const search = useSearchParams();
  const asked = search.get("tab");
  const tab: Tab = TABS.includes(asked as Tab) ? (asked as Tab) : "profile";

  const setTab = useCallback(
    (next: Tab) => {
      // `replace` rather than `push`: flipping between tabs is not three
      // places to go back through. Entering the workspace is the navigation.
      router.replace(`/datasets/${datasetId}?tab=${next}`, { scroll: false });
    },
    [datasetId, router],
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /**
   * Deleting from here leaves nothing to come back to, so it navigates home
   * rather than re-rendering a page about a dataset that no longer exists.
   */
  async function remove() {
    if (dataset === null) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteDataset(dataset.id);
      router.push("/");
    } catch (cause) {
      setDeleteError(
        cause instanceof Error
          ? cause.message
          : "Could not delete that dataset.",
      );
      setDeleting(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setMe(await api.me());
      // This used to loop over `identity.workspaces`, trying the dataset id in
      // each until one answered something other than 404 — a search, in the
      // client, for which of the caller's tenants a URL belonged to. D-039
      // removed the question: there is one account, the session names it, and
      // the id in the path is either theirs or it is not.
      try {
        setDataset(await api.dataset(datasetId));
        setContract(await api.schema(datasetId));
      } catch (cause) {
        if (cause instanceof ApiError && cause.isMissing) {
          // Deliberately one message for two cases. The API answers 404 to
          // "not there" and to "not yours" alike (§13.3.1 L2), and a client
          // that guessed which would undo that.
          setError("That dataset does not exist, or is not yours.");
          return;
        }
        throw cause;
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setError(describeFailure(cause));
    } finally {
      setLoading(false);
    }
  }, [datasetId, router]);

  useEffect(() => {
    void load();
  }, [load]);

  // The header used to carry `v1 · schema v4`. Removed from the UI at the
  // owner's direction; the versions themselves are untouched — Dataset
  // is still immutable (INV-2) and a correction still creates a new
  // SchemaContract rather than overwriting one (INV-3), because the step
  // fingerprint in §9.4 is built from both ids and INV-6 depends on it.

  if (loading) {
    return (
      <Shell>
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  if (error || !dataset || !contract) {
    // `me` is passed here too: a page that failed to load is exactly where
    // someone might want to sign out, and stranding them would be worse.
    return (
      <Shell me={me}>
        <LoadFailure
          message={error ?? "This dataset is not available."}
          onRetry={() => void load()}
        />
      </Shell>
    );
  }

  /**
   * Switching project from here means leaving this dataset, so it navigates.
   *
   * The remembered project is written *before* the push, because `/` reads it
   * on mount — writing it afterwards would land the user on the project they
   * just left and then correct itself, which reads as the app changing its
   * mind.
   */
  return (
    <Shell me={me} up={{ href: "/", label: "Datasets" }}>
      {/* Which dataset this is. Nothing on this page said so: the heading went
          with the dataset badge (§14.2, 2026-07-31), and the dataset's identity
          left with it — not the intent of that decision, just its blast radius.
          The name alone, no dataset number: P4 comes back in Phase 3, attached
          to results rather than to a header. */}
      {/* Title row, because a page-level action belongs beside the thing it
          acts on. Not in the header: that is chrome shared by every screen, and
          a control there that destroys *this* dataset would be the one item in
          it that means something different on every page.

          Labelled `Delete`, where the card carries only a bin. The card is one
          of a grid and repeats its control twenty times, so an icon keeps the
          list quiet; here there is exactly one, there is room for a word, and a
          word is what a destructive control should have. */}
      <div className="title-row">
        <Ellipsis as="h1">{dataset.name}</Ellipsis>
        <button
          type="button"
          className="quiet-danger"
          onClick={() => setAsking(true)}
          disabled={asking}
        >
          <Trash size={16} />
          Delete
        </button>
      </div>

      {/* A dialog, and not the banner that used to sit here under the title.
          The banner put the name inside a sentence with nothing bounding it, so
          a 200-character one widened the banner past the window, gave the page
          a horizontal scrollbar, and took the title's marquee off the edge of
          the screen with it. `ConfirmDialog` says why the shape is also the
          right one for the question. */}
      <ConfirmDialog
        open={asking}
        title="Delete this dataset?"
        name={dataset.name}
        detail="The file goes with it, and nothing here can be undone."
        confirmLabel="Delete file"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={() => void remove()}
        onCancel={() => {
          setAsking(false);
          // Cleared on the way out, so re-opening the question does not show
          // the answer to the last one.
          setDeleteError(null);
        }}
      />

      {/* "891 rows · 12 columns" used to sit here. Both halves are stated
          again a few pixels below — the column count in the picker, the row
          count beside "View more" — and the counts down there move as you
          change what is shown, which this line never did. */}
      {!dataset.data_present ? (
        <div className="banner error">
          The rows for this dataset are no longer in storage. The schema is
          still here and can be corrected, but nothing can be read.
        </div>
      ) : null}

      {dataset.data_present ? (
        <>
          {/* Three tabs, and the order is the argument.
              Profile first because it answers the question somebody opening an
              unfamiliar dataset actually has — *what is in here, and what looks
              wrong* — and Preview answers the one they ask second, once they
              know which column to look at. §11.7.5 calls this orientation
              before depth.

              Analysis is third because it is what you do *after* orienting, and
              because it is the only one of the three that is not a lens on the
              current state: Profile and Preview are both derived from (dataset,
              contract) and hold nothing, while an Analysis accumulates. That
              difference is why the tab is the right container only for now —
              §9.2 makes `Analysis` an entity, one exploration session over one
              dataset, and a dataset may eventually have several. On the day it
              does, this becomes a route with an id in it rather than a tab.
              Building that route today would mean inventing an id for a table
              that does not exist (§20: a table created before it has a user
              rots, and so does a URL). */}
          <div
            className="tabs"
            role="tablist"
            aria-label="How to read this dataset"
          >
            {TABS.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                id={`tab-${name}`}
                aria-selected={tab === name}
                aria-controls={`panel-${name}`}
                className={tab === name ? "tab on" : "tab"}
                onClick={() => setTab(name)}
              >
                {TAB_NAMES[name]}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
            tabIndex={0}
          >
            {tab === "profile" ? (
              <ProfilePanel
                datasetId={datasetId}
                contractId={contract.id}
                onContractChanged={setContract}
              />
            ) : tab === "preview" ? (
              <PreviewGrid
                datasetId={datasetId}
                totalRows={dataset.row_count}
                contract={contract}
                onContractChanged={setContract}
              />
            ) : (
              <AnalysisBoard datasetId={datasetId} />
            )}
          </div>
        </>
      ) : (
        <p className="faint">No rows to show.</p>
      )}
    </Shell>
  );
}

/**
 * The Profile tab's data, fetched when it is shown.
 *
 * Keyed on ``contractId``, and that is the whole reason this is a component
 * rather than an effect in the page. Correcting a column's type produces a new
 * SchemaContract, which changes the §9.4 fingerprint, which means the profile
 * on screen is now about an interpretation nobody holds any more. Keying the
 * fetch on the contract makes the refresh automatic instead of something the
 * page has to remember — the same class of mistake `FR-C.4` exists to prevent
 * one layer down.
 *
 * It is also why this does not fetch until the tab is opened: profiling is a
 * pass over the file, and paying for it on a page somebody came to for the
 * grid would be spending their time on a question they did not ask.
 */
function ProfilePanel({
  datasetId,
  contractId,
  onContractChanged,
}: {
  datasetId: string;
  contractId: string;
  onContractChanged: (next: SchemaContract) => void;
}) {
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setProfile(null);
    try {
      setProfile(await api.profile(datasetId));
    } catch (cause) {
      setError(describeFailure(cause));
    }
  }, [datasetId]);

  useEffect(() => {
    // `contractId` is read so the linter keeps it in the dependency list, and
    // the comment says why rather than a disable directive: the value is the
    // trigger, not an input to the call.
    void contractId;
    void load();
  }, [load, contractId]);

  if (error) {
    return <LoadFailure message={error} onRetry={() => void load()} />;
  }
  if (!profile) {
    return <p className="muted">Reading every column…</p>;
  }
  return (
    <ProfileCards
      profile={profile}
      datasetId={datasetId}
      onContractChanged={onContractChanged}
    />
  );
}
