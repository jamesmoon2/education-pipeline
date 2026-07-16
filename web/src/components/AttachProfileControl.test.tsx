import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AttachProfileControl from "./AttachProfileControl";

vi.mock("../api/client", () => ({ attachProfile: vi.fn() }));
import { attachProfile } from "../api/client";

describe("AttachProfileControl", () => {
  it("uses profile summary objects while attaching by id", async () => {
    vi.mocked(attachProfile).mockResolvedValue({ profile_id: "p1", topic_id: "t1", snapshot_path: "inputs/profile.toml" });
    render(<AttachProfileControl topicId="t1" profiles={[{ id: "p1", attached_topic_count: 2 }]} onDone={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("Attach profile to t1"), "p1");
    expect(screen.getByRole("option", { name: "p1 (2 topics)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Attach" }));
    expect(attachProfile).toHaveBeenCalledWith("t1", "p1");
  });
});
