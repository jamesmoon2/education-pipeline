import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { metadataNumber } from "../api/types";
import type { LearnerProfile, ProfileDetail } from "../api/types";
import ProfileEditorPage from "./ProfileEditorPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ApiRequestError: actual.ApiRequestError, getProfile: vi.fn(), putProfile: vi.fn(), duplicateProfile: vi.fn(), previewProfile: vi.fn() };
});
import { ApiRequestError, duplicateProfile, getProfile, previewProfile, putProfile } from "../api/client";

const profile: LearnerProfile = {
  schema_version: 1, id: "p1", target_learner: "Synthetic learner", adjacent_domains: [], learning_goals: [], preferred_examples: [], examples_to_avoid: [], assessment_styles: [], accessibility_constraints: [], sensitive_areas: [],
  learning_preferences: { preferred_modalities: [], preferred_visual_aids: [], practice_style: [], common_sticking_points: [], attention_constraints: [], review_style: [] }, localization: {}, privacy: { private_by_default: true, include_in_published_output: false }, metadata: {},
};
const detail: ProfileDetail = { id: "p1", parsed: profile, sensitivity: { target_learner: "high" }, content_sha256: "sha-1", warnings: [], attached_topic_count: 1 };

function renderPage(path: string, initialEntries = [path]) {
  return render(<MemoryRouter initialEntries={initialEntries} initialIndex={initialEntries.length - 1}><Routes><Route path="/profiles/new" element={<ProfileEditorPage />} /><Route path="/profiles/:profileId" element={<ProfileEditorPage />} /><Route path="/profiles" element={<p>Profiles home</p>} /></Routes></MemoryRouter>);
}

