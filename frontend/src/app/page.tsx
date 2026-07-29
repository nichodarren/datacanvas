"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Shell } from "@/components/Shell";
import { Upload } from "@/components/Upload";
import { ApiError, type Dataset, type Me, type Project, api } from "@/lib/api";

/**
 * Project home: what is here, and how to add something.
 *
 * §14.5 is firm that an empty canvas is the wrong empty state — people need to
 * see the product work before trusting it with their own data. The drop zone is
 * therefore the *first* thing, not a button hidden behind a menu. Bundled sample
 * datasets (FR-B.5) would go beside it; they are P1 and are not faked here.
 */
export default function HomePage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const workspace = me?.workspaces[0] ?? null;
  const project = projects[0] ?? null;

  const load = useCallback(async () => {
    try {
      const identity = await api.me();
      setMe(identity);
      const firstWorkspace = identity.workspaces[0];
      if (!firstWorkspace) return;
      const found = await api.projects(firstWorkspace.id);
      setProjects(found);
      const firstProject = found[0];
      if (firstProject) {
        setDatasets(await api.datasets(firstWorkspace.id, firstProject.id));
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not load your workspace.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Shell active="preview">
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  return (
    <Shell active="preview">
      <h1>{project?.name ?? "Your project"}</h1>
      <p className="muted">
        {me?.user.email}
        {workspace ? ` · ${workspace.name} · ${workspace.role}` : ""}
      </p>

      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}

      <h2>Add data</h2>
      {workspace && project ? (
        <Upload
          workspaceId={workspace.id}
          projectId={project.id}
          onCommitted={(versionId) => router.push(`/versions/${versionId}`)}
        />
      ) : (
        <p className="muted">No project yet.</p>
      )}

      <h2>Datasets</h2>
      {datasets.length === 0 ? (
        <p className="faint">
          Nothing uploaded yet. A dataset is immutable once committed — uploading the same file
          again creates a new version rather than replacing this one.
        </p>
      ) : (
        <table className="plain">
          <thead>
            <tr>
              <th>Name</th>
              <th>Added</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => (
              <tr key={dataset.id}>
                <td>{dataset.name}</td>
                <td className="faint">{new Date(dataset.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  );
}
