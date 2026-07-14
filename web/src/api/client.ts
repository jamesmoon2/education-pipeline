import type {
  AdvanceResult,
  ApproveResult,
  AttachProfileResult,
  CatalogProvider,
  EditResponseResult,
  ExportFormat,
  ExportResult,
  FinalizeResult,
  ImportProfileResult,
  ImportTopicResult,
  Job,
  GuidePreviewResult,
  LogChunk,
  PlanPayload,
  PreviewResult,
  ProviderAvailability,
  ResponseResult,
  RunStatus,
  Session,
  StageContent,
  StageOverride,
  TopicDetail,
  TopicSummary,
  ValidateResult,
  ValidationResult,
  WaiverResult,
  WaiversResult,
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

async function request<T>(
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: string } = {},
): Promise<T> {
  const token = await getToken();
  const resp = await fetch(path, {
    ...init,
    headers: { ...(init.headers ?? {}), "X-EP-Token": token },
  });
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

export async function api<T>(path: string): Promise<T> {
  return request<T>(path);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, {
    method: "DELETE",
  });
}

export async function download(path: string, filename: string): Promise<void> {
  const token = await getToken();
  const resp = await fetch(path, { headers: { "X-EP-Token": token } });
  if (!resp.ok) {
    let body: unknown = {};
    try {
      body = await resp.json();
    } catch {
      // non-JSON body; fall through to the generic error below
    }
    const err = (body as { error?: { code: string; message: string } }).error;
    throw new ApiRequestError(
      resp.status,
      err?.code ?? "unknown",
      err?.message ?? `HTTP ${resp.status}`,
    );
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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

export const getProfiles = () => api<{ profiles: string[] }>("/v1/profiles");

export const postAdvance = (topicId: string) =>
  apiPost<AdvanceResult>(`/v1/runs/${encodeURIComponent(topicId)}/advance`, {});
export const postResponse = (topicId: string, stage: string, text: string, force = false) =>
  apiPost<ResponseResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/response`,
    { text, force },
  );
export const putResponse = (
  topicId: string,
  stage: string,
  text: string,
  baseSha256: string,
) =>
  apiPut<EditResponseResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/response`,
    { text, base_sha256: baseSha256 },
  );
export const postPreview = (text: string) =>
  apiPost<PreviewResult>("/v1/preview", { text });
export const postGuidePreview = (text: string) =>
  apiPost<GuidePreviewResult>("/v1/guide-preview", {
    text,
    include_validation: true,
  });
export const postValidate = (topicId: string, phase: "draft" | "final") =>
  apiPost<ValidateResult>(`/v1/runs/${encodeURIComponent(topicId)}/validate`, { phase });
export const getValidation = (topicId: string, phase: "draft" | "final") =>
  api<ValidationResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/validation/${phase}`,
  );
export const postWaiver = (
  topicId: string,
  phase: "draft" | "final",
  findingId: string,
  guideSha256: string,
  reason: string,
) =>
  apiPost<WaiverResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/validation/${phase}/waivers`,
    { finding_id: findingId, guide_sha256: guideSha256, reason },
  );
export const deleteWaiver = (
  topicId: string,
  phase: "draft" | "final",
  findingId: string,
) =>
  apiDelete<WaiverResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/validation/${phase}/waivers/${encodeURIComponent(findingId)}`,
  );
export const getWaivers = (topicId: string, phase: "draft" | "final") =>
  api<WaiversResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/validation/${phase}/waivers`,
  );
export const postApprove = (topicId: string, stage: string, overwrite = false) =>
  apiPost<ApproveResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/approve`,
    { overwrite },
  );
export const postFinalize = (topicId: string, overwrite = false) =>
  apiPost<FinalizeResult>(`/v1/runs/${encodeURIComponent(topicId)}/finalize`, { overwrite });
export const postExport = (topicId: string, format: ExportFormat, overwrite = false) =>
  apiPost<ExportResult>(`/v1/runs/${encodeURIComponent(topicId)}/export`, {
    format,
    overwrite,
  });
export const importTopic = (toml: string, overwrite = false) =>
  apiPost<ImportTopicResult>("/v1/topics", { toml, overwrite });
export const createTopic = (
  fields: { id: string; title: string; brief?: string; audience?: string; goals?: string[] },
  overwrite = false,
) => apiPost<{ id: string; title: string }>("/v1/topics", { ...fields, overwrite });
export const importProfile = (toml: string, overwrite = false) =>
  apiPost<ImportProfileResult>("/v1/profiles", { toml, overwrite });
export const attachProfile = (topicId: string, profileId: string) =>
  apiPost<AttachProfileResult>(`/v1/topics/${encodeURIComponent(topicId)}/profile`, {
    profile_id: profileId,
  });
export const enqueueJob = (topicId: string, stage?: string, force = false) =>
  apiPost<Job>(
    "/v1/jobs",
    stage ? { topic_id: topicId, stage, force } : { topic_id: topicId, force },
  );
export const cancelJob = (jobId: string) =>
  apiPost<Job>(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {});
export const downloadFinal = (topicId: string, guideV1 = false) =>
  download(
    `/v1/runs/${encodeURIComponent(topicId)}/final/download`,
    `${topicId}-guide.${guideV1 ? "json" : "md"}`,
  );
export const downloadExport = (topicId: string, format: ExportFormat) =>
  download(
    `/v1/runs/${encodeURIComponent(topicId)}/exports/${format}/download`,
    format === "html" ? `${topicId}-guide.html` : `${topicId}-guide.bundle.md`,
  );

export const getConfigProviders = () =>
  api<{ providers: ProviderAvailability[] }>("/v1/config/providers");
export const getConfigCatalog = () =>
  api<{ providers: CatalogProvider[] }>("/v1/config/catalog");
export const getConfigPlan = () => api<PlanPayload>("/v1/config/plan");
export const putConfigPlan = (
  baseSha256: string,
  provider: string,
  stages: Record<string, StageOverride>,
) =>
  apiPut<PlanPayload>("/v1/config/plan", {
    base_sha256: baseSha256,
    provider,
    stages,
  });
export const getRunPlan = (topicId: string) =>
  api<PlanPayload>(`/v1/runs/${encodeURIComponent(topicId)}/plan`);
export const putRunPlan = (
  topicId: string,
  overrides: Record<string, StageOverride | null>,
) =>
  apiPut<PlanPayload>(`/v1/runs/${encodeURIComponent(topicId)}/plan`, { overrides });
