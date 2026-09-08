"use client";

import { use, useEffect, useState } from "react";

import { AnalysisWorkspace } from "@/components/AnalysisWorkspace";
import { LoadFailure } from "@/components/LoadFailure";
import { api, describeFailure, type Dataset } from "@/lib/api";

/**
 * Full-screen analysis, at its own URL.
 *
 * **A route rather than a mode toggle**, and the reasons are four:
 *
 * - the tab keeps working exactly as it does, so nothing regresses;
 * - the URL is bookmarkable and survives a reload, which a `useState` flag
 *   would not;
 * - the browser's back button does the obvious thing;
 * - the two layouts are genuinely different components, and one component
 *   holding two layouts is how a component starts rotting.
 *
 * It fetches only the dataset — its name for the bar, and the 404 that proves
 * the reader may be here at all. The conversation log is the workspace's own
 * business, because it is the thing that changes while the page is open.
 */
export default function AnalysisPage({
  params,
}: {
  params: Promise<{ datasetId: string }>;
}) {
  const { datasetId } = use(params);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .dataset(datasetId)
      .then((found) => {
        if (alive) setDataset(found);
      })
      .catch((cause) => {
        if (alive) setError(describeFailure(cause));
      });
    return () => {
      alive = false;
    };
  }, [datasetId]);

  if (error !== null) {
    return <LoadFailure message={error} onRetry={() => location.reload()} />;
  }
  if (dataset === null) {
    return <p className="muted workspace-loading">Loading…</p>;
  }

  return <AnalysisWorkspace datasetId={datasetId} datasetName={dataset.name} />;
}
