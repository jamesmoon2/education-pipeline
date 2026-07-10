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
