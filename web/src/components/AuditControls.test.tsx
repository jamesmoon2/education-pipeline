import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PersonalizationPayload } from "../api/types";
import AuditControls from "./AuditControls";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    approveAudit: vi.fn(),
    enqueueAuditJob: vi.fn(),
    prepareAudit: vi.fn(),
  };
});

import { approveAudit, enqueueAuditJob, prepareAudit } from "../api/client";

const baseAudit: PersonalizationPayload["audit"] = {
  state: "not_run",
  stage_state: "not_run",
  available: true,
  unavailable_reason: null,
  findings: [],
};

function renderControls(
  audit: PersonalizationPayload["audit"],
  exportState: PersonalizationPayload["export"]["state"] = "missing",
) {
  const onChanged = vi.fn();
  render(
    <MemoryRouter>
      <AuditControls
        topicId="feedback loops"
        audit={audit}
        exportState={exportState}
        onChanged={onChanged}
      />
    </MemoryRouter>,
  );
  return onChanged;
}

describe("AuditControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    vi.mocked(prepareAudit).mockResolvedValue({} as never);
    vi.mocked(enqueueAuditJob).mockResolvedValue({} as never);
    vi.mocked(approveAudit).mockResolvedValue({} as never);
  });

  it("explains an unavailable audit without offering actions", () => {
    renderControls({
      ...baseAudit,
      available: false,
      unavailable_reason: "Final validation is not current.",
    });

    expect(screen.getByText(/Final validation is not current\./)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("prepares an eligible audit explicitly", async () => {
    const onChanged = renderControls(baseAudit);
    await userEvent.click(screen.getByRole("button", { name: "Prepare audit" }));

    expect(prepareAudit).toHaveBeenCalledWith("feedback loops", false);
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("Audit prompt prepared.");
  });

  it("offers provider and manual response paths after preparation", async () => {
    const onChanged = renderControls({ ...baseAudit, stage_state: "prompt_written" });

    expect(screen.getByRole("link", { name: "Paste audit response…" })).toHaveAttribute(
      "href",
      "/topics/feedback%20loops/stages/audit?tab=response&paste=1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Run audit with provider" }));

    expect(enqueueAuditJob).toHaveBeenCalledWith("feedback loops", false);
    expect(onChanged).toHaveBeenCalled();
  });

  it("offers review, approval, and forced provider rerun for an ingested response", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = renderControls({ ...baseAudit, stage_state: "response_ingested" });

    expect(screen.getByRole("link", { name: "Review audit response" })).toHaveAttribute(
      "href",
      "/topics/feedback%20loops/stages/audit?tab=response",
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve audit" }));
    expect(approveAudit).toHaveBeenCalledWith("feedback loops", false);

    await userEvent.click(screen.getByRole("button", { name: "Rerun audit with provider…" }));
    expect(enqueueAuditJob).toHaveBeenCalledWith("feedback loops", true);
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("presents a current approved audit as optional and still permits rerun", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderControls({
      ...baseAudit,
      state: "current",
      stage_state: "approved",
      findings: [
        {
          id: "audit.goal:goal-001",
          rule_id: "audit.goal",
          severity: "warning",
          blocking: false,
          waivable: false,
          path: "/modules/0",
          message: "Review goal coverage.",
          remediation: "Review the repair guide.",
          stage: "audit",
          source_stage: "repair",
        },
      ],
    });

    expect(screen.getByText(/current with 1 projected finding/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review approved audit" })).toHaveAttribute(
      "href",
      "/topics/feedback%20loops/stages/audit?tab=approved",
    );
    await userEvent.click(screen.getByRole("button", { name: "Rerun audit with provider…" }));
    expect(enqueueAuditJob).toHaveBeenCalledWith("feedback loops", true);
  });

  it("requires confirmation before replacing an existing response", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderControls({ ...baseAudit, stage_state: "response_ingested" });

    await userEvent.click(screen.getByRole("button", { name: "Rerun audit with provider…" }));
    expect(enqueueAuditJob).not.toHaveBeenCalled();
  });

  it("rebuilds stale audit inputs and then exposes provider and manual paths", async () => {
    renderControls({ ...baseAudit, state: "stale", stage_state: "stale" });

    expect(screen.getByText(/audit is stale/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rebuild audit prompt" }));
    expect(prepareAudit).toHaveBeenCalledWith("feedback loops", true);

    expect(await screen.findByRole("button", { name: "Run audit with provider" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paste audit response…" })).toBeInTheDocument();
  });

  it("never force-runs a rebuilt stale audit without confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderControls({ ...baseAudit, state: "stale", stage_state: "stale" });

    await userEvent.click(screen.getByRole("button", { name: "Rebuild audit prompt" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Run audit with provider" }),
    );

    expect(window.confirm).toHaveBeenCalled();
    expect(enqueueAuditJob).not.toHaveBeenCalled();
  });

  it("clears local prepared readiness when authoritative stage state advances", async () => {
    const onChanged = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <AuditControls
          topicId="feedback loops"
          audit={baseAudit}
          exportState="missing"
          onChanged={onChanged}
        />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Prepare audit" }));
    expect(await screen.findByRole("link", { name: "Paste audit response…" })).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <AuditControls
          topicId="feedback loops"
          audit={{ ...baseAudit, stage_state: "response_ingested" }}
          exportState="missing"
          onChanged={onChanged}
        />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Paste audit response…" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Review audit response" })).toBeInTheDocument();
  });

  it("prompts for re-export only when exported public artifacts are stale", () => {
    const currentAudit = { ...baseAudit, state: "current" as const, stage_state: "approved" as const };
    const { rerender } = render(
      <MemoryRouter>
        <AuditControls
          topicId="feedback loops"
          audit={currentAudit}
          exportState="stale"
          onChanged={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/Re-export the guide to publish the current audit projection/)).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <AuditControls
          topicId="feedback loops"
          audit={currentAudit}
          exportState="current"
          onChanged={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/Re-export the guide/)).not.toBeInTheDocument();
  });

  it("surfaces action errors and re-enables the control", async () => {
    vi.mocked(prepareAudit).mockRejectedValue(new Error("Audit inputs changed; retry."));
    renderControls(baseAudit);

    await userEvent.click(screen.getByRole("button", { name: "Prepare audit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Audit inputs changed; retry.");
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare audit" })).toBeEnabled());
  });
});
