import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RunStatus, ValidationReport } from "../api/types";
import ValidationFindingsPanel from "./ValidationFindingsPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getValidation: vi.fn(),
    getWaivers: vi.fn(),
    postWaiver: vi.fn(),
    postValidate: vi.fn(),
  };
});

import {
  ApiRequestError,
  getValidation,
  getWaivers,
  postValidate,
  postWaiver,
} from "../api/client";

const report: ValidationReport = {
  report_schema_version: 1,
  guide_schema_version: "1.0",
  phase: "draft",
  guide_sha256: "a".repeat(64),
  validator_version: "1",
  summary: { blocking: 1, errors: 1, warnings: 1, info: 0 },
  findings: [
    {
      id: "unsafe:one",
      rule_id: "unsafe",
      severity: "error",
      blocking: true,
      waivable: false,
      path: "/modules/0/sections/0/blocks/0",
      message: "Unsafe content.",
      remediation: "Remove it.",
      related_ids: ["block-one"],
      stage: "draft",
    },
    {
      id: "quality:two",
      rule_id: "quality",
      severity: "warning",
      blocking: false,
      waivable: true,
      path: "/modules/0/sections/1",
      message: "Improve this section.",
      remediation: "Add detail.",
      stage: "draft",
    },
  ],
};

const runStatus: RunStatus = {
  topic_id: "feedback loops",
  finalized: false,
  content_contract: { kind: "interactive_guide" },
  stage_provenance: [],
  validations: {
    draft: { state: "current", blocking: 0, errors: 0, warnings: 1 },
    final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
  },
  stages: [],
  next_action: {
    topic_id: "feedback loops",
    stage: null,
    action: "done",
    detail: "",
  },
};

function renderPanel(
  state: "missing" | "current" | "stale" = "current",
  overrides: Partial<Parameters<typeof ValidationFindingsPanel>[0]> = {},
) {
  const props = {
    topicId: "feedback loops",
    phase: "draft" as const,
    state,
    onChanged: vi.fn(),
    ...overrides,
  };
  render(<ValidationFindingsPanel {...props} />);
  return props;
}

