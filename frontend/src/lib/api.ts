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
        if (event.lengthComputable && event.total > 0)
          onProgress(event.loaded / event.total);
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
    xhr.addEventListener("abort", () =>
      reject(new ApiError(0, "The upload was cancelled.")),
    );

    xhr.send(form);
  });
}

// ---------------------------------------------------------------- types ----

/**
 * Who is signed in.
 *
 * `workspaces: Workspace[]` was here until D-039, and every call below started
 * by reading `me.workspaces[0].id` out of it — a first element the client had
 * to pick and could pick wrongly. The account is the tenant now, so there is
 * nothing to pick: the session says which one, and no id travels in a URL.
 */
export interface Me {
  user: { id: string; email: string; created_at: string };
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

/**
 * One dataset, and the facts about the bytes it is.
 *
 * Everything below `name` lived on a separate `DatasetDataset` until D-043. The
 * dataset page fetched that and had nothing on it saying which dataset it
 * belonged to, which is why `dataset_name` had to be added back to it — a field
 * that existed only because the two halves of one thing arrived as two things.
 */
export interface Dataset {
  id: string;
  owner_id: string;
  name: string;
  content_hash: string;
  row_count: number;
  column_count: number;
  byte_size: number;
  created_at: string;
  /** Whether the bytes are really in the store. Reaching this means the caller
   * passed through `data_access.open()`. */
  data_present: boolean;
}

/**
 * A dataset as the home screen shows it: enough to choose one without opening
 * any of them.
 *
 * `columns_needing_attention` used to be here and came out with the grid signal
 * it counted. `version_count`, `latest_version_id` and `version_no` went with
 * D-043: the first was always 1, and the other two were how a card said which
 * of a dataset's versions to open — a question with one answer for every
 * dataset that has ever existed here.
 */
export interface DatasetSummary {
  id: string;
  name: string;
  created_at: string;
  row_count: number;
  column_count: number;
  schema_version_no: number | null;
}

export interface SampleDataset {
  key: string;
  name: string;
  description: string;
}

export interface ColumnSpec {
  name: string;
  ordinal: number;
  physical_type: string;
  logical_type: string;
  null_markers: string[];
  detection_confidence: number;
  detection_reason: string;
  overridden: boolean;
}

/** A versioned interpretation of a Dataset (FR-C.3, INV-3).

 * The *schema* is still versioned after D-043, and the asymmetry is deliberate:
 * data is a fact and does not change, while its interpretation is a judgement
 * somebody can be wrong about and later correct.
 */
export interface SchemaContract {
  id: string;
  dataset_id: string;
  version_no: number;
  columns: ColumnSpec[];
  created_at: string;
  derived_from: string | null;
}

export interface Committed {
  dataset: Dataset;
  schema_contract: SchemaContract;
  original_filename: string;
}

/** One tool that ran during a turn, and the id its figures are cited by. */
export interface Ran {
  ref: string;
  tool: string;
  args: Record<string, unknown>;
  /**
   * How to draw it, without knowing the tool's name (§11.2, §11.4.1).
   *
   * Six values and no more: `table`, `report`, `matrix`, `chart_spec`,
   * `column_cards`, `stat_panel`. A seventh needs a component before it needs
   * a name — which is the rule that keeps the vocabulary from becoming a list
   * of things nothing renders.
   */
  output_kind: string;
}

/**
 * One computation's result, fetched on its own (§11.4.1).
 *
 * **Separately from the answer, and the payload is why.** A report is under a
 * kilobyte; a scatter plot at the 5,000-row ceiling is about a megabyte.
 * Inlined, a six-step turn could carry several megabytes and the sentence
 * would wait for all of it. Fetched on its own, the answer arrives first and
 * the cards follow.
 */
export interface Artifact {
  ref: string;
  tool: string;
  tool_version: number;
  output_kind: string;
  result: Record<string, unknown>;
}

/** Something §12.5 refused to let pass silently. */
export interface Complaint {
  kind: string;
  detail: string;
}

/**
 * One copilot turn (§12.3).
 *
 * **Branch on `grounded`, not on `narrative`.** A turn can carry confident
 * prose and still have failed its citation check — that is exactly what a
 * broken `[ref:]` or an unsupported figure means — so *has text* and *may be
 * believed* are two questions and this answers both.
 */
export interface Turn {
  narrative: string | null;
  grounded: boolean;
  steps: Ran[];
  complaints: Complaint[];
  stopped: string | null;
  rejections: string[];
  categories: string[];
  tokens: number;
  privacy_mode: string;
  /**
   * Which rung answered and which model it ran.
   *
   * Two fields because they answer different questions: the **rung**
   * (`gemini#2`) names an account and §12.8 bills per one; the **model** is
   * what shaped the answer. Empty means it was not recorded, which is true of
   * every turn stored before this existed.
   */
  provider: string;
  model: string;
}

/**
 * One entry in the conversation log (§12.4).
 *
 * **Carries its own `steps`**, and that is what makes the log navigable rather
 * than nostalgic: a `ref` is a `computation_id`, so an entry knows which cards
 * on the canvas it produced. A list of past questions with nothing attached
 * would be a list nobody could act on.
 *
 * Never sent back to a model. §12.4 stores the transcript to be **read**, and
 * what a planner receives is structured state assembled fresh each turn — the
 * three reasons are token growth, poisoned determinism, and a falling signal
 * ratio.
 */
export interface TurnSummary {
  id: string;
  asked_at: string;
  question: string;
  narrative: string | null;
  grounded: boolean;
  stopped: string | null;
  steps: Ran[];
  complaints: Complaint[];
  /**
   * Which rung answered and which model it ran.
   *
   * Two fields because they answer different questions: the **rung**
   * (`gemini#2`) names an account and §12.8 bills per one; the **model** is
   * what shaped the answer. Empty means it was not recorded, which is true of
   * every turn stored before this existed.
   */
  provider: string;
  model: string;
}

export interface History {
  turns: TurnSummary[];
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

/** One histogram bucket, carrying the edges it was cut at (§11.8.6c). */
export interface Bin {
  lower: number;
  upper: number;
  count: number;
}

export interface TopValue {
  value: string;
  count: number;
}

/**
 * Which of the nine card shapes a column gets (§11.8.3).
 *
 * Five come from the logical type. The other four override it, because on those
 * the normal shape is *misleading* rather than merely empty — a histogram with
 * one bar for a constant column, a median for a column of serial numbers.
 *
 * Decided by the server and sent, never re-derived here. The ordering rule that
 * produces it lives in one place on purpose: two places that must agree
 * eventually will not.
 */
export type ProfileKind =
  | "numerical"
  | "categorical"
  | "text"
  | "date"
  | "boolean"
  | "empty"
  | "constant"
  | "unsupported";

/**
 * One card's worth of §11.8.
 *
 * Everything after `null_share` is optional because `kind` decides which fields
 * mean anything. A numerical column has no `top`; a categorical one has no
 * `median`.
 */
export interface ColumnProfile {
  name: string;
  ordinal: number;
  physical_type: string;
  logical_type: string;
  kind: ProfileKind;
  total: number;
  present: number;
  distinct: number;
  null_share: number;
  conforming: number | null;

