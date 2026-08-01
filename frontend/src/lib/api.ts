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

/**
 * A failure, in words a person can act on.
 *
 * `request` surfaces the API's own `detail` because those are written to be read
 * (P6, NFR-REL.2). Two cases have no such detail and fell through to the raw
 * status line, which is how a screen came to greet someone with
 * `500 Internal Server Error` and nothing else: a server error whose body is not
 * our JSON, and a request that never arrived at all.
 *
 * §14.5 asks error states to be actionable. A status code is not an action, and
 * to most people it is not even information — it is a number that suggests they
 * broke something.
 */
export function describeFailure(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 0) {
      return "Could not reach the server. Check your connection, then try again.";
    }
    if (cause.status >= 500) {
      return "The server could not answer that. This is a fault on our side, not something you did.";
    }
    return cause.message;
  }
  return "Something went wrong. Trying again may be enough.";
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

/**
 * A POST whose *upload* can be watched (D-034).
 *
 * The one place this file does not use `fetch`, and the reason is a hard limit
 * rather than a preference: `fetch` cannot report upload progress. A request
 * body can only be observed by streaming it, which needs HTTP/2 and duplex
 * support that is not reliably there, so `XMLHttpRequest` — which has had
 * `upload.onprogress` for fifteen years — is the honest tool.
 *
 * It matters because Gate 2 measured a 480 MB upload at **28 seconds** end to
 * end, against an NFR-UX.2 threshold of 500 ms for showing progress at all. The
 * screen answered that with a button that said `Uploading…` and never changed.
 *
 * `fraction` covers **bytes leaving the browser and nothing else.** The server
 * still has to normalise the file to Parquet and infer types across every row
 * of it (FR-B.3), and that work is invisible from here. Callers are expected to
 * say so rather than park a bar at 99% — an indicator that asserts a state it
 * cannot observe is the class of lie this project keeps removing.
 */
function upload<T>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    // The `credentials: "include"` of the fetch path, by its other name.
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");

    if (onProgress) {
      xhr.upload.addEventListener("progress", (event) => {
        // Absent for a body of unknown length. Reporting 0% forever would be
        // worse than reporting nothing, so nothing is what is reported.
        if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
      });
    }

    xhr.addEventListener("load", () => {
      const raw = xhr.responseText;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve((xhr.status === 204 ? undefined : JSON.parse(raw)) as T);
        return;
      }
      // Mirrors `request`: the API writes its failures to be read by a person
      // (P6, NFR-REL.2), so the detail is surfaced rather than replaced.
      let detail = `${xhr.status} ${xhr.statusText}`;
      try {
        const body = JSON.parse(raw) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        // A non-JSON error body is not worth a second failure.
      }
      reject(new ApiError(xhr.status, detail));
    });

    // Fires for a dropped connection or a refused one — cases where there is no
    // status at all. 0 is not a real HTTP status and is never treated as one.
    xhr.addEventListener("error", () =>
      reject(new ApiError(0, "The upload could not reach the server.")),
    );
    xhr.addEventListener("abort", () => reject(new ApiError(0, "The upload was cancelled.")));

    xhr.send(form);
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
 * A dataset as the home screen shows it: enough to choose one without opening
 * any of them.
 *
 * `columns_needing_attention` used to be here and came out with the grid signal
 * it counted. `schema_version_no` is currently unread — it costs nothing to
 * send, and a version-history view is the next thing that will want it.
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
}

export interface SampleDataset {
  key: string;
  name: string;
  description: string;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  /**
   * Which dataset this version belongs to.
   *
   * The version page never said. The "Dataset version N" heading was removed
   * with the version badge (§14.2), and the dataset's own name went with it as
   * an unintended side effect — leaving a page that is a grid and a brand link.
   *
   * Not the version badge returning: P4 stays unmet in the UI until Phase 3.
   */
  dataset_name: string;
  /**
   * The project the dataset belongs to (FR-A.4), and the reason the trail can
   * exist at all.
   *
   * Without it the version page could not name its project — and the brand link
   * went to `/`, which opens whichever project the browser last remembered. A
   * version reached from a bookmark could therefore hand the user a *different*
   * project on the way back, silently. No amount of client cleverness fixes
   * that; the fact had to come from the server. See `Trail`.
   */
  project_id: string;
  project_name: string;
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

/** One live session as its owner sees it. Never carries a token (§13.2). */
export interface UserSession {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip_created: string | null;
  user_agent: string | null;
  is_current: boolean;
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

  /** OWASP Session Management: a user must be able to inspect their sessions. */
  sessions: () => request<UserSession[]>("/auth/sessions"),

  revokeSession: (sessionId: string) =>
    request<void>(`/auth/sessions/${sessionId}`, { method: "DELETE" }),

  /** Returns how many *other* sessions the change ended. */
  changePassword: (currentPassword: string, newPassword: string) =>
    json<{ revoked_sessions: number }>("/auth/password", "POST", {
      current_password: currentPassword,
      new_password: newPassword,
    }),

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

  /**
   * The only call that can take minutes, and so the only one that reports
   * progress (NFR-UX.2). See `upload` for why it is not `fetch`, and for what
   * `onProgress` does *not* cover.
   */
  createDataset: (
    workspaceId: string,
    projectId: string,
    file: File,
    options: { name?: string; dialect?: Dialect | null; onProgress?: (fraction: number) => void },
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (options.name) form.append("name", options.name);
    if (options.dialect) {
      form.append("delimiter", options.dialect.delimiter);
      form.append("encoding", options.dialect.encoding);
      form.append("has_header", String(options.dialect.has_header));
    }
    return upload<DatasetWithVersion>(
      `/workspaces/${workspaceId}/projects/${projectId}/datasets`,
      form,
      options.onProgress,
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
