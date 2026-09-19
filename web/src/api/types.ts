import type { CostSource } from "../lib/cost";

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
    | "done"
    // Per-module drafting (T24/T25): the deterministic step that merges
    // every saved module response (plus the skeleton) into
    // responses/draft.response.json once nothing else is outstanding.
    // `advance` performs it; nothing here requires a model call.
    | "assemble";
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
  // Salvaged provider output that never became a response (thread T04).
  // Optional: fixtures and payloads predating the field simply omit it.
  failed_outputs?: string[];
  // The same, for a draft unit (skeleton or one module): those salvage files
  // are named `draft.<unit>.failed.<ts>.txt` and are promoted into the unit's
  // own response. Optional for the same reason as `failed_outputs`.
  failed_unit_outputs?: FailedUnitOutput[];
}

export interface FailedUnitOutput {
  file: string;
  unit: "skeleton" | "module";
  module_id: string | null;
}

/** One stage's cost roll-up over its job records
 *  (education_pipeline/cost.py summarize_job_costs). `usd` is null when
 *  nothing about that stage's spend is known -- never 0 as a stand-in. */
export interface StageCost {
  usd: number | null;
  source: CostSource;
  jobs: number;
  // How many of those jobs carry no usable price, so `usd` covers only the
  // rest. Optional: payloads and fixtures predating the field omit it, and a
  // missing value means nothing is known to be missing.
  unpriced_jobs?: number;
}

/** A run's cost block: every supported stage plus the run totals. */
export interface RunCost {
  stages: Record<string, StageCost>;
  run_usd: number | null;
  run_source: CostSource;
  // Completeness of `run_usd`: false when some jobs have no usable price, so
  // the total is a known-cost subtotal. Both optional -- a payload without
  // them is treated as complete.
  unpriced_jobs?: number;
  complete?: boolean;
}

/** One library row's cost (GET /v1/topics per-entry `cost`). */
export interface TopicCost {
  run_usd: number | null;
  // False when `run_usd` leaves unpriced jobs out. The row carries no count
  // of its own; absent means complete.
  complete?: boolean;
}

/** The most recent job in the workspace with a known cost for a stage --
 *  what the settings plan editor shows beside that stage's model choice. */
export interface ObservedStageCost {
  usd: number;
  source: string;
  observed_at: string | null;
}

/** GET /v1/topics' top-level cost block: the workspace total, plus the
 *  last observed cost per stage. */
