import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Job, RunStatus } from "../api/types";
import PipelineStepper, { latestProvenanceByStage } from "./PipelineStepper";

function makeStatus(overrides: Partial<RunStatus> = {}): RunStatus {
  return {
    topic_id: "t",
    finalized: false,
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [
      { stage: "spec", state: "approved", prompt_written: true, response_ingested: true, approved: true },
      { stage: "outline", state: "prompt_written", prompt_written: true, response_ingested: false, approved: false },
      { stage: "draft", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    ],
    next_action: {
      topic_id: "t",
      stage: "outline",
      action: "save_response",
      detail: "Run the outline prompt and save the response.",
    },
    ...overrides,
  };
}

function renderStepper(status: RunStatus, activeJob: Job | null = null, findings: Record<string, number> = {}) {
  return render(
    <MemoryRouter>
      <PipelineStepper status={status} activeJob={activeJob} findingsByStage={findings} />
    </MemoryRouter>,
  );
}

describe("PipelineStepper", () => {
  it("renders one step per stage with plain-language state labels", () => {
    renderStepper(makeStatus());
    const list = screen.getByRole("list", { name: "Run pipeline" });
    const steps = within(list).getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(within(steps[0]).getByText("Complete")).toBeInTheDocument();
    expect(within(steps[1]).getByText("Ready to run")).toBeInTheDocument();
    expect(within(steps[2]).getByText("Waiting")).toBeInTheDocument();
  });

  it("links each step to its stage page", () => {
    renderStepper(makeStatus());
    expect(screen.getByRole("link", { name: "outline" })).toHaveAttribute(
      "href",
      "/topics/t/stages/outline",
    );
  });

  it("marks the next-action stage as the current step", () => {
    renderStepper(makeStatus());
    const current = screen.getByRole("listitem", { name: "outline stage" });
    expect(current).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("listitem", { name: "spec stage" })).not.toHaveAttribute("aria-current");
  });

  it("shows a findings badge only for stages with findings", () => {
    renderStepper(makeStatus(), null, { outline: 3, draft: 1 });
    const outline = screen.getByRole("listitem", { name: "outline stage" });
    expect(within(outline).getByLabelText("3 findings")).toHaveTextContent("3");
    const draft = screen.getByRole("listitem", { name: "draft stage" });
    expect(within(draft).getByLabelText("1 finding")).toHaveTextContent("1");
    const spec = screen.getByRole("listitem", { name: "spec stage" });
    expect(within(spec).queryByLabelText(/finding/)).not.toBeInTheDocument();
  });

  it("replaces the state label with live job status on the job's stage", () => {
    const job: Job = {
      id: "job-1",
      topic_id: "t",
      stage: "outline",
      provider: "claude-code",
      model: null,
      effort: null,
      status: "running",
      created_at: "2026-01-01T00:00:00Z",
      started_at: "2026-01-01T00:00:01Z",
      ended_at: null,
      exit_code: null,
      error: null,
    };
    renderStepper(makeStatus(), job);
    const outline = screen.getByRole("listitem", { name: "outline stage" });
    expect(within(outline).getByText("Running with claude-code…")).toBeInTheDocument();
    expect(within(outline).queryByText("Ready to run")).not.toBeInTheDocument();
    const spec = screen.getByRole("listitem", { name: "spec stage" });
    expect(within(spec).getByText("Complete")).toBeInTheDocument();
  });

  it("shows the latest provenance entry for a re-run stage", () => {
    const status = makeStatus({
      stage_provenance: [
        { stage: "spec", provider: "codex", model: null, effort: null, source: "job", job_id: "j1", recorded_at: "2026-01-01T00:00:00Z" },
        { stage: "spec", provider: "claude-code", model: "sonnet", effort: "high", source: "job", job_id: "j2", recorded_at: "2026-01-02T00:00:00Z" },
      ],
    });
    renderStepper(status);
    const spec = screen.getByRole("listitem", { name: "spec stage" });
    expect(within(spec).getByText("ran on claude-code / sonnet / high (job)")).toBeInTheDocument();
    expect(within(spec).queryByText(/codex/)).not.toBeInTheDocument();
  });
});

describe("latestProvenanceByStage", () => {
  it("keeps the most recently recorded entry per stage", () => {
    const latest = latestProvenanceByStage([
      { stage: "spec", provider: "a", model: null, effort: null, source: "job", job_id: null, recorded_at: "2026-01-02T00:00:00Z" },
      { stage: "spec", provider: "b", model: null, effort: null, source: "job", job_id: null, recorded_at: "2026-01-01T00:00:00Z" },
      { stage: "qa", provider: "c", model: null, effort: null, source: "job", job_id: null, recorded_at: "2026-01-01T00:00:00Z" },
    ]);
    expect(latest.get("spec")?.provider).toBe("a");
    expect(latest.get("qa")?.provider).toBe("c");
  });
});
