import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ModuleRepairControl from "./ModuleRepairControl";

vi.mock("../api/client", () => ({
  getRepairModules: vi.fn(),
  postAdvance: vi.fn(),
}));

import { getRepairModules, postAdvance } from "../api/client";

const modulesPayload = {
  topic_id: "t",
  modules: [
    { id: "loop-basics", title: "How loops behave", open_findings: 2 },
    { id: "intervention-practice", title: "Intervene", open_findings: 0 },
  ],
  repair_scope: null,
};

describe("ModuleRepairControl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists the draft's modules with open finding counts", async () => {
    vi.mocked(getRepairModules).mockResolvedValue(modulesPayload);

    render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

    expect(
      await screen.findByRole("option", { name: /How loops behave \(2 open findings\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Intervene \(0 open findings\)/ }),
    ).toBeInTheDocument();
  });

  it("prepares a scoped prompt for the chosen module", async () => {
    vi.mocked(getRepairModules).mockResolvedValue(modulesPayload);
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: {} as never,
    });
    const onPrepared = vi.fn();

    render(<ModuleRepairControl topicId="t" onPrepared={onPrepared} />);

    await userEvent.selectOptions(
      await screen.findByLabelText("Module"),
      "loop-basics",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Regenerate this module" }),
    );

    expect(postAdvance).toHaveBeenCalledWith("t", { repairModule: "loop-basics" });
    expect(onPrepared).toHaveBeenCalled();
  });

  it("renders nothing while the module list is unavailable", async () => {
    vi.mocked(getRepairModules).mockRejectedValue(new Error("no approved draft"));

    const { container } = render(
      <ModuleRepairControl topicId="t" onPrepared={() => {}} />,
    );

    await vi.waitFor(() => expect(getRepairModules).toHaveBeenCalled());
    expect(container.querySelector(".module-repair")).toBeNull();
  });
});
