"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PreviewGrid } from "@/components/PreviewGrid";
import { Shell } from "@/components/Shell";
import {
  ApiError,
  type DatasetVersion,
  type Me,
  type SchemaContract,
  api,
} from "@/lib/api";

/**
 * One DatasetVersion: its rows, read according to its schema contract.
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
 * The `v1 · schema v4` badge and the "Dataset version N" heading went the same
 * way. §14.2 put them in the header for P4 — *never be unsure which version you
 * are looking at* — and that requirement is now unmet in the UI on purpose,
 * recorded in the project notes rather than forgotten.
 *
 * **Nothing about the model changed.** A DatasetVersion is still immutable
 * (INV-2) and a correction still produces a new SchemaContract instead of
 * overwriting one (INV-3), both enforced by Postgres triggers. They have to be:
 * §9.4 builds every step fingerprint from `dataset_version_id` and
 * `schema_contract_id`, and INV-6 — same fingerprint, same result — is what
 * makes the cache safe to trust. Take versioning out of the model and a step
 * computed under `qty: integer` and one computed under `qty: categorical` share
 * a fingerprint and disagree about the answer.
 */
export default function VersionPage() {
  const router = useRouter();
  const params = useParams<{ versionId: string }>();
  const versionId = params.versionId;

  const [me, setMe] = useState<Me | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [version, setVersion] = useState<DatasetVersion | null>(null);
  const [contract, setContract] = useState<SchemaContract | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const identity = await api.me();
      setMe(identity);
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

  // The header used to carry `v1 · schema v4`. Removed from the UI at the
  // owner's direction; the versions themselves are untouched — DatasetVersion
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

  if (error || !version || !contract || !workspaceId) {
    // `me` is passed here too: a page that failed to load is exactly where
    // someone might want to sign out, and stranding them would be worse.
    return (
      <Shell me={me}>
        <div className="banner error" role="alert">
          {error ?? "Not available."}
        </div>
      </Shell>
    );
  }


  return (
    <Shell me={me}>
      {/* Stored size came out: it is a fact about our storage, not about the
          user's data, and nobody opening a dataset is asking it. */}
      <p className="muted">
        {version.row_count.toLocaleString()} rows · {version.column_count} columns
      </p>

      {!version.data_present ? (
        <div className="banner error">
          The rows for this version are no longer in storage. The schema is still here and can be
          corrected, but nothing can be read.
        </div>
      ) : null}

      {version.data_present ? (
        <PreviewGrid
          workspaceId={workspaceId}
          versionId={versionId}
          totalRows={version.row_count}
          contract={contract}
          onContractChanged={setContract}
        />
      ) : (
        <p className="faint">No rows to show.</p>
      )}
    </Shell>
  );
}
