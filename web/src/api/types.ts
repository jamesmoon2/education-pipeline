export interface Session {
  token: string;
  version: string;
}

export interface NextAction {
  topic_id: string;
  stage: string | null;
  action:
    | "write_prompt"
    | "save_response"
    | "approve"
    | "validate"
    | "resolve_findings"
    | "finalize"
    | "done";
  detail: string;
}

export type StageState =
  | "pending"
  | "prompt_written"
  | "response_ingested"
  | "approved"
  | "stale";

export interface ContentContract {
  kind: "legacy_markdown" | "interactive_guide";
  schema_version?: string;
}

export type ValidationState = "missing" | "current" | "stale";

export interface ValidationCounts {
  blocking: number;
  errors: number;
  warnings: number;
}

export interface ValidationStatus extends ValidationCounts {
  state: ValidationState;
  findings_by_stage?: Record<string, number>;
  // Post-waiver blocking count (RunStore.gate_result). Optional: omitted by
  // non-guide runs and by any payload/fixture predating this field -- kept
  // optional rather than required for the same reason findings_by_stage was
  // (a required field broke four out-of-scope fixtures last time).
  effective_blocking?: number;
}

export interface StageStatus {
  stage: string;
  state: StageState;
  prompt_written: boolean;
  response_ingested: boolean;
  approved: boolean;
}

export interface StageProvenance {
  stage: string;
  provider: string;
  model: string | null;
  effort: string | null;
  source: string;
  job_id: string | null;
  recorded_at: string;
}

export interface RunStatus {
  topic_id: string;
  finalized: boolean;
  content_contract: ContentContract;
  stage_provenance: StageProvenance[];
  validations: { draft: ValidationStatus; final: ValidationStatus };
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
  response_sha256: string | null;
  content_type:
    | "text/markdown"
    | "application/vnd.education-pipeline.guide+json;version=1.0";
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

export interface EditResponseResult {
  topic_id: string;
  stage: string;
  response_path: string;
  response_sha256: string;
}

export interface PreviewResult {
  html: string;
}

export interface ValidationFinding {
  id: string;
  rule_id: string;
  severity: "blocker" | "error" | "warning" | "info";
  blocking: boolean;
  waivable: boolean;
  path: string;
  message: string;
  remediation: string;
  related_ids?: string[];
  stage?: string;
}

export interface ValidationReport {
  report_schema_version: number;
  guide_schema_version: string;
  phase: "draft" | "final";
  guide_sha256: string;
  validator_version: string;
  summary: ValidationCounts & { info: number };
  findings: ValidationFinding[];
}

export interface ValidationResult {
  state: ValidationState;
  report: ValidationReport;
}

export interface ValidateResult extends ValidationResult {
  status: RunStatus;
}

export interface Waiver {
  finding_id: string;
  reason: string;
}

export interface WaiverSet {
  schema_version: number;
  guide_sha256: string;
  waivers: Waiver[];
}

export interface WaiverResult extends ValidationResult {
  waivers: WaiverSet;
}

export interface WaiversResult {
  state: ValidationState;
  waivers: WaiverSet;
}

export interface GuidePreviewResult {
  html: string;
  content_sha256: string;
  validation: ValidationCounts;
}

export interface ProviderAvailability {
  id: string;
  label: string;
  description: string;
  executable: boolean;
  available: boolean;
  reason: string | null;
}

export interface CatalogModel {
  id: string;
  label: string;
  description: string;
  quality: string | null;
  default_effort: string | null;
}

export interface CatalogProvider {
  id: string;
  label: string;
  description: string;
  models: CatalogModel[];
}

export interface PlanStage {
  stage: string;
  provider: string | null;
  model: string | null;
  effort: string | null;
  recommendation: string;
  warning: string | null;
  source?: "default" | "override";
  override_error?: string | null;
  command?: string[] | null;
}

export interface PlanPayload {
  provider: string;
  plan_sha256: string;
  stages: PlanStage[];
}

export interface StageOverride {
  provider?: string;
  model?: string;
  effort?: string;
  recommendation?: string;
}
