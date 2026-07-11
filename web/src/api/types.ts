export interface Session {
  token: string;
  version: string;
}

export interface NextAction {
  topic_id: string;
  stage: string | null;
  action: "write_prompt" | "save_response" | "approve" | "finalize" | "done";
  detail: string;
}

export type StageState =
  | "pending"
  | "prompt_written"
  | "response_ingested"
  | "approved";

export interface StageStatus {
  stage: string;
  state: StageState;
  prompt_written: boolean;
  response_ingested: boolean;
  approved: boolean;
}

export interface RunStatus {
  topic_id: string;
  finalized: boolean;
  stages: StageStatus[];
  next_action: NextAction;
}

export interface TopicSummary {
  id: string;
  title: string | null;
  error: string | null;
  run: RunStatus | null;
}

export interface TopicDetail {
  id: string;
  title: string | null;
  toml: string;
}

export interface StageContent {
  topic_id: string;
  stage: string;
  prompt: string | null;
  response: string | null;
  approved: string | null;
}

export interface Job {
  id: string;
  topic_id: string;
  stage: string;
  provider: string;
  model: string | null;
  effort: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled" | "interrupted";
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  error: string | null;
}

export interface LogChunk {
  data: string;
  offset: number;
}

export type ExportFormat = "html" | "markdown";

export interface AdvanceResult {
  performed: "write_prompt" | "finalize" | null;
  status: RunStatus;
}

export interface ResponseResult {
  topic_id: string;
  stage: string;
  response_path: string;
  status: RunStatus;
}

export interface ApproveResult {
  topic_id: string;
  stage: string;
  approved_path: string;
  status: RunStatus;
}

export interface FinalizeResult {
  topic_id: string;
  final_path: string;
  status: RunStatus;
}

export interface ExportResult {
  topic_id: string;
  format: ExportFormat;
  export_path: string;
}

export interface ImportTopicResult {
  id: string;
  title: string;
}

export interface ImportProfileResult {
  id: string;
}

export interface AttachProfileResult {
  profile_id: string;
  topic_id: string;
  snapshot_path: string;
}
