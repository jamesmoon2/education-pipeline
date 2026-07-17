import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PersonalizationPayload } from "../api/types";
import PersonalizationPanel from "./PersonalizationPanel";

function payload(overrides: Partial<PersonalizationPayload> = {}): PersonalizationPayload {
  return {
    topic_id: "feedback-loops",
    profile: { state: "attached", id: "learner-a" },
    trace: {
      state: "current",
      facets: ["pacing", "prior knowledge"],
      goals: [
        {
          goal_id: "goal-001",
          goal_text: "Recognize feedback loops",
          status: "served",
          evidence: [
            { kind: "module", id: "loop-basics" },
            { kind: "outcome", id: "identify-loop" },
          ],
          exclusions: [],
        },
        {
          goal_id: "goal-002",
          goal_text: "Model a complex organization",
          status: "excluded",
          evidence: [],
          exclusions: [{ reason: "Outside this course's scope." }],
        },
      ],
    },
    audit: {
      state: "not_run",
      stage_state: "not_run",
      available: true,
      unavailable_reason: null,
      findings: [],
    },
    findings: [],
    export: { state: "missing" },
    ...overrides,
  };
}

describe("PersonalizationPanel", () => {
  it("explains active facets and the optional audit with InfoTips", () => {
    render(<PersonalizationPanel personalization={payload()} onEvidence={vi.fn()} />);
    expect(screen.getByRole("button", { name: "About Active facets" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About Optional audit" })).toBeInTheDocument();
  });

  it("renders current goal, facet, exclusion, trace-only, and evidence states", async () => {
    const onEvidence = vi.fn();
    render(<PersonalizationPanel personalization={payload()} onEvidence={onEvidence} />);

    const panel = screen.getByRole("region", { name: "Personalization fit" });
    expect(within(panel).getByText("Profile: learner-a")).toBeInTheDocument();
    expect(within(panel).getByText("pacing")).toBeInTheDocument();
    expect(within(panel).getByText("prior knowledge")).toBeInTheDocument();
    expect(within(panel).getByText("Recognize feedback loops")).toBeInTheDocument();
    expect(within(panel).getByText(/Outside this course's scope\./)).toBeInTheDocument();
    expect(within(panel).getByText(/Optional audit has not been run/)).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("button", { name: "Open module loop-basics" }));
    await userEvent.click(within(panel).getByRole("button", { name: "Open outcome identify-loop" }));
    expect(onEvidence).toHaveBeenNthCalledWith(1, { kind: "module", id: "loop-basics" });
    expect(onEvidence).toHaveBeenNthCalledWith(2, { kind: "outcome", id: "identify-loop" });
  });

  it("renders no-profile without leaking into an invented trace state", () => {
    render(
      <PersonalizationPanel
        personalization={payload({
          profile: { state: "not_attached", id: null },
          trace: { state: "missing", goals: [], facets: [] },
          audit: {
            state: "not_run",
            stage_state: "not_run",
            available: false,
            unavailable_reason: "No learner profile is attached.",
            findings: [],
          },
        })}
        onEvidence={vi.fn()}
      />,
    );
    expect(screen.getByText("No learner profile is attached.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open/ })).not.toBeInTheDocument();
  });

  it.each([
    ["missing", "Personalization trace is not available yet."],
    ["stale", "Personalization trace is stale."],
    ["invalid", "Personalization trace is invalid."],
  ] as const)("renders the %s trace state without stale evidence controls", (state, message) => {
    render(
      <PersonalizationPanel
        personalization={payload({ trace: { state, goals: [], facets: [] } })}
        onEvidence={vi.fn()}
      />,
    );
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open/ })).not.toBeInTheDocument();
  });

  it("distinguishes current and stale audit plus stale export", () => {
    const { rerender } = render(
      <PersonalizationPanel
        personalization={payload({
          audit: {
            state: "current",
            stage_state: "approved",
            available: true,
            unavailable_reason: null,
            findings: [],
          },
          export: { state: "current" },
        })}
        onEvidence={vi.fn()}
      />,
    );
    expect(screen.getByText("Optional audit is current.")).toBeInTheDocument();
    expect(screen.getByText("Export is current.")).toBeInTheDocument();

    rerender(
      <PersonalizationPanel
        personalization={payload({
          audit: {
            state: "stale",
            stage_state: "stale",
            available: true,
            unavailable_reason: null,
            findings: [],
          },
          export: { state: "stale" },
        })}
        onEvidence={vi.fn()}
      />,
    );
    expect(screen.getByText("Optional audit is stale.")).toBeInTheDocument();
    expect(screen.getByText("Re-export to publish the current personalization evidence.")).toBeInTheDocument();
  });
});
