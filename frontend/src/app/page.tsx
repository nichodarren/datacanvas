"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LoadFailure } from "@/components/LoadFailure";
import { Shell } from "@/components/Shell";
import { Trail } from "@/components/Trail";
import { Upload } from "@/components/Upload";
import { recallProject, rememberProject } from "@/lib/lastProject";
import {
  ApiError,
  type DatasetSummary,
  type Me,
  type Project,
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
 * See ``ProjectPicker`` for why.
 */
export default function HomePage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [samples, setSamples] = useState<SampleDataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  /** An action failed; the page around it still works. Shown as a banner. */
  const [error, setError] = useState<string | null>(null);

  /**
   * The page itself could not load — which means no identity, and therefore no
   * project, no upload, no samples and no account menu. Kept apart from `error`
   * because the two need opposite treatments: a banner sits above a working
   * page, and this one has to *replace* the body. See `LoadFailure`.
   */
  const [fatal, setFatal] = useState<string | null>(null);

  const workspace = me?.workspaces[0] ?? null;

  const loadDatasets = useCallback(async (workspaceId: string, projectId: string) => {
    setDatasets(await api.datasets(workspaceId, projectId));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setFatal(null);
    try {
      const identity = await api.me();
      setMe(identity);
      const firstWorkspace = identity.workspaces[0];
      if (!firstWorkspace) return;

      const found = await api.projects(firstWorkspace.id);
      setProjects(found);

      // Come back to where you were. A tool that always drops you in the same
      // place regardless of what you were doing makes you re-navigate every
      // visit, and that cost is paid every single time.
      const remembered = recallProject();
      const chosen = found.find((item) => item.id === remembered) ?? found[0] ?? null;
      setProject(chosen);
      if (chosen) await loadDatasets(firstWorkspace.id, chosen.id);

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
  }, [router, loadDatasets]);

  useEffect(() => {
    void load();
  }, [load]);

  async function selectProject(next: Project) {
    if (!workspace) return;
    setProject(next);
    rememberProject(next.id);
    setDatasets([]);
    await loadDatasets(workspace.id, next.id);
  }

  async function createProject(name: string) {
    if (!workspace) return;
    const created = await api.createProject(workspace.id, name);
    setProjects([...projects, created]);
    await selectProject(created);
  }

  async function loadSample(key: string) {
    if (!workspace || !project) return;
    setBusy(key);
    setError(null);
    try {
      const created = await api.loadSample(workspace.id, project.id, key);
      router.push(`/versions/${created.version.id}`);
    } catch (cause) {
      // A banner, not a `LoadFailure`: the sample did not load, but the page
      // around it — projects, upload, the other samples — still works.
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

  const picker = workspace ? (
    <Trail
      project={project}
      projects={projects}
      atProject
      onSelect={(next) => void selectProject(next)}
      onCreate={createProject}
    />
  ) : undefined;

  const empty = datasets.length === 0;

  return (
    <Shell headerExtras={picker} me={me}>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      {empty ? (
        <section className="start">
          <h1>Start by adding data</h1>
          <p className="muted" style={{ marginTop: 0 }}>
            Everything else in DataCanvas begins with a file.
          </p>

          {workspace && project ? (
            <Upload
              workspaceId={workspace.id}
              projectId={project.id}
              onCommitted={(versionId) => router.push(`/versions/${versionId}`)}
            />
          ) : null}

          {/* The order, stated before it is walked. §14.3 describes this
              sequence; a first-time user cannot be expected to infer it. */}
          <ol className="steps">
            <li>
              <strong>Confirm how it reads</strong>
              <span className="faint"> — delimiter, encoding, header row</span>
            </li>
            <li>
              <strong>Check the column types</strong>
              <span className="faint"> — worked out by scanning the whole file</span>
            </li>
            <li>
              <strong>Browse the data</strong>
              <span className="faint"> — and correct any type that looks wrong</span>
            </li>
          </ol>

          {samples.length > 0 ? (
            <>
              <h2>No file to hand? Try one of these</h2>
              <div className="cards">
                {samples.map((sample) => (
                  <button
                    key={sample.key}
                    type="button"
                    className="card sample"
                    disabled={busy !== null}
                    onClick={() => void loadSample(sample.key)}
                  >
                    <strong>{sample.name}</strong>
                    <span className="faint">{sample.description}</span>
                    {busy === sample.key ? <span className="pill">Loading…</span> : null}
                  </button>
                ))}
              </div>
              {/* Pressing a sample disables every card and drops a pill into
                  the one that was pressed — both invisible to someone who
                  cannot see them, and the button they just activated goes
                  silent because it is now disabled. This says the same thing in
                  the channel that is left. */}
              <p className="sr-only" aria-live="polite">
                {busy === null ? "" : "Loading the sample dataset…"}
              </p>
            </>
          ) : null}
        </section>
      ) : (
        <>
          <h1>{project?.name ?? "Datasets"}</h1>
          {/* This line used to repeat the email and workspace. Both now live in
              the account menu, where they are reachable from every screen
              rather than only this one, so the space says something new. */}
          <p className="muted" style={{ marginTop: 0 }}>
            {datasets.length.toLocaleString()} dataset{datasets.length === 1 ? "" : "s"}
          </p>

          <div className="cards" style={{ marginTop: 18 }}>
            {datasets.map((dataset) => (
              <DatasetCard key={dataset.id} dataset={dataset} />
            ))}
          </div>

          <h2>Add another</h2>
          {workspace && project ? (
            <Upload
              workspaceId={workspace.id}
              projectId={project.id}
              onCommitted={(versionId) => router.push(`/versions/${versionId}`)}
            />
          ) : null}
        </>
      )}
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
 */
function DatasetCard({ dataset }: { dataset: DatasetSummary }) {
  const target = dataset.latest_version_id ? `/versions/${dataset.latest_version_id}` : null;

  const body = (
    <>
      <strong>{dataset.name}</strong>
      <span className="faint">
        {dataset.row_count === null
          ? "no version yet"
          : `${dataset.row_count.toLocaleString()} rows × ${dataset.column_count} columns`}
      </span>
    </>
  );

  if (!target) {
    return <div className="card dataset">{body}</div>;
  }
  return (
    <Link href={target} className="card dataset">
      {body}
    </Link>
  );
}
