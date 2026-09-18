import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ModuleRepairControl from "./ModuleRepairControl";

vi.mock("../api/client", () => ({
  getRepairModules: vi.fn(),
  postAdvance: vi.fn(),
}));

import { getRepairModules, postAdvance } from "../api/client";

// Existing-test fixture: no sections on either module, so the section picker
// has nothing to preselect and every case here stays whole-module scoped.
// This is the minimal widening for the new payload keys (`sections`,
// `module_level_findings`); it keeps this fixture's original intent.
const modulesPayload = {
  topic_id: "t",
  modules: [
    {
      id: "loop-basics",
      title: "How loops behave",
      open_findings: 2,
      module_level_findings: 0,
      sections: [],
    },
    {
      id: "intervention-practice",
      title: "Intervene",
      open_findings: 0,
      module_level_findings: 0,
      sections: [],
    },
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

  describe("section scope", () => {
    it("shows a section select once a module is chosen, whole module first, defaulting there when no single section stands out", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 0,
            module_level_findings: 0,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 0 },
              { id: "practice", title: "Practice", open_findings: 0 },
            ],
          },
        ],
        repair_scope: null,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      expect(screen.queryByLabelText("Section")).not.toBeInTheDocument();

      await userEvent.selectOptions(
        await screen.findByLabelText("Module"),
        "loop-basics",
      );

      const sectionSelect = await screen.findByLabelText("Section");
      const options = within(sectionSelect).getAllByRole(
        "option",
      ) as HTMLOptionElement[];
      expect(options[0]).toHaveTextContent("Whole module");
      expect(options[0].value).toBe("");
      expect(options[1]).toHaveTextContent("Introduction (0 open findings)");
      expect(options[2]).toHaveTextContent("Practice (0 open findings)");
      expect((sectionSelect as HTMLSelectElement).value).toBe("");
      expect(
        screen.getByRole("button", { name: "Regenerate this module" }),
      ).toBeInTheDocument();
    });

    it("posts a section-scoped repair prompt when a section is chosen, naming the section in the success message", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 1,
            module_level_findings: 0,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 0 },
              { id: "practice", title: "Practice", open_findings: 1 },
            ],
          },
        ],
        repair_scope: null,
      });
      vi.mocked(postAdvance).mockResolvedValue({
        performed: "write_prompt",
        status: {} as never,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      await userEvent.selectOptions(
        await screen.findByLabelText("Module"),
        "loop-basics",
      );
      // Preselected onto "practice" (its sole open-findings section), so
      // switch explicitly to "intro" to prove a manual choice is honored too.
      await userEvent.selectOptions(
        await screen.findByLabelText("Section"),
        "intro",
      );

      expect(
        await screen.findByRole("button", { name: "Regenerate this section" }),
      ).toBeInTheDocument();

      await userEvent.click(
        screen.getByRole("button", { name: "Regenerate this section" }),
      );

      expect(postAdvance).toHaveBeenCalledWith("t", {
        repairModule: "loop-basics",
        repairSection: "intro",
      });
      expect(
        await screen.findByText(/loop-basics[\s\S]*intro|intro[\s\S]*loop-basics/),
      ).toBeInTheDocument();
    });

    it("preselects the sole section with open findings when the module has no module-level findings", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 1,
            module_level_findings: 0,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 0 },
              { id: "practice", title: "Practice", open_findings: 1 },
            ],
          },
        ],
        repair_scope: null,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      await userEvent.selectOptions(
        await screen.findByLabelText("Module"),
        "loop-basics",
      );

      const sectionSelect = await screen.findByLabelText("Section");
      expect((sectionSelect as HTMLSelectElement).value).toBe("practice");
      expect(
        screen.getByRole("button", { name: "Regenerate this section" }),
      ).toBeInTheDocument();
      expect(screen.queryByText(/module-level/i)).not.toBeInTheDocument();
    });

    it("falls back to whole module when several sections have open findings", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 2,
            module_level_findings: 0,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 1 },
              { id: "practice", title: "Practice", open_findings: 1 },
            ],
          },
        ],
        repair_scope: null,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      await userEvent.selectOptions(
        await screen.findByLabelText("Module"),
        "loop-basics",
      );

      const sectionSelect = await screen.findByLabelText("Section");
      expect((sectionSelect as HTMLSelectElement).value).toBe("");
      expect(
        screen.getByRole("button", { name: "Regenerate this module" }),
      ).toBeInTheDocument();
      expect(screen.queryByText(/module-level/i)).not.toBeInTheDocument();
    });

    it("defaults to whole module and explains that module-level findings force it, even with a single qualifying section", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 3,
            module_level_findings: 2,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 0 },
              { id: "practice", title: "Practice", open_findings: 1 },
            ],
          },
        ],
        repair_scope: null,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      await userEvent.selectOptions(
        await screen.findByLabelText("Module"),
        "loop-basics",
      );

      const sectionSelect = await screen.findByLabelText("Section");
      expect((sectionSelect as HTMLSelectElement).value).toBe("");
      expect(
        screen.getByRole("button", { name: "Regenerate this module" }),
      ).toBeInTheDocument();
      expect(screen.getByText(/module-level/i)).toBeInTheDocument();
    });

    it("resets the section selection to the new module's default when the module changes", async () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            open_findings: 1,
            module_level_findings: 0,
            sections: [
              { id: "intro", title: "Introduction", open_findings: 0 },
              { id: "practice", title: "Practice", open_findings: 1 },
            ],
          },
          {
            id: "intervention-practice",
            title: "Intervene",
            open_findings: 2,
            module_level_findings: 0,
            sections: [
              { id: "setup", title: "Setup", open_findings: 1 },
              { id: "wrapup", title: "Wrap up", open_findings: 1 },
            ],
          },
        ],
        repair_scope: null,
      });

      render(<ModuleRepairControl topicId="t" onPrepared={() => {}} />);

      const moduleSelect = await screen.findByLabelText("Module");
      await userEvent.selectOptions(moduleSelect, "loop-basics");
      expect((await screen.findByLabelText("Section") as HTMLSelectElement).value).toBe(
        "practice",
      );

      await userEvent.selectOptions(moduleSelect, "intervention-practice");

      const sectionSelect = await screen.findByLabelText("Section");
      // Two qualifying sections on the new module -> resets to whole module.
      expect((sectionSelect as HTMLSelectElement).value).toBe("");
      expect(
        screen.getByRole("button", { name: "Regenerate this module" }),
      ).toBeInTheDocument();
    });
  });
});
