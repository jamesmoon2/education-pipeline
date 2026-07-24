import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import StageContentView from "./StageContentView";

describe("StageContentView", () => {
  it("renders markdown as formatted prose by default", () => {
    render(
      <StageContentView
        label="prompt"
        text={"# Course Spec\n\nWrite **great** content."}
        contentType="text/markdown"
      />,
    );
    expect(screen.getByRole("heading", { name: "Course Spec" })).toBeInTheDocument();
    expect(screen.getByText("great")).toBeInTheDocument();
    expect(screen.queryByText("# Course Spec")).not.toBeInTheDocument();
  });

  it("offsets artifact headings below the stage page's h2", () => {
    render(
      <StageContentView
        label="prompt"
        text={"# Top\n\n#### Deep\n\n###### Deepest"}
        contentType="text/markdown"
      />,
    );
    // Source h1 renders as h3 (the page title is an h2); deep levels clamp at h6.
    expect(screen.getByRole("heading", { name: "Top", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deep", level: 6 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deepest", level: 6 })).toBeInTheDocument();
  });

  it("renders pipe tables as real tables", () => {
    render(
      <StageContentView
        label="response"
        text={"| Loop | Effect |\n|---|---|\n| Reinforcing | amplifies |"}
        contentType="text/markdown"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Loop" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "amplifies" })).toBeInTheDocument();
  });

  it("switches to the exact raw bytes and back", async () => {
    render(
      <StageContentView label="response" text={"# Raw Me"} contentType="text/markdown" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(screen.getByText("# Raw Me")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Raw Me" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(screen.getByRole("heading", { name: "Raw Me" })).toBeInTheDocument();
  });

  it("marks the active display mode for assistive tech", () => {
    render(<StageContentView label="response" text="body" contentType="text/markdown" />);
    const group = screen.getByRole("group", { name: "response display mode" });
    expect(within(group).getByRole("button", { name: "Rendered" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(group).getByRole("button", { name: "Raw" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("renders JSON content as a collapsible tree", () => {
    render(
      <StageContentView
        label="response"
        text={JSON.stringify({ modules: [{ id: "loop-basics" }], title: "T" })}
        contentType="application/vnd.education-pipeline.guide+json;version=1.0"
      />,
    );
    expect(screen.getByText("modules")).toBeInTheDocument();
    expect(screen.getByText("title:")).toBeInTheDocument();
    expect(screen.getByText('"loop-basics"')).toBeInTheDocument();
  });

  it("falls back to raw text when JSON content does not parse", () => {
    render(
      <StageContentView label="response" text="{not json" contentType="application/json" />,
    );
    expect(screen.getByText(/Not valid JSON/)).toBeInTheDocument();
    expect(screen.getByText("{not json")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("keeps the empty-artifact placeholder", () => {
    render(<StageContentView label="approved" text={null} contentType="text/markdown" />);
    expect(screen.getByText("(no approved yet)")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});
