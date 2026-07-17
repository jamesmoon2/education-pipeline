import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import InfoTip from "./InfoTip";

describe("InfoTip", () => {
  it("is hidden until focused and exposes the text as a described tooltip", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Brief" text="What the course should cover." />);
    const trigger = screen.getByRole("button", { name: "About Brief" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.tab();
    expect(trigger).toHaveFocus();
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("What the course should cover.");
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);

    await user.tab();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("dismisses on Escape and toggles on click", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Brief" text="Help." />);
    const trigger = screen.getByRole("button", { name: "About Brief" });

    await user.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
