"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PreviewGrid } from "@/components/PreviewGrid";
import { Shell } from "@/components/Shell";
import {
  ApiError,
  type DatasetVersion,
  type SchemaContract,
  api,
} from "@/lib/api";

/**
 * One DatasetVersion: its rows, and its interpretation.
 *
 * Two tabs, because §9.2 keeps two things apart that most tools conflate: the
 * data (immutable, INV-2) and the schema (versioned, INV-3). They change for
 * different reasons and at different rates, and the UI says so — the version
 * badge in the header carries both numbers, always (§14.2, P4).
 */
export default function VersionPage() {
  const router = useRouter();
  const params = useParams<{ versionId: string }>();
  const versionId = params.versionId;

  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [version, setVersion] = useState<DatasetVersion | null>(null);
  const [contract, setContract] = useState<SchemaContract | null>(null);
  const [tab, setTab] = useState<"preview" | "schema">("preview");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const identity = await api.me();
      // Every workspace is tried rather than assuming the first. A version id
      // belongs to exactly one workspace, and the API answers 404 for the
      // others — which is deliberate (§13.3.1 L2) and means "not yours" and
      // "not there" are indistinguishable to us as well as to an attacker.
      for (const candidate of identity.workspaces) {
        try {
          const found = await api.version(candidate.id, versionId);
          setWorkspaceId(candidate.id);
          setVersion(found);
          setContract(await api.schema(candidate.id, versionId));
          return;
        } catch (cause) {
          if (cause instanceof ApiError && cause.isMissing) continue;
          throw cause;
        }
      }
      setError("That dataset version does not exist, or is not yours.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.isUnauthenticated) {
        router.replace("/login");
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not load this version.");
    } finally {
      setLoading(false);
    }
  }, [versionId, router]);

  useEffect(() => {
    void load();
  }, [load]);

  const badge =
    version && contract ? (
      <span className="version-badge" title="Data version and schema version (§9.2)">
        v{version.version_no} · schema v{contract.version_no}
      </span>
    ) : undefined;

  if (loading) {
    return (
      <Shell active="preview">
        <p className="muted">Loading…</p>
      </Shell>
    );
  }

  if (error || !version || !contract || !workspaceId) {
    return (
      <Shell active="preview">
        <div className="banner error" role="alert">
          {error ?? "Not available."}
        </div>
      </Shell>
    );
  }

  const uncertain = contract.columns.filter(
    (column) => !column.overridden && column.detection_confidence < 0.8,
  );

  return (
    <Shell versionBadge={badge} active={tab}>
      <h1>Dataset version {version.version_no}</h1>
      <p className="muted">
        {version.row_count.toLocaleString()} rows · {version.column_count} columns ·{" "}
        {(version.byte_size / 1024 / 1024).toFixed(2)} MB stored
      </p>

      {!version.data_present ? (
        <div className="banner error">
          The rows for this version are no longer in storage. The schema is still here and can be
          corrected, but nothing can be read.
        </div>
      ) : null}

      {/* FR-C.6 / §14.3 step 4: the banner that sends a user to the columns
          worth a second look, rather than making them scan every header. */}
      {uncertain.length > 0 ? (
        <div className="banner">
          <strong>
            {uncertain.length} column{uncertain.length === 1 ? "" : "s"} worth checking.
          </strong>{" "}
          <span className="muted">
            {uncertain.map((column) => column.name).join(", ")} — the detector was not confident.
            Click a column type in the grid to correct it.
          </span>
        </div>
      ) : null}

      <div className="tabs">
        <button
          type="button"
          className={tab === "preview" ? "active" : ""}
          onClick={() => setTab("preview")}
        >
          Preview
        </button>
        <button
          type="button"
          className={tab === "schema" ? "active" : ""}
          onClick={() => setTab("schema")}
        >
          Schema
        </button>
      </div>

      {tab === "preview" ? (
        version.data_present ? (
          <PreviewGrid
            workspaceId={workspaceId}
            versionId={versionId}
            totalRows={version.row_count}
            contract={contract}
            onContractChanged={setContract}
          />
        ) : (
          <p className="faint">No rows to show.</p>
        )
      ) : (
        <SchemaTable contract={contract} />
      )}
    </Shell>
  );
}

/**
 * The schema as a list.
 *
 * The grid is where a type gets corrected, because that is where the problem is
 * visible (FR-D.4 rationale). This view exists for the other question — *what
 * did the machine decide, and why* — which is a reading task, not an editing
 * one, and is unreadable spread across thirty column headers.
 */
function SchemaTable({ contract }: { contract: SchemaContract }) {
  return (
    <>
      <p className="faint" style={{ fontSize: 12 }}>
        Schema version {contract.version_no}
        {contract.derived_from ? " · corrected from the previous version" : " · auto-detected"}.
        Corrections never overwrite: each one creates a new version (INV-3).
      </p>
      <table className="plain">
        <thead>
          <tr>
            <th>Column</th>
            <th>Type</th>
            <th>Confidence</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {[...contract.columns]
            .sort((a, b) => a.ordinal - b.ordinal)
            .map((column) => (
              <tr key={column.name}>
                <td className="mono">{column.name}</td>
                <td>
                  <span className="pill">{column.logical_type}</span>
                  {column.overridden ? <span className="pill ok"> set by a user</span> : null}
                </td>
                <td className={column.detection_confidence < 0.8 ? "pill warn" : "faint"}>
                  {column.detection_confidence.toFixed(2)}
                </td>
                <td className="muted">{column.detection_reason}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </>
  );
}
