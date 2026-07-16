import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { metadataNumber } from "../api/types";
import type { LearnerProfile, ProfilePreview } from "../api/types";
import ProfilePrivacyPreview from "./ProfilePrivacyPreview";

vi.mock("../api/client", () => ({ previewProfile: vi.fn() }));
import { previewProfile } from "../api/client";

const profile = {
  schema_version: 1, id: "p", target_learner: "Synthetic learner", adjacent_domains: [], learning_goals: [],
  preferred_examples: [], examples_to_avoid: [], assessment_styles: [], accessibility_constraints: [], sensitive_areas: [],
  learning_preferences: { preferred_modalities: [], preferred_visual_aids: [], practice_style: [], common_sticking_points: [], attention_constraints: [], review_style: [] },
  localization: {}, privacy: { private_by_default: true, include_in_published_output: false }, metadata: {},
} satisfies LearnerProfile;

const preview: ProfilePreview = {
  parsed: profile,
  prompt_context: "# Learner Profile Context\n- Target learner: Synthetic learner\n",
  publishable_summary: null,
  sensitivity: { target_learner: "high" },
  warnings: [{ code: "privacy.summary_contains_private_value", field_path: "target_learner", fingerprint: "abc123def456" }],
};

describe("ProfilePrivacyPreview", () => {
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

  it("debounces requests, shows loading, and renders the server output and safe warning fields", async () => {
    vi.useFakeTimers();
    let resolve!: (value: ProfilePreview) => void;
    vi.mocked(previewProfile).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ProfilePrivacyPreview profile={profile} debounceMs={300} />);

    expect(previewProfile).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(previewProfile).toHaveBeenCalledWith(profile);
    expect(screen.getByText("Rendering privacy preview…")).toBeInTheDocument();
    await act(async () => { resolve(preview); });

    expect(screen.getByText(/Learner Profile Context/)).toBeInTheDocument();
    expect(screen.getByText("Not included in published output.")).toBeInTheDocument();
    expect(screen.getByText(/privacy\.summary_contains_private_value/)).toBeInTheDocument();
    expect(screen.getByText(/target_learner/)).toBeInTheDocument();
    expect(screen.getByText(/abc123def456/)).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Privacy preview" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "Private prompt context" })).toHaveAttribute("tabindex", "0");
  });

  it("clears a successful preview when the draft changes and the next preview fails", async () => {
    vi.useFakeTimers();
    vi.mocked(previewProfile).mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error("invalid draft"));
    const view = render(<ProfilePrivacyPreview profile={profile} debounceMs={10} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getByText(/Learner Profile Context/)).toBeInTheDocument();

    view.rerender(<ProfilePrivacyPreview profile={{ ...profile, target_learner: "Changed" }} debounceMs={10} />);
    expect(screen.queryByText(/Learner Profile Context/)).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getByRole("alert")).toHaveTextContent("invalid draft");
    expect(screen.queryByText(/Learner Profile Context/)).not.toBeInTheDocument();
  });

  it("shows a stable not-previewable state for an invalid numeric draft", async () => {
    vi.useFakeTimers();
    vi.mocked(previewProfile).mockImplementation(() => { throw new Error("Invalid integer metadata value."); });
    render(<ProfilePrivacyPreview profile={{ ...profile, metadata: { count: metadataNumber("-", "integer") } }} debounceMs={10} />);

    await act(async () => { await vi.advanceTimersByTimeAsync(10); });

    expect(previewProfile).not.toHaveBeenCalled();
    expect(screen.queryByText("Rendering privacy preview…")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Fix invalid metadata numbers to preview");
  });
});
