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
  | "not_run"
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
    | "application/json"
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

export interface ProfileSummary {
  id: string;
  attached_topic_count: number;
}

export type ProfileSensitivityTier = "high" | "medium" | "low";
export type ProfileSensitivity = Record<string, ProfileSensitivityTier>;

const profileMetadataNumberMarker = Symbol("profileMetadataNumber");

export interface ProfileMetadataNumber {
  readonly kind: "integer" | "float";
  readonly text: string;
  readonly [profileMetadataNumberMarker]: true;
}

export function metadataNumber(text: string, kind: ProfileMetadataNumber["kind"]): ProfileMetadataNumber {
  return { kind, text, [profileMetadataNumberMarker]: true };
}

export function isMetadataNumber(value: unknown): value is ProfileMetadataNumber {
  return typeof value === "object" && value !== null && profileMetadataNumberMarker in value;
}

export function metadataNumberValidationMessage(value: ProfileMetadataNumber): string | null {
  if (value.kind === "integer") {
    return /^-?(?:0|[1-9]\d*)$/.test(value.text) ? null : "Enter a valid integer.";
  }
  return /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value.text)
    ? null
    : "Enter a valid decimal.";
}

export function hasInvalidMetadataNumber(value: ProfileMetadataValue): boolean {
  if (isMetadataNumber(value)) return metadataNumberValidationMessage(value) !== null;
  if (Array.isArray(value)) return value.some(hasInvalidMetadataNumber);
  if (typeof value === "object" && value !== null) return Object.values(value).some(hasInvalidMetadataNumber);
  return false;
}

export type ProfileMetadataValue =
  | string
  | boolean
  | number
  | ProfileMetadataNumber
  | ProfileMetadataValue[]
  | { [key: string]: ProfileMetadataValue };

export interface LearnerPreferences {
  preferred_modalities: string[];
  explanation_style?: string;
  preferred_visual_aids: string[];
  diagram_frequency?: string;
  interaction_style?: string;
  practice_style: string[];
  feedback_style?: string;
  worked_example_preference?: string;
  common_sticking_points: string[];
  attention_constraints: string[];
  review_style: string[];
}

export interface LearnerLocalization {
  jurisdiction?: string;
  locale?: string;
  units?: string;
  language_register?: string;
}

export interface LearnerPrivacy {
  private_by_default: boolean;
  include_in_published_output: boolean;
  publishable_summary?: string;
}

export interface LearnerProfile {
  schema_version: number;
  id: string;
  target_learner: string;
  prior_education?: string;
  prior_experience?: string;
  professional_experience?: string;
  current_skill_level?: string;
  adjacent_domains: string[];
  learning_goals: string[];
  preferred_examples: string[];
  examples_to_avoid: string[];
  math_comfort?: string;
  reading_level?: string;
  pace?: string;
  desired_depth?: string;
  time_budget?: string;
  assessment_styles: string[];
  accessibility_constraints: string[];
  tone_preference?: string;
  sensitive_areas: string[];
  learning_preferences: LearnerPreferences;
  localization: LearnerLocalization;
  privacy: LearnerPrivacy;
  metadata: { [key: string]: ProfileMetadataValue };
}

export interface ProfileWarning {
  code: string;
  field_path: string;
  fingerprint: string;
}

export interface ProfileDetail {
  id: string;
  parsed: LearnerProfile;
  sensitivity: ProfileSensitivity;
  content_sha256: string;
  warnings: ProfileWarning[];
  attached_topic_count: number;
}

export interface ProfilePreview {
  parsed: LearnerProfile;
  prompt_context: string;
  publishable_summary: string | null;
  sensitivity: ProfileSensitivity;
  warnings: ProfileWarning[];
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
