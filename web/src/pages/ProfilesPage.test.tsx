import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ProfilesPage from "./ProfilesPage";

vi.mock("../api/client", () => ({
  getProfiles: vi.fn(),
  getConfigProviders: vi.fn(),
  getConfigCatalog: vi.fn(),
  draftProfile: vi.fn(),
  importProfile: vi.fn(),
}));
import { getConfigCatalog, getConfigProviders, getProfiles } from "../api/client";

describe("ProfilesPage", () => {
  it("lists structured summaries with attachment counts and editor links", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [{ id: "cohort-a", attached_topic_count: 3 }] });
    vi.mocked(getConfigProviders).mockResolvedValue({ providers: [] });
    vi.mocked(getConfigCatalog).mockResolvedValue({ providers: [], presets: [] });
    render(<MemoryRouter><ProfilesPage /></MemoryRouter>);
    expect(await screen.findByRole("link", { name: "cohort-a" })).toHaveAttribute("href", "/profiles/cohort-a");
    expect(screen.getByText("3 attached topics")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New profile" })).toHaveAttribute("href", "/profiles/new");
    expect(
      screen.getByRole("heading", { name: "Draft a profile from a description" }),
    ).toBeInTheDocument();
  });
});
