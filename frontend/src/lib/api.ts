/**
 * The one place that talks to the backend.
 *
 * Everything goes through `/api/*`, which Next rewrites to the API — see
 * `next.config.mjs` for why that is required rather than convenient.
 *
 * `credentials: "include"` is set even though the request is same-origin. It
 * costs nothing and it stops the whole app from silently becoming anonymous the
 * day someone points this at a different origin.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 404 is what the API answers for "not yours" as well as "not there" (§13.3.1 L2). */
  get isMissing(): boolean {
    return this.status === 404;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    // The API's failures are written to be read by a person (P6, NFR-REL.2),
    // so the detail is surfaced rather than replaced with a generic message.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // A non-JSON error body is not worth a second failure.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------- types ----

export interface Workspace {
  id: string;
  name: string;
  is_personal: boolean;
  created_at: string;
  role: string;
}

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface Me {
  user: { id: string; email: string; created_at: string };
  workspaces: Workspace[];
}

export interface Dialect {
  delimiter: string;
  encoding: string;
  has_header: boolean;
  confidence: number;
}

export interface IngestPreview {
  format: string;
  dialect: Dialect | null;
  columns: string[];
  sample_rows: string[][];
  partial: boolean;
  warnings: string[];
}

export interface Dataset {
  id: string;
  project_id: string;
  name: string;
  created_at: string;
}

/**
 * A dataset as the home screen shows it.
 *
 * Deliberately more than a name. `columns_needing_attention` is what turns a
 * list of uploads into a place to start — it answers "which of these wants me?"
 * without opening any of them, and it is the same threshold the grid header
 * uses so the two cannot disagree.
 */
export interface DatasetSummary {
  id: string;
  name: string;
  created_at: string;
  version_count: number;
  latest_version_id: string | null;
  version_no: number | null;
  row_count: number | null;
  column_count: number | null;
  schema_version_no: number | null;
  columns_needing_attention: number;
}

export interface SampleDataset {
  key: string;
  name: string;
  description: string;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version_no: number;
  content_hash: string;
  row_count: number;
  column_count: number;
  byte_size: number;
  ingested_at: string;
  data_present: boolean;
}

export interface ColumnSpec {
  name: string;
  ordinal: number;
  physical_type: string;
  logical_type: string;
  role: string | null;
  null_markers: string[];
  detection_confidence: number;
  detection_reason: string;
  overridden: boolean;
}

export interface SchemaContract {
  id: string;
  dataset_version_id: string;
  version_no: number;
  columns: ColumnSpec[];
  created_at: string;
  derived_from: string | null;
}

export interface DatasetWithVersion {
  dataset: Dataset;
  version: DatasetVersion;
  schema_contract: SchemaContract;
  original_filename: string;
}

export interface RowPage {
  columns: string[];
  rows: (string | null)[][];
  offset: number;
  limit: number;
  total_rows: number;
}

/** §9.2's closed vocabulary, mirrored. `test_api_schemas.py` guards the backend half. */
export const LOGICAL_TYPES = [
  "integer",
  "decimal",
  "boolean",
  "categorical",
  "text",
  "date",
  "datetime",
  "duration",
  "unsupported",
] as const;

// ----------------------------------------------------------------- calls ----

export const api = {
  me: () => request<Me>("/auth/me"),

  login: (email: string, password: string) =>
    json<{ user: Me["user"] }>("/auth/login", "POST", { email, password }),

  register: (email: string, password: string) =>
    json<{ user: Me["user"] }>("/auth/register", "POST", { email, password }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  /** FR-A.2, the "all devices" half. Revokes this session too. */
  logoutAll: () =>
    request<{ revoked_sessions: number }>("/auth/logout-all", { method: "POST" }),

  projects: (workspaceId: string) =>
    request<Project[]>(`/workspaces/${workspaceId}/projects`),

  createProject: (workspaceId: string, name: string) =>
    json<Project>(`/workspaces/${workspaceId}/projects`, "POST", { name }),

  datasets: (workspaceId: string, projectId: string) =>
    request<DatasetSummary[]>(`/workspaces/${workspaceId}/projects/${projectId}/datasets`),

  samples: () => request<SampleDataset[]>("/samples"),

  loadSample: (workspaceId: string, projectId: string, key: string) =>
    json<DatasetWithVersion>(
      `/workspaces/${workspaceId}/projects/${projectId}/datasets/samples`,
      "POST",
      { key },
    ),

  /**
   * D-025: only the first megabyte is sent, and the server keeps none of it.
   *
   * Slicing here rather than server-side is the point — the user is confirming
   * how the file will be read, and that is legible from its first rows. Sending
   * 500 MB to answer "is the delimiter a comma?" would be the staging area
   * D-025 rejected, wearing a different hat.
   */
  previewUpload: (file: File) => {
    const PREVIEW_BYTES = 1024 * 1024;
    const head = file.slice(0, PREVIEW_BYTES);
    const form = new FormData();
    form.append("file", new File([head], file.name, { type: file.type }));
    return request<IngestPreview>("/uploads/preview", { method: "POST", body: form });
  },

  createDataset: (
    workspaceId: string,
    projectId: string,
    file: File,
    options: { name?: string; dialect?: Dialect | null },
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (options.name) form.append("name", options.name);
    if (options.dialect) {
      form.append("delimiter", options.dialect.delimiter);
      form.append("encoding", options.dialect.encoding);
      form.append("has_header", String(options.dialect.has_header));
    }
    return request<DatasetWithVersion>(
      `/workspaces/${workspaceId}/projects/${projectId}/datasets`,
      { method: "POST", body: form },
    );
  },

  version: (workspaceId: string, versionId: string) =>
    request<DatasetVersion>(`/workspaces/${workspaceId}/dataset-versions/${versionId}`),

  schema: (workspaceId: string, versionId: string) =>
    request<SchemaContract>(`/workspaces/${workspaceId}/dataset-versions/${versionId}/schema`),

  correctSchema: (
    workspaceId: string,
    versionId: string,
    columns: { name: string; logical_type?: string; role?: string }[],
  ) =>
    json<SchemaContract>(
      `/workspaces/${workspaceId}/dataset-versions/${versionId}/schema`,
      "POST",
      { columns },
    ),

  rows: (workspaceId: string, versionId: string, offset: number, limit: number) =>
    request<RowPage>(
      `/workspaces/${workspaceId}/dataset-versions/${versionId}/rows` +
        `?offset=${offset}&limit=${limit}`,
    ),
};
