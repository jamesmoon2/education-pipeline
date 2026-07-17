import type { NextAction, StageStatus } from "../api/types";

// Plain-language surface labels for internal state constants (design
// system §3.4/§7.3): learner-facing paths speak in these words; the raw
// constants stay available in details, provenance, and diagnostics.
const STAGE_STATE_LABELS: Record<StageStatus["state"], string> = {
  not_run: "Not started",
  pending: "Waiting",
  prompt_written: "Ready to run",
  response_ingested: "Needs review",
  approved: "Complete",
  stale: "Stale",
};

export function stageStateLabel(state: StageStatus["state"]): string {
  return STAGE_STATE_LABELS[state] ?? state;
}

const NEXT_ACTION_LABELS: Record<NextAction["action"], string> = {
  write_prompt: "Write the next prompt",
  save_response: "Run the stage prompt",
  approve: "Review and approve",
  validate: "Run validation",
  resolve_findings: "Resolve findings",
  finalize: "Finalize",
  done: "Export ready",
};

export function nextActionLabel(action: NextAction["action"]): string {
  return NEXT_ACTION_LABELS[action] ?? action;
}
