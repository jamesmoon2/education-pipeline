import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { metadataNumber } from "../api/types";
import type { LearnerProfile } from "../api/types";
import ProfileForm from "./ProfileForm";

const profile: LearnerProfile = {
  schema_version: 1,
  id: "learner-a",
  target_learner: "Synthetic learner",
  prior_education: "College",
  prior_experience: "Some practice",
  professional_experience: "Analyst",
  current_skill_level: "Beginning",
  adjacent_domains: ["Biology"],
  learning_goals: ["Model feedback"],
  preferred_examples: ["Ecosystems"],
  examples_to_avoid: ["Personal finance"],
  math_comfort: "Algebra",
  reading_level: "Technical",
  pace: "Measured",
  desired_depth: "Deep",
  time_budget: "4 hours",
  assessment_styles: ["Reflection"],
  accessibility_constraints: ["Captions"],
  tone_preference: "Direct",
  sensitive_areas: ["Health"],
  learning_preferences: {
    preferred_modalities: ["visual"],
    explanation_style: "concrete first",
    preferred_visual_aids: ["causal loops"],
    diagram_frequency: "often",
    interaction_style: "guided",
    practice_style: ["scenarios"],
    feedback_style: "specific",
    worked_example_preference: "faded steps",
    common_sticking_points: ["delays"],
    attention_constraints: ["short sections"],
    review_style: ["retrieval"],
  },
  localization: {
    jurisdiction: "US",
    locale: "en-US",
    units: "metric",
    language_register: "plain",
  },
  privacy: {
    private_by_default: true,
    include_in_published_output: false,
    publishable_summary: "A general learner summary",
  },
  metadata: {
    cohort: { year: 2026, labels: ["pilot", { reviewed: true }] },
    score: 2.5,
  },
};

describe("ProfileForm", () => {
  it("renders all six sections and every schema leaf", () => {
    render(<ProfileForm value={profile} onChange={vi.fn()} sensitivity={{ target_learner: "high", "metadata.*": "high" }} />);

    for (const heading of ["Identity", "Background", "Learning plan", "Learning preferences", "Localization", "Privacy and metadata"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    for (const label of [
      "Schema version", "Profile id", "Target learner", "Prior education", "Prior experience", "Professional experience",
      "Current skill level", "Adjacent domains", "Learning goals", "Preferred examples", "Examples to avoid",
      "Math comfort", "Reading level", "Pace", "Desired depth", "Time budget", "Assessment styles",
      "Accessibility constraints", "Tone preference", "Sensitive areas", "Preferred modalities", "Explanation style",
      "Preferred visual aids", "Diagram frequency", "Interaction style", "Practice style", "Feedback style",
      "Worked example preference", "Common sticking points", "Attention constraints", "Review style", "Jurisdiction",
      "Locale", "Units", "Language register", "Private by default", "Include summary in published output",
      "Publishable summary",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText("High sensitivity").length).toBeGreaterThan(0);
  });

  it("edits arrays, nested preferences, and recursive metadata without losing types", async () => {
    const onChange = vi.fn();
    function Harness() {
      const [value, setValue] = useState(profile);
      return <ProfileForm value={value} onChange={(next) => { onChange(next); setValue(next); }} sensitivity={{ "metadata.*": "high" }} />;
    }
    render(<Harness />);

    fireEvent.change(screen.getByLabelText("Learning goals"), { target: { value: "First goal\nSecond goal" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ learning_goals: ["First goal", "Second goal"] }));

    await userEvent.clear(screen.getByLabelText("Explanation style"));
    await userEvent.type(screen.getByLabelText("Explanation style"), "analogy first");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      learning_preferences: expect.objectContaining({ explanation_style: "analogy first" }),
    }));

    await userEvent.clear(screen.getByLabelText("Metadata value cohort.year"));
    await userEvent.type(screen.getByLabelText("Metadata value cohort.year"), "2027");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      metadata: expect.objectContaining({ cohort: expect.objectContaining({ year: expect.objectContaining({ text: "2027", kind: "integer" }) }) }),
    }));
    expect(screen.getByLabelText("Metadata value cohort.labels.1.reviewed")).toHaveAttribute("type", "checkbox");
  });

  it("switches numeric metadata kinds and preserves exact numeric input", async () => {
    let latest = profile;
    function Harness() {
      const [value, setValue] = useState(profile);
      return <ProfileForm value={value} onChange={(next) => { latest = next; setValue(next); }} sensitivity={{}} />;
    }
    render(<Harness />);

    await userEvent.selectOptions(screen.getByLabelText("Metadata type cohort.year"), "float");
    fireEvent.change(screen.getByLabelText("Metadata value cohort.year"), { target: { value: "-2.5e+3" } });
    expect(latest.metadata.cohort).toEqual(expect.objectContaining({ year: expect.objectContaining({ text: "-2.5e+3", kind: "float" }) }));
    await userEvent.selectOptions(screen.getByLabelText("Metadata type cohort.year"), "integer");
    fireEvent.change(screen.getByLabelText("Metadata value cohort.year"), { target: { value: "9223372036854775807" } });
    expect(latest.metadata.cohort).toEqual(expect.objectContaining({ year: expect.objectContaining({ text: "9223372036854775807", kind: "integer" }) }));
  });

  it("gives repeated metadata actions contextual accessible names", () => {
    render(<ProfileForm value={profile} onChange={vi.fn()} sensitivity={{}} />);
    expect(screen.getByRole("button", { name: "Remove metadata cohort.labels.1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add list item to cohort.labels" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add metadata field to cohort" })).toBeInTheDocument();
  });

  it("uses collision-free validation ids for distinct metadata paths", () => {
    render(<ProfileForm value={{
      ...profile,
      metadata: {
        a: { b: metadataNumber("-", "integer") },
        "a-b": metadataNumber("-", "integer"),
      },
    }} onChange={vi.fn()} sensitivity={{}} />);

    const dottedId = screen.getByLabelText("Metadata value a.b").getAttribute("aria-describedby");
    const dashedId = screen.getByLabelText("Metadata value a-b").getAttribute("aria-describedby");
    expect(dottedId).toBeTruthy();
    expect(dashedId).toBeTruthy();
    expect(dottedId).not.toBe(dashedId);
    expect(document.getElementById(dottedId!)).toHaveTextContent("Enter a valid integer.");
    expect(document.getElementById(dashedId!)).toHaveTextContent("Enter a valid integer.");
  });

  it("distinguishes literal dotted keys from nested metadata paths in validation ids", () => {
    render(<ProfileForm value={{
      ...profile,
      metadata: {
        "a.b": metadataNumber("-", "integer"),
        a: { b: metadataNumber("-", "integer") },
      },
    }} onChange={vi.fn()} sensitivity={{}} />);

    const describedIds = screen.getAllByLabelText("Metadata value a.b").map((input) => input.getAttribute("aria-describedby"));
    expect(describedIds).toHaveLength(2);
    expect(describedIds[0]).toBeTruthy();
    expect(describedIds[1]).toBeTruthy();
    expect(describedIds[0]).not.toBe(describedIds[1]);
    expect(document.getElementById(describedIds[0]!)).toHaveTextContent("Enter a valid integer.");
    expect(document.getElementById(describedIds[1]!)).toHaveTextContent("Enter a valid integer.");
  });
});