export interface WorkspaceCost {
  workspace_usd: number | null;
  stages?: Record<string, ObservedStageCost>;
  // As RunCost: false when the workspace total omits unpriced jobs, with the
  // count of them. Absent means complete.
  complete?: boolean;
  unpriced_jobs?: number;
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

export interface BlueprintInfo {
  id: string;
  title: string;
  summary: string;
  when_to_use: string;
  required_interactions: string[];
  default_difficulty: string;
}

export interface BlueprintsPayload {
  blueprints: BlueprintInfo[];
  recommendation: { id: string; rationale: string } | null;
  topic_blueprint: string | null;
}

export interface RunBlueprint {
  id: string;
  source: "user" | "topic" | "recommended";
  rationale?: string;
}

export interface RepairModulesPayload {
  topic_id: string;
  modules: {
    id: string;
    title: string;
    open_findings: number;
    // Findings that sit above every section of the module (e.g.
    // `module.no_interaction`, guide-wide rules): a section-scoped repair
    // cannot carry their fix, so the picker forces whole-module scope
    // whenever this is nonzero.
    module_level_findings: number;
    sections: { id: string; title: string; open_findings: number }[];
  }[];
  repair_scope: { module_id: string; section_id: string | null } | null;
}

/** Per-module drafting design, §5: one draft unit's persisted state. */
export type DraftUnitState =
  | "not_run"
  | "prompt_written"
  | "response_ingested"
  | "stale"
  | "orphaned"
  | "superseded";

export interface DraftSkeletonProgress {
  state: DraftUnitState;
  error: string | null;
  job_id: string | null;
}

export interface DraftModuleProgress {
  id: string;
  title: string;
  state: DraftUnitState;
  response_sha256: string | null;
  error: string | null;
  job_id: string | null;
}

export interface DraftAssembledProgress {
  ok: boolean;
  response_sha256: string | null;
  error: string | null;
}

/** `GET /v1/runs/{id}` `draft_progress` block (guide runs only; a legacy
 *  run's payload omits the key entirely, matching `RunStatus.draft_progress`
 *  being optional rather than nullable). */
export interface DraftProgress {
  skeleton: DraftSkeletonProgress;
  modules: DraftModuleProgress[];
  assembled: DraftAssembledProgress | null;
  superseded: boolean;
  parallelism: number;
  counts: { total: number; saved: number; stale: number };
}

export interface RunStatus {
  topic_id: string;
  finalized: boolean;
  content_contract: ContentContract;
  // Optional so pre-blueprint payload fixtures stay valid; the daemon always
  // sends it (null for legacy and pre-blueprint runs).
  blueprint?: RunBlueprint | null;
  stage_provenance: StageProvenance[];
  validations: { draft: ValidationStatus; final: ValidationStatus };
  stages: StageStatus[];
  next_action: NextAction;
  // Present only when the daemon has a job store to sum over; a run whose
  // stages all ran by hand carries an all-null block rather than nothing.
  cost?: RunCost;
  // Present only for guide-v1 runs (the daemon omits the key for legacy
  // Markdown runs and for payload fixtures predating per-module drafting).
  draft_progress?: DraftProgress;
}

export interface WorkspacePayload {
  path: string;
  counts: { topics: number; runs: number; profiles: number };
  first_run: boolean;
}

export interface CompletionSummary {
  stages_approved: number;
  stages_total: number;
  exported: boolean;
}

export interface TopicSummary {
  id: string;
  title: string | null;
  error: string | null;
  run: RunStatus | null;
  archived: boolean;
  last_activity: string | null;
  profile_id: string | null;
  completion: CompletionSummary | null;
  cost?: TopicCost;
}

export interface TopicsPayload {
  topics: TopicSummary[];
  cost?: WorkspaceCost;
}

/** ``POST /v1/runs/{id}/continue`` wire shape
 *  (``education_pipeline.orchestrate`` ``step_payload``/``stop_payload``):
 *  one mechanical step the daemon performed, or the reason it stopped. Kept
 *  structurally identical to ``ContinueStep``/``ContinueStop`` in
 *  ``lib/continueRun.ts`` -- the wire contract and the client's own domain
 *  types are declared separately so this file stays the one place the wire
 *  shape is pinned, but a payload assigns straight into the client type with
 *  no mapping step. */
export type ContinueStepPayload =
  | { kind: "advance"; stage: string | null }
  | { kind: "validate"; stage: string | null; phase: "draft" | "final" }
  | { kind: "job"; stage: string; provider: string; count?: number };

export type ContinueStopPayload =
  | { kind: "started"; stage: string; provider: string; count?: number }
  | { kind: "manual"; stage: string }
  | { kind: "plan_unreadable"; stage: string }
  | { kind: "approve"; stage: string | null }
  | { kind: "resolve_findings" }
  | { kind: "finalize" }
  | { kind: "done" }
  | { kind: "unfinished" }
  | { kind: "failed"; action: string; message: string };

/** ``POST /v1/runs/{id}/continue``: the whole daemon response. ``status`` is
 *  the freshest run status the loop read, or null only when the very first
 *  status read failed. */
export interface ContinuePayload {
  topic_id: string;
  steps: ContinueStepPayload[];
  stop: ContinueStopPayload;
  status: RunStatus | null;
}

export interface ArchiveResult {
  topic_id: string;
  archived: boolean;
}

export interface DuplicateTopicResult {
  id: string;
  title: string | null;
  profile_id?: string;
}

export interface RevealResult {
  path: string;
}

export type RevealTarget = "run" | "export" | "topic";

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
  // Present only on the repair stage of interactive-guide runs. `section_id`
  // is present (non-null) only for a section-scoped repair; a whole-module
  // scope carries no `section_id` key, matching the daemon's payload.
  repair_scope?: { module_id: string; section_id?: string | null } | null;
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
  // Per-module drafting (§5): set only for draft-stage jobs. Optional so
  // records/fixtures predating the field (and every non-draft job) load as
  // before -- a pre-Phase-2 job record loads with these as null.
  unit?: "skeleton" | "module" | null;
  module_id?: string | null;
  batch_id?: string | null;
}