describe("ValidationFindingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getValidation).mockResolvedValue({ state: "current", report });
    vi.mocked(getWaivers).mockResolvedValue({
      state: "current",
      waivers: { schema_version: 1, guide_sha256: report.guide_sha256, waivers: [] },
    });
  });

  it("shows missing distinctly without requesting a report", () => {
    renderPanel("missing");
    expect(screen.getByText("No draft validation report yet.")).toBeInTheDocument();
    expect(getValidation).not.toHaveBeenCalled();
    expect(getWaivers).not.toHaveBeenCalled();
  });

  it("loads current findings and links to the phase source with path and related id", async () => {
    renderPanel();
    expect(screen.getByText("The draft validation report is current.")).toBeInTheDocument();
    expect(await screen.findByText("Unsafe content.")).toBeInTheDocument();
    expect(getValidation).toHaveBeenCalledWith("feedback loops", "draft");
    expect(screen.getByRole("link", { name: /Open source at \/modules\/0\/sections\/0\/blocks\/0/ }))
      .toHaveAttribute(
        "href",
        "/topics/feedback%20loops/stages/draft?json_path=%2Fmodules%2F0%2Fsections%2F0%2Fblocks%2F0&related_id=block-one",
      );
    expect(screen.getByText(/1 blocking · 1 errors · 1 warnings · 0 waived/)).toBeInTheDocument();
  });

  it("filters independently by severity and finding status", async () => {
    renderPanel();
    await screen.findByText("Unsafe content.");
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "warning");
    expect(screen.queryByText("Unsafe content.")).not.toBeInTheDocument();
    expect(screen.getByText("Improve this section.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "blocking");
    expect(screen.getByText("No findings match these filters.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "all");
    expect(screen.getByText("Unsafe content.")).toBeInTheDocument();
  });

  it("shows stale findings distinctly and never offers a stale waiver", async () => {
    vi.mocked(getValidation).mockResolvedValue({ state: "stale", report });
    renderPanel("stale");
    expect(screen.getByText(/report is stale/)).toBeInTheDocument();
    expect(await screen.findByText("Improve this section.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Waive…" })).not.toBeInTheDocument();
  });

  it("offers Re-run validation when the report is stale", async () => {
    vi.mocked(getValidation).mockResolvedValue({ state: "stale", report });
    renderPanel("stale");
    expect(await screen.findByRole("button", { name: "Re-run validation" })).toBeInTheDocument();
  });

  it("offers Re-run validation for a current report with blocking findings", async () => {
    renderPanel(); // default report has summary.blocking === 1
    expect(await screen.findByRole("button", { name: "Re-run validation" })).toBeInTheDocument();
  });

  it("does not offer Re-run validation for a current, clean report", async () => {
    const cleanReport: ValidationReport = {
      ...report,
      summary: { blocking: 0, errors: 0, warnings: 0, info: 0 },
      findings: [],
    };
    vi.mocked(getValidation).mockResolvedValue({ state: "current", report: cleanReport });
    renderPanel();
    await screen.findByText("The draft validation report is current.");
    expect(screen.queryByRole("button", { name: "Re-run validation" })).not.toBeInTheDocument();
  });

  it("does not offer Re-run validation when every blocker is waived (effectiveBlocking 0) despite raw blocking findings", async () => {
    // report.summary.blocking is 1 (unwaived on disk), but the caller
    // supplies the post-waiver gate count of 0: the raw finding still
    // lists (marked waived) but there is nothing left to re-run for.
    renderPanel("current", { effectiveBlocking: 0 });
    await screen.findByText("The draft validation report is current.");
    expect(screen.queryByRole("button", { name: "Re-run validation" })).not.toBeInTheDocument();
  });

  it("offers Re-run validation when effectiveBlocking is greater than 0", async () => {
    renderPanel("current", { effectiveBlocking: 2 });
    expect(await screen.findByRole("button", { name: "Re-run validation" })).toBeInTheDocument();
  });

  it("offers Re-run validation for a stale report regardless of effectiveBlocking", async () => {
    vi.mocked(getValidation).mockResolvedValue({ state: "stale", report });
    renderPanel("stale", { effectiveBlocking: 0 });
    expect(await screen.findByRole("button", { name: "Re-run validation" })).toBeInTheDocument();
  });

  it("re-runs validation, disables the button while in flight, updates counts, and notifies the parent", async () => {
    let resolvePost!: (value: {
      state: "current";
      report: ValidationReport;
      status: RunStatus;
    }) => void;
    vi.mocked(postValidate).mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      }),
    );
    const props = renderPanel("stale");
    const button = await screen.findByRole("button", { name: "Re-run validation" });
    await userEvent.click(button);

    expect(postValidate).toHaveBeenCalledWith("feedback loops", "draft");
    expect(screen.getByRole("button", { name: /Re-running/ })).toBeDisabled();

    const updatedReport: ValidationReport = {
      ...report,
      summary: { blocking: 0, errors: 0, warnings: 1, info: 0 },
      findings: [report.findings[1]],
    };
    resolvePost({ state: "current", report: updatedReport, status: runStatus });

    await waitFor(() =>
      expect(screen.getByText(/0 blocking · 0 errors · 1 warnings · 0 waived/)).toBeInTheDocument(),
    );
    expect(props.onChanged).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Re-run validation" })).not.toBeDisabled();
  });

  it("surfaces an ApiRequestError from Re-run validation", async () => {
    vi.mocked(postValidate).mockRejectedValue(
      new ApiRequestError(409, "stale_validation", "The guide changed since the last approval."),
    );
    renderPanel("stale");
    const button = await screen.findByRole("button", { name: "Re-run validation" });
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The guide changed since the last approval.",
    );
    expect(screen.getByRole("button", { name: "Re-run validation" })).not.toBeDisabled();
  });

  it("separates stale saved waivers from current findings", async () => {
    vi.mocked(getWaivers).mockResolvedValue({
      state: "stale",
      waivers: {
        schema_version: 1,
        guide_sha256: "b".repeat(64),
        waivers: [{ finding_id: "quality:two", reason: "Old reason" }],
      },
    });
    renderPanel();
    expect(await screen.findByText(/Saved waivers are stale/)).toBeInTheDocument();
    expect(screen.queryByText("waived")).toBeNull();
  });

  it("requires a non-empty reason and submits the exact report hash", async () => {
    vi.mocked(postWaiver).mockResolvedValue({
      state: "current",
      report,
      waivers: {
        schema_version: 1,
        guide_sha256: report.guide_sha256,
        waivers: [{ finding_id: "quality:two", reason: "Accepted for this release" }],
      },
    });
    const props = renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Waive…" }));
    const dialog = screen.getByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Confirm waiver" });
    expect(submit).toBeDisabled();
    expect(within(dialog).getByText(report.guide_sha256)).toBeInTheDocument();

    await userEvent.type(within(dialog).getByLabelText("Reason"), "Accepted for this release");
    await userEvent.click(submit);
    await waitFor(() => expect(postWaiver).toHaveBeenCalledWith(
      "feedback loops",
      "draft",
      "quality:two",
      report.guide_sha256,
      "Accepted for this release",
    ));
    expect(props.onChanged).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("waived")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "waived");
    expect(screen.getByText("Improve this section.")).toBeInTheDocument();
    expect(screen.queryByText("Unsafe content.")).not.toBeInTheDocument();
  });

  it.each([
    [409, "stale_validation", "The guide changed."],
    [422, "finding_not_waivable", "This finding cannot be waived."],
  ])("preserves the waiver reason after HTTP %s envelope feedback", async (status, code, message) => {
    vi.mocked(postWaiver).mockRejectedValue(new ApiRequestError(status, code, message));
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Waive…" }));
    const reason = screen.getByLabelText("Reason");
    await userEvent.type(reason, "My carefully considered reason");
    await userEvent.click(screen.getByRole("button", { name: "Confirm waiver" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(reason).toHaveValue("My carefully considered reason");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("links each finding to its own responsible stage, not the panel's phase", async () => {
    vi.mocked(getValidation).mockResolvedValue({
      state: "current",
      report: {
        ...report,
        phase: "final",
        findings: [
          { ...report.findings[0], stage: "outline" },
          { ...report.findings[1], stage: "repair" },
        ],
      },
    });
    renderPanel("current", { phase: "final" });
    const links = await screen.findAllByRole("link", { name: /Open source/ });
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/stages/outline?"));
    expect(links[1]).toHaveAttribute("href", expect.stringContaining("/stages/repair?"));
  });

  it("falls back to the repair stage for a pre-v2 finding with no stage on a final-phase report", async () => {
    const { stage: _stage, ...findingWithoutStage } = report.findings[0];
    vi.mocked(getValidation).mockResolvedValue({
      state: "current",
      report: {
        ...report,
        phase: "final",
        findings: [findingWithoutStage as typeof report.findings[0]],
      },
    });
    renderPanel("current", { phase: "final" });
    const link = await screen.findByRole("link", { name: /Open source/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("/stages/repair?"));
  });

  it("falls back to the draft stage for a pre-v2 finding with no stage on a draft-phase report", async () => {
    const { stage: _stage, ...findingWithoutStage } = report.findings[0];
    vi.mocked(getValidation).mockResolvedValue({
      state: "current",
      report: {
        ...report,
        phase: "draft",
        findings: [findingWithoutStage as typeof report.findings[0]],
      },
    });
    renderPanel("current", { phase: "draft" });
    const link = await screen.findByRole("link", { name: /Open source/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("/stages/draft?"));
  });
});
