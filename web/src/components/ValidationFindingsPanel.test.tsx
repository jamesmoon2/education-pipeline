import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ValidationReport } from "../api/types";
import ValidationFindingsPanel from "./ValidationFindingsPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getValidation: vi.fn(),
    getWaivers: vi.fn(),
    postWaiver: vi.fn(),
  };
});

import { ApiRequestError, getValidation, getWaivers, postWaiver } from "../api/client";

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
    },
  ],
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

  it("maps final findings to the repair stage", async () => {
    vi.mocked(getValidation).mockResolvedValue({
      state: "current",
      report: { ...report, phase: "final" },
    });
    renderPanel("current", { phase: "final" });
    const links = await screen.findAllByRole("link", { name: /Open source/ });
    expect(links).not.toHaveLength(0);
    for (const link of links) {
      expect(link).toHaveAttribute("href", expect.stringContaining("/stages/repair?"));
    }
  });
});
