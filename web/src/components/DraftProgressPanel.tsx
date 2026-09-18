import type { DraftProgress, Job } from "../api/types";

// TODO(T25 green): this is a type-only stub so DraftProgressPanel.test.tsx
// can import a real module (see docs/superpowers/specs/
// 2026-09-18-per-module-drafting-design.md §8 for the intended contract:
// skeleton row, one row per module, batch run/rerun/paste, assemble,
// superseded note, counts, and batch progress/cancel). Every behavior is
// deliberately unimplemented so the red suite stays red until this is
// built out.
export default function DraftProgressPanel(_props: {
  topicId: string;
  progress: DraftProgress;
  activeJobs: Job[];
  onChanged: () => void;
}) {
  return null;
}