  minimum: number | null;
  median: number | null;
  maximum: number | null;
  earliest: string | null;
  latest: string | null;
  bins: Bin[];
  top: TopValue[];
  others_count: number;
  others_distinct: number;
  length_min: number | null;
  length_median: number | null;
  length_max: number | null;
  samples: string[];
  value: string | null;
}

/**
 * The Profile tab, and the receipt for every number on it.
 *
 * `computation_id` is not decoration. INV-5 says every number displayed comes
 * from a Computation that can be referenced, and this is the reference — which
 * is why this tab waited for the `computation` table rather than shipping as a
 * plain read.
 */
export interface DatasetProfile {
  computation_id: string;
  fingerprint: string;
  tool_name: string;
  tool_version: number;
  computed_at: string;
  duration_ms: number;
  row_count: number;
  columns: ColumnProfile[];
}

/**
 * One column, in depth (§11.7) — what the panel behind a profile card shows.
 *
 * Exactly one of the five shape blocks is filled, chosen by `logical_type`, and
 * all five are `null` for a column with no values at all. The server decides
 * which; re-deriving it here from the type would put §11.7.3's per-type table in
 * a second place, and two places that must agree eventually do not.
 *
 * `narrative` is written by a deterministic template on the server (§11.7.6c),
 * never by a model. The structure of a profile is always the same, so a template
 * is correct, free and instant — and the sentence inherits the same
 * `computation_id` as the numbers it reads out, which is how it satisfies P3
 * without a model being involved.
 */
export interface ColumnDetail {
  computation_id: string;
  fingerprint: string;
  tool_name: string;
  tool_version: number;
  computed_at: string;
  duration_ms: number;

