import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SensitivityBadge from "./SensitivityBadge";

describe("SensitivityBadge", () => {
  it("labels a server-provided sensitivity tier accessibly", () => {
    render(<SensitivityBadge tier="high" />);
    expect(screen.getByText("High sensitivity")).toHaveClass("sensitivity-high");
  });

  it("renders nothing when the server has no tier for a field", () => {
    const { container } = render(<SensitivityBadge tier={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
