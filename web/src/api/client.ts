import type {
  Job,
  LogChunk,
  RunStatus,
  Session,
  StageContent,
  TopicDetail,
  TopicSummary,
} from "./types";

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

let tokenPromise: Promise<string> | null = null;

async function fetchToken(): Promise<string> {
  const resp = await fetch("/v1/session");
  if (!resp.ok) {
    throw new ApiRequestError(
      resp.status,
      "session_failed",
      `session bootstrap failed (HTTP ${resp.status})`,
    );
  }
  return ((await resp.json()) as Session).token;
}

function getToken(): Promise<string> {
  if (tokenPromise === null) {
    tokenPromise = fetchToken().catch((err) => {
      tokenPromise = null; // allow retry on the next call
      throw err;
    });
  }
  return tokenPromise;
}

export function resetSessionForTests(): void {
  tokenPromise = null;
}

export async function api<T>(path: string): Promise<T> {
  const token = await getToken();
  const resp = await fetch(path, { headers: { "X-EP-Token": token } });
  let body: unknown = {};
  try {
    body = await resp.json();
  } catch {
    // non-JSON body; fall through to the generic error below
  }
  if (!resp.ok) {
    const err = (body as { error?: { code: string; message: string } }).error;
    throw new ApiRequestError(
      resp.status,
      err?.code ?? "unknown",
      err?.message ?? `HTTP ${resp.status}`,
    );
  }
  return body as T;
}

export const getTopics = () => api<{ topics: TopicSummary[] }>("/v1/topics");
export const getTopic = (id: string) =>
  api<TopicDetail>(`/v1/topics/${encodeURIComponent(id)}`);
export const getRunStatus = (topicId: string) =>
  api<RunStatus>(`/v1/runs/${encodeURIComponent(topicId)}`);
export const getStageContent = (topicId: string, stage: string) =>
  api<StageContent>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}`,
  );
export const getJobs = (topicId?: string) =>
  api<{ jobs: Job[] }>(
    topicId ? `/v1/jobs?topic=${encodeURIComponent(topicId)}` : "/v1/jobs",
  );
export const getJobLog = (jobId: string, offset: number) =>
  api<LogChunk>(`/v1/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}`);