describe("ProfileEditorPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.resetAllMocks();
    vi.mocked(previewProfile).mockResolvedValue({ parsed: profile, prompt_context: "Preview", publishable_summary: null, sensitivity: {}, warnings: [] });
  });

  it("creates a profile with a null base hash", async () => {
    vi.mocked(putProfile).mockResolvedValue({ ...detail, content_sha256: "sha-created" });
    renderPage("/profiles/new");
    await userEvent.type(screen.getByLabelText("Profile id"), "new-profile");
    await userEvent.type(screen.getByLabelText("Target learner"), "Synthetic cohort");
    await userEvent.click(screen.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(putProfile).toHaveBeenCalledWith("new-profile", expect.objectContaining({ id: "new-profile", target_learner: "Synthetic cohort" }), null));
  });

  it("loads, edits, saves, and duplicates an existing profile", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    vi.mocked(putProfile).mockResolvedValue({ ...detail, content_sha256: "sha-2" });
    vi.mocked(duplicateProfile).mockResolvedValue({ ...detail, id: "p2", parsed: { ...profile, id: "p2" } });
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.clear(screen.getByLabelText("Target learner"));
    await userEvent.type(screen.getByLabelText("Target learner"), "Edited learner");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(putProfile).toHaveBeenCalledWith("p1", expect.objectContaining({ target_learner: "Edited learner" }), "sha-1"));
    await userEvent.type(screen.getByLabelText("Duplicate as"), "p2");
    await userEvent.click(screen.getByRole("button", { name: "Duplicate profile" }));
    await waitFor(() => expect(duplicateProfile).toHaveBeenCalledWith("p1", "p2"));
  });

  it("guards dirty navigation with beforeunload", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.type(screen.getByLabelText("Target learner"), " changed");
    const event = new Event("beforeunload", { cancelable: true });
    fireEvent(window, event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("keeps unsaved input after a 409 and reloads only when chosen", async () => {
    vi.mocked(getProfile).mockResolvedValueOnce(detail).mockResolvedValueOnce({ ...detail, content_sha256: "sha-current", parsed: { ...profile, target_learner: "Disk value" } });
    vi.mocked(putProfile).mockRejectedValue(new ApiRequestError(409, "stale_content", "reload profiles", { current_sha256: "sha-current" }));
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.clear(screen.getByLabelText("Target learner"));
    await userEvent.type(screen.getByLabelText("Target learner"), "Unsaved value");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const conflict = await screen.findByRole("alert");
    expect(conflict).toHaveTextContent(/changed on disk/i);
    expect(conflict).toHaveFocus();
    expect(screen.getByLabelText("Target learner")).toHaveValue("Unsaved value");
    const reload = screen.getByRole("button", { name: "Reload current profile" });
    expect(reload).toHaveAttribute("aria-describedby", conflict.id);
    await userEvent.click(reload);
    expect(await screen.findByDisplayValue("Disk value")).toBeInTheDocument();
  });

  it("announces and focuses ordinary save errors", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    vi.mocked(putProfile).mockRejectedValue(new Error("Server refused save"));
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.type(screen.getByLabelText("Target learner"), " changed");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Server refused save");
    expect(alert).toHaveFocus();
  });

  it("announces save success as status", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    vi.mocked(putProfile).mockResolvedValue({ ...detail, content_sha256: "sha-2" });
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.type(screen.getByLabelText("Target learner"), " changed");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const success = await screen.findByText("Changes saved.");
    expect(success).toHaveAttribute("role", "status");
  });

  it("confirms before dirty duplicate navigation", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    vi.mocked(duplicateProfile).mockResolvedValue({ ...detail, id: "p2", parsed: { ...profile, id: "p2" } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.type(screen.getByLabelText("Target learner"), " changed");
    await userEvent.type(screen.getByLabelText("Duplicate as"), "p2");
    await userEvent.click(screen.getByRole("button", { name: "Duplicate profile" }));
    expect(confirm).toHaveBeenCalledWith("Discard unsaved profile changes?");
    expect(duplicateProfile).not.toHaveBeenCalled();
  });

  it("guards browser Back navigation while dirty", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.type(screen.getByLabelText("Target learner"), " changed");
    fireEvent.popState(window);
    expect(confirm).toHaveBeenCalledWith("Discard unsaved profile changes?");
    expect(go).toHaveBeenCalledWith(1);
  });

  it("blocks save and shows field validation for an incomplete numeric draft", async () => {
    vi.mocked(getProfile).mockResolvedValue({ ...detail, parsed: { ...profile, metadata: { count: 1 } } });
    renderPage("/profiles/p1");
    await screen.findByDisplayValue("Synthetic learner");
    fireEvent.change(screen.getByLabelText("Metadata value count"), { target: { value: "-" } });

    expect(screen.getByLabelText("Metadata value count")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter a valid integer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(putProfile).not.toHaveBeenCalled();
  });

  it("restores the dirty editor route and draft after declining browser Back", async () => {
    vi.mocked(getProfile).mockResolvedValue(detail);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    window.history.replaceState({}, "", "/profiles");
    window.history.pushState({}, "", "/profiles/p1");
    render(<BrowserRouter><Routes><Route path="/profiles/:profileId" element={<ProfileEditorPage />} /><Route path="/profiles" element={<p>Profiles home</p>} /></Routes></BrowserRouter>);
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.clear(screen.getByLabelText("Target learner"));
    await userEvent.type(screen.getByLabelText("Target learner"), "Edited draft survives");

    window.history.back();

    await waitFor(() => expect(confirm).toHaveBeenCalledWith("Discard unsaved profile changes?"));
    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 50)); });
    expect(window.location.pathname).toBe("/profiles/p1");
    expect(await screen.findByLabelText("Target learner")).toHaveValue("Edited draft survives");
  });

  it("restores a new-profile route and draft after declining browser Back", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    let restoreEvent: Event | null = null;
    const dispatch = window.dispatchEvent.bind(window);
    vi.spyOn(window, "dispatchEvent").mockImplementation((event) => {
      if (event.type === "popstate" && window.location.pathname === "/profiles/new") {
        restoreEvent = event;
        return true;
      }
      return dispatch(event);
    });
    window.history.replaceState({}, "", "/profiles");
    window.history.pushState({}, "", "/profiles/new");
    render(<BrowserRouter><Routes><Route path="/profiles/new" element={<ProfileEditorPage />} /><Route path="/profiles" element={<p>Profiles home</p>} /></Routes></BrowserRouter>);
    await userEvent.type(screen.getByLabelText("Profile id"), "new-draft");
    await userEvent.type(screen.getByLabelText("Target learner"), "New draft survives");

    window.history.back();

    await waitFor(() => expect(confirm).toHaveBeenCalledWith("Discard unsaved profile changes?"));
    expect(await screen.findByText("Profiles home")).toBeInTheDocument();
    await waitFor(() => expect(restoreEvent).not.toBeNull());
    await act(async () => { dispatch(new PopStateEvent("popstate", { state: window.history.state })); });
    expect(await screen.findByLabelText("Profile id")).toHaveValue("new-draft");
    expect(screen.getByLabelText("Target learner")).toHaveValue("New draft survives");
    expect(window.location.pathname).toBe("/profiles/new");
  });

  it("retains an existing-profile draft when reload fails after declined Back", async () => {
    vi.mocked(getProfile).mockResolvedValueOnce(detail).mockRejectedValue(new Error("reload unavailable"));
    vi.spyOn(window, "confirm").mockReturnValue(false);
    let restoreEvent: Event | null = null;
    const dispatch = window.dispatchEvent.bind(window);
    vi.spyOn(window, "dispatchEvent").mockImplementation((event) => {
      if (event.type === "popstate" && window.location.pathname === "/profiles/p1") {
        restoreEvent = event;
        return true;
      }
      return dispatch(event);
    });
    window.history.replaceState({}, "", "/profiles");
    window.history.pushState({}, "", "/profiles/p1");
    const routes = <Routes><Route path="/profiles/:profileId" element={<ProfileEditorPage />} /><Route path="/profiles" element={<p>Profiles home</p>} /></Routes>;
    const view = render(<BrowserRouter>{routes}</BrowserRouter>);
    await screen.findByDisplayValue("Synthetic learner");
    await userEvent.clear(screen.getByLabelText("Target learner"));
    await userEvent.type(screen.getByLabelText("Target learner"), "Draft survives failed reload");

    window.history.back();
    expect(await screen.findByText("Profiles home")).toBeInTheDocument();
    await waitFor(() => expect(restoreEvent).not.toBeNull());
    await act(async () => { dispatch(new PopStateEvent("popstate", { state: window.history.state })); });

    expect(await screen.findByRole("alert")).toHaveTextContent("reload unavailable");
    expect(screen.getByLabelText("Target learner")).toHaveValue("Draft survives failed reload");

    view.unmount();
    render(<BrowserRouter>{routes}</BrowserRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("reload unavailable");
    expect(screen.getByLabelText("Target learner")).toHaveValue("Draft survives failed reload");
  });

  it("purges a retained failed-restoration draft after confirmed discard", async () => {
    const discardProfile = { ...profile, id: "p-discard", target_learner: "Pristine server learner" };
    const discardDetail = { ...detail, id: "p-discard", parsed: discardProfile };
    vi.mocked(getProfile)
      .mockResolvedValueOnce(discardDetail)
      .mockRejectedValueOnce(new Error("reload unavailable"))
      .mockResolvedValue(discardDetail);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    let restoreEvent: Event | null = null;
    const dispatch = window.dispatchEvent.bind(window);
    vi.spyOn(window, "dispatchEvent").mockImplementation((event) => {
      if (event.type === "popstate" && window.location.pathname === "/profiles/p-discard") {
        restoreEvent = event;
        return true;
      }
      return dispatch(event);
    });
    window.history.replaceState({}, "", "/profiles");
    window.history.pushState({}, "", "/profiles/p-discard");
    const routes = <Routes><Route path="/profiles/:profileId" element={<ProfileEditorPage />} /><Route path="/profiles" element={<p>Profiles home</p>} /></Routes>;
    const view = render(<BrowserRouter>{routes}</BrowserRouter>);
    await screen.findByDisplayValue("Pristine server learner");
    await userEvent.clear(screen.getByLabelText("Target learner"));
    await userEvent.type(screen.getByLabelText("Target learner"), "Discard this retained draft");

    window.history.back();
    expect(await screen.findByText("Profiles home")).toBeInTheDocument();
    await waitFor(() => expect(restoreEvent).not.toBeNull());
    await act(async () => { dispatch(new PopStateEvent("popstate", { state: window.history.state })); });
    expect(await screen.findByRole("alert")).toHaveTextContent("reload unavailable");
    expect(screen.getByLabelText("Target learner")).toHaveValue("Discard this retained draft");

    await userEvent.click(screen.getByRole("link", { name: "← Profiles" }));
    expect(confirm).toHaveBeenLastCalledWith("Discard unsaved profile changes?");
    expect(await screen.findByText("Profiles home")).toBeInTheDocument();

    view.unmount();
    window.history.pushState({}, "", "/profiles/p-discard");
    render(<BrowserRouter>{routes}</BrowserRouter>);
    expect(await screen.findByLabelText("Target learner")).toHaveValue("Pristine server learner");
  });
});