  column: string;
  logical_type: string;
  physical_type: string;
  narrative: string;
  completeness: {
    total: number;
    present: number;
    nulls: number;
    empty: number;
    null_share: number;
    /** Numeric columns only — a count of zeros on a text column is a number
     *  about something that is not a number. */
    zeros: number | null;
    negatives: number | null;
  };
  /**
   * Completeness in **file order**, bucketed — missingno's matrix for one
   * column. The question no count answers: *where* the gaps are. A column that
   * is 7% null because the last eighty rows were never filled in is not the
   * same column as one that is 7% null at random, and `null 7.0%` says the
   * same thing about both.
   */
  presence: {
    /** File rows per slot. 1 when the column is short enough. */
    rows_per_slot: number;
    /** In file order; the last slot may be short. */
    slots: { rows: number; present: number }[];
  };
  cardinality: { distinct: number; is_unique: boolean };
  numeric: {
    conforming: number;
    mean: number | null;
    median: number | null;
    mode: number | null;
    std: number | null;
    variance: number | null;
    minimum: number | null;
    maximum: number | null;
    value_range: number | null;
    iqr: number | null;
    skewness: number | null;
    /** Excess kurtosis, Fisher: a normal distribution scores 0, not 3. The
     *  panel says which convention beside the figure. */
    kurtosis: number | null;
    quantiles: { q: number; value: number }[];
    outlier_low: number | null;
    outlier_high: number | null;
    outlier_count: number;
    /** Where each whisker stops: the most extreme value still inside the
     *  fence. Not the fence — a whisker drawn to the fence claims data reaches
     *  a place no value does. */
    whisker_low: number | null;
    whisker_high: number | null;
    smallest: number[];
    largest: number[];
    bins: Bin[];
    /** The quantile function at 101 points, plotted as the ECDF. */
    ecdf: { p: number; value: number }[];
    /** Every distinct value with its count, in value order (D-074). Unbinned,
     *  which is the point: twenty bars over `age` look smooth whether the
     *  column holds every age or only the ones ending in 0 and 5. */
    rug: { value: number; count: number }[];
    /** 1 when the rug is every distinct value; higher when it is one tick in
     *  `rug_stride` because the column carried more than the cap. */
    rug_stride: number;
  } | null;
  categorical: {
    top: { value: string; count: number }[];
    others_count: number;
    others_distinct: number;
    top5_share: number;
    rare_categories: number;
    /**
     * `(rank, cumulative share)` over **every** category, sampled.
     *
     * The honest form of a Pareto chart for a column whose table shows ten of
     * two hundred: bars plus a cumulative line over the top ten would draw the
     * head and say nothing about the tail, while looking exactly like a chart
     * that had.
     */
    concentration: { rank: number; share: number }[];
  } | null;
  text: {
    length_min: number | null;
    length_median: number | null;
    length_mean: number | null;
    length_max: number | null;
    words_min: number | null;
    words_median: number | null;
    words_mean: number | null;
    words_max: number | null;
    length_bins: Bin[];
    word_bins: Bin[];

    /** What the characters *are*, which is what sorts a text column into the
     *  three things it is ever actually one of: a mistyped code, a label, or
     *  prose. `postal_code` reading 94.8% numeric is how 62 rows holding the
     *  word `unknown` give themselves away in a column reported 0% null. */
    share_numeric: number;
    share_dateish: number;
    share_with_digit: number;
    share_padded: number;
    share_upper: number;
    share_punct: number;
    share_url: number;
    share_non_ascii: number;

    top: TopValue[];
    others_count: number;
    others_distinct: number;

    /** Tokens split on non-alphanumerics and lowercased, and nothing else
     *  (D-071): no stopword list, because a stopword list is a language. */
    tokens_total: number;
    tokens_distinct: number;
    top_words: TopValue[];
    top_pairs: TopValue[];
    top_triples: TopValue[];
    /** The same terms as `top_words`, sixty deep instead of twelve, for the
     *  cloud (D-073). One query serves both, so they cannot disagree. */
    cloud: TopValue[];
    vocabulary: { rank: number; share: number }[];

    samples: string[];
  } | null;
  date: {
    /** Values that actually parse as a moment. Everything else here is
     *  computed from these and from no others, which is why the panel leads
     *  with it: a column forced to `date` whose values are `07/03/2024` draws
     *  a real range built from whatever fraction happened to be ISO. */
    conforming: number;
    earliest: string | null;
    latest: string | null;
    span_days: number | null;
    granularity: string;
    /** Days holding at least one value, against the days the span covers. */
    days_seen: number;
    days_in_span: number;
    /** Calendar buckets, **zero-filled**: a month with no rows is a gap, and a
     *  series that omits it closes the gap up. `by_day` is empty for spans too
     *  long to draw a bar per day. */
    by_year: { key: string; count: number }[];
    by_month: { key: string; count: number }[];
    by_day: { key: string; count: number }[];
    /** Cyclic, folded across the span, always the whole domain. `by_hour` is
     *  empty unless the column carries a time. */
    by_weekday: { key: string; count: number }[];
    by_month_of_year: { key: string; count: number }[];
    by_hour: { key: string; count: number }[];
  } | null;
  boolean: { true_count: number; false_count: number; other_count: number } | null;
}

/**
 * The five types a column can be corrected to (§9.2, FR-C.2).
 *
 * `unsupported` is deliberately not here. It is what the system says about a
 * column whose physical type is not scalar — a struct, a list — and offering it
 * in a menu would let somebody declare a readable column unreadable.
 *
 * `test_api_schemas.py` guards the backend half of this list.
 */
export const LOGICAL_TYPES = [
  "numerical",
  "categorical",
  "text",
  "date",
  "boolean",
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
    request<{ revoked_sessions: number }>("/auth/logout-all", {
      method: "POST",
    }),

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

  /**
   * Every dataset the account owns.
   *
   * This took two ids and returned one project's worth. The home page had to
   * fetch the project list first, then fan out across it and flatten the
   * result, because a screen that showed one project's datasets while offering
   * no way to change project would have hidden the rest.
   *
   * One call now, and the server does the filtering it always should have: the
   * `WHERE owner_id = ...` is the only thing standing between a signed-in
   * caller and every dataset in the database, which is why
   * `test_tenant_isolation.py` checks this route specifically.
   */
  datasets: () => request<DatasetSummary[]>("/datasets"),

  samples: () => request<SampleDataset[]>("/samples"),

  loadSample: (key: string) =>
    json<Committed>("/datasets/samples", "POST", { key }),

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
    return request<IngestPreview>("/uploads/preview", {
      method: "POST",
      body: form,
    });
  },

