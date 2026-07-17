import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { BlueprintsPayload } from "../api/types";
import BlueprintPicker from "./BlueprintPicker";

const payload: BlueprintsPayload = {
  blueprints: [
    {
      id: "conceptual-foundations",
      title: "Conceptual foundations",
      summary: "Builds a mental model of core concepts and how they relate.",
      when_to_use: "Choose when the goal is understanding ideas.",
      required_interactions: ["knowledge_check", "reflection"],
      default_difficulty: "introductory",
    },
    {
      id: "exam-preparation",
      title: "Exam preparation",
      summary: "Prepares for a specific assessment with format-matched practice.",
      when_to_use: "Choose when success is measured by an exam.",
      required_interactions: ["knowledge_check", "worked_reveal"],
      default_difficulty: "intermediate",
    },
  ],
  recommendation: {
    id: "exam-preparation",
    rationale: "Recommended Exam preparation because the topic mentions 'exam'.",
  },
  topic_blueprint: null,
};

describe("BlueprintPicker", () => {
  it("renders every blueprint with guidance and marks the recommendation", () => {
    render(
      <BlueprintPicker payload={payload} value="exam-preparation" onChange={() => {}} />,
    );

    expect(screen.getByRole("radio", { name: /Conceptual foundations/ })).toBeInTheDocument();
    const recommended = screen.getByRole("radio", { name: /Exam preparation/ });
    expect(recommended).toBeChecked();
    expect(screen.getByText(/Recommended Exam preparation because/)).toBeInTheDocument();
    expect(screen.getByText("Choose when success is measured by an exam.")).toBeInTheDocument();
    expect(screen.getByText(/Recommended$/)).toBeInTheDocument();
  });

  it("overriding is one click", async () => {
    const onChange = vi.fn();
    render(
      <BlueprintPicker payload={payload} value="exam-preparation" onChange={onChange} />,
    );

    await userEvent.click(screen.getByRole("radio", { name: /Conceptual foundations/ }));

    expect(onChange).toHaveBeenCalledWith("conceptual-foundations");
  });
});
