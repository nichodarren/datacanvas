"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ProjectPicker } from "@/components/ProjectPicker";
import { Shell } from "@/components/Shell";
import { Upload } from "@/components/Upload";
import {
  ApiError,
  type DatasetSummary,
  type Me,
  type Project,
  type SampleDataset,
  api,
} from "@/lib/api";

const LAST_PROJECT = "datacanvas.project";

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
  const [error, setError] = useState<string | null>(null);

  const workspace = me?.workspaces[0] ?? null;

  const loadDatasets = useCallback(async (workspaceId: string, projectId: string) => {
    setDatasets(await api.datasets(workspaceId, projectId));
  }, []);

  const load = useCallback(async () => {
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
      const remembered = window.localStorage.getItem(LAST_PROJECT);
      const chosen = found.find((item) => item.id === remembered) ?? found[0] ?? null;
      setProject(chosen);
      if (chosen) await loadDatasets(firstWorkspace.id, chosen.id);

      setSamples(await api.samples());
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not load your projects.");
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
    window.localStorage.setItem(LAST_PROJECT, next.id);
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
      setError(cause instanceof Error ? cause.message : "Could not load that sample.");
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <Shell active="preview">
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  const picker = workspace ? (
    <ProjectPicker
      projects={projects}
      current={project}
      onSelect={(next) => void selectProject(next)}
      onCreate={createProject}
    />
  ) : undefined;

  const empty = datasets.length === 0;

  return (
    <Shell active="preview" headerExtras={picker} me={me}>
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
            {datasets.length} dataset{datasets.length === 1 ? "" : "s"}
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
 * The badge is the point. A card that only said "5,000 × 12" would be tidier
 * and would answer nothing — *which of these needs me?* is the question someone
 * returning to their own work actually has, and the count of unsure columns is
 * the only thing on this screen that answers it.
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
      <span className="row" style={{ gap: 6 }}>
        {dataset.version_no !== null ? <span className="pill">v{dataset.version_no}</span> : null}
        {dataset.schema_version_no !== null ? (
          <span className="pill">schema v{dataset.schema_version_no}</span>
        ) : null}
        {dataset.version_count > 1 ? (
          <span className="pill">{dataset.version_count} versions</span>
        ) : null}
        {dataset.columns_needing_attention > 0 ? (
          <span className="pill warn">
            {dataset.columns_needing_attention} to check
          </span>
        ) : null}
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