  /**
   * The only call that can take minutes, and so the only one that reports
   * progress (NFR-UX.2). See `upload` for why it is not `fetch`, and for what
   * `onProgress` does *not* cover.
   */
  createDataset: (
    file: File,
    options: {
      name?: string;
      dialect?: Dialect | null;
      onProgress?: (fraction: number) => void;
    },
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (options.name) form.append("name", options.name);
    if (options.dialect) {
      form.append("delimiter", options.dialect.delimiter);
      form.append("encoding", options.dialect.encoding);
      form.append("has_header", String(options.dialect.has_header));
    }
    return upload<Committed>("/datasets", form, options.onProgress);
  },

  dataset: (datasetId: string) => request<Dataset>(`/datasets/${datasetId}`),

  schema: (datasetId: string) =>
    request<SchemaContract>(`/datasets/${datasetId}/schema`),

  /**
   * Every column, profiled (§11.8).
   *
   * One call for the whole tab rather than one per column: the server runs one
   * tool, over one pass, under one fingerprint — so the second time this is
   * asked it is a cache hit and the numbers are guaranteed identical (INV-6).
   */
  profile: (datasetId: string) =>
    request<DatasetProfile>(`/datasets/${datasetId}/profile`),
  /** One column, deeply. Two columns are two fingerprints and two cache
   *  entries, which is right — they are two questions. */
  /** One copilot turn (§12.3). Slow by nature — a turn is up to seven model
   *  calls — so callers should show that it is working. */
  ask: (datasetId: string, question: string) =>
    request<Turn>(`/datasets/${datasetId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),

  /**
   * Every question asked of this dataset, newest first (§12.4).
   *
   * Read on entering the full-screen analysis page, so the canvas and its
   * index arrive together: the log is what a reader uses to find a card they
   * made twenty minutes ago.
   */
  history: (datasetId: string) =>
    request<History>(`/datasets/${datasetId}/history`),

  /**
   * Forget one question (NFR-PRIV.3).
   *
   * The computations it named are **not** deleted: a `Computation` is
   * shared by every turn that asked the same thing of the same data, so
   * removing one because a log entry was tidied away would empty a cache
   * entry another turn still cites. What goes is the sentence a person
   * typed, which is the half §13.7.1 keeps only a hash of.
   */
  forget: (datasetId: string, turnId: string) =>
    request<void>(`/datasets/${datasetId}/history/${turnId}`, { method: "DELETE" }),

  /**
   * One computation's result, for the canvas to draw.
   *
   * Cached by the browser for the life of the page rather than re-fetched per
   * render: a Computation is immutable by construction (INV-6), so the second
   * request could only ever return the first answer.
   */
  artifact: (datasetId: string, ref: string) =>
    request<Artifact>(`/datasets/${datasetId}/computations/${ref}`),

  columnProfile: (datasetId: string, column: string) =>
    request<ColumnDetail>(
      `/datasets/${datasetId}/columns/${encodeURIComponent(column)}/profile`,
    ),

  correctSchema: (
    datasetId: string,
    columns: { name: string; logical_type?: string }[],
  ) =>
    json<SchemaContract>(`/datasets/${datasetId}/schema`, "POST", {
      columns,
    }),

  rows: (datasetId: string, offset: number, limit: number) =>
    request<RowPage>(
      `/datasets/${datasetId}/rows?offset=${offset}&limit=${limit}`,
    ),

  /**
   * FR-B.6. The route has existed since Phase 2 and nothing called it.
   *
   * It is not a row delete: the service removes the Parquet, the source file
   * kept for re-parse, and the rows, and it writes an audit event. NFR-PRIV.3
   * promises the bytes are actually gone rather than merely unreachable, and
   * this is the only path that keeps that promise.
   */
  deleteDataset: (datasetId: string) =>
    request<void>(`/datasets/${datasetId}`, { method: "DELETE" }),
};