/** `GET /v1/jobs/batch/{id}` and `POST /v1/jobs/batch/{id}/cancel`. */
export interface BatchPayload {
  batch_id: string;
  jobs: Job[];
}

/** `POST /v1/jobs` for a draft module batch: job-shaped at the top level
 *  (the same keys a single job dict carries) plus `batch_id` and `jobs` in
 *  module order (§5). A skeleton-only enqueue has no `batch_id`/`jobs`. */
export type EnqueueJobResult = Job & Partial<BatchPayload>;

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

/** `POST`/`PUT /v1/runs/{id}/draft/skeleton/response` and
 *  `.../draft/modules/{module_id}/response` -- the unit-level twin of
 *  `ResponseResult`. */
export interface DraftUnitResponseResult {
  unit: "skeleton" | "module";
  module_id: string | null;
  response_path: string;
  response_sha256: string;
  status: RunStatus;
}

/** `POST /v1/runs/{id}/draft/assemble`. */
export interface DraftAssembleResult {
  ok: boolean;
  response_sha256: string | null;
  error: string | null;
  module_ids: string[];
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

export type PersonalizationTraceState = "missing" | "current" | "stale" | "invalid";
export type PersonalizationAuditState = "not_run" | "current" | "stale";
export type PersonalizationExportState = "missing" | "current" | "stale";

export interface PersonalizationEvidence {
  kind: "module" | "outcome";
  id: string;
}

export interface PersonalizationGoal {
  goal_id: string;
  goal_text: string;
  status: "served" | "excluded" | "missing";
  evidence: PersonalizationEvidence[];
  exclusions: { reason: string }[];
}

export interface PersonalizationPayload {
  topic_id: string;
  profile: {
    state: "not_attached" | "attached";
    id: string | null;
  };
  trace: {
    state: PersonalizationTraceState;
    goals: PersonalizationGoal[];
    facets: string[];
  };
  audit: {
    state: PersonalizationAuditState;
    stage_state: StageState;
    available: boolean;
    unavailable_reason: string | null;
    findings: ValidationFinding[];
  };
  findings: ValidationFinding[];
  export: { state: PersonalizationExportState };
}

export interface AuditPreparationResult {
  topic_id: string;
  stage: "audit";
  prompt_path: string;
  response_path: string;
  audit: { state: PersonalizationAuditState; finding_count: number };
  next_steps: {
    manual: { action: "save_response"; stage: "audit"; response_path: string };
    provider: { action: "enqueue"; stage: "audit"; force?: boolean };
  };
}

export interface ImportTopicResult {
  id: string;
  title: string;
}

export interface ImportProfileResult {
  id: string;
}

export interface ProfileDraftResult {
  toml: string;
  profile_id: string;
  provider: string;
  model: string | null;
  effort: string | null;
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
  source_stage?: string;
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
  /**
   * Whether this provider's CLI accepts an effort option at all (Claude Code
   * `--effort`, Codex `model_reasoning_effort`). Optional so fixtures and
   * older daemons that predate the field still type-check; treat a missing
   * value as "assume it does".
   */
  supports_effort?: boolean;
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

export interface PresetStagePayload {
  model: string;
  effort: string | null;
}

export interface CatalogPreset {
  id: string;
  label: string;
  description: string;
  stages: Record<string, Record<string, PresetStagePayload>>;
}

export interface PlanStage {
  stage: string;
  provider: string | null;
  model: string | null;
  effort: string | null;
  // Optional per-stage provider timeout, set by hand in model-plan.toml.
  // Reported by the API; the cockpit has no editor for it yet.
  timeout_seconds?: number | null;
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
  // Decision 10: bounds concurrently *running* module jobs of one draft
  // batch, 1..4, default 2. Optional so payload/fixtures predating
  // per-module drafting stay valid; the daemon always sends it.
  parallelism?: number;
}

export interface StageOverride {
  provider?: string;
  model?: string;
  effort?: string;
  timeout_seconds?: number;
  recommendation?: string;
}

export interface CockpitBuild {
  status: "ok" | "stale" | "missing";
  build_id: string | null;
}

export interface HealthPayload {
  version: string;
  ok: boolean;
  started_at: string | null;
  cockpit_build?: CockpitBuild;
}
