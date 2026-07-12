import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResponseEditor from "./ResponseEditor";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    putResponse: vi.fn(),
    postPreview: vi.fn(),
    postGuidePreview: vi.fn(),
    getStageContent: vi.fn(),
  };
});

import {
  ApiRequestError,
  getStageContent,
  postPreview,
  putResponse,
} from "../api/client";

function renderEditor(overrides: Partial<Parameters<typeof ResponseEditor>[0]> = {}) {
  const props = {
    topicId: "t",
    stage: "repair",
    content: "original body",
    contentSha256: "sha-1",
    contentType: "text/markdown" as const,
    onSaved: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<ResponseEditor {...props} />);
  return props;
}

describe("ResponseEditor", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("saves the buffer with the remembered base hash", async () => {
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      response_path: "responses/repair.response.md",
      response_sha256: "sha-2",
    });
    const props = renderEditor();

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "edited body");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(putResponse).toHaveBeenCalledWith("t", "repair", "edited body", "sha-1");
    await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  });

  it("keeps the buffer and offers reload on a stale 409", async () => {
    vi.mocked(putResponse).mockRejectedValue(
      new ApiRequestError(409, "stale_content", "the repair response changed on disk"),
    );
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      prompt: null,
      response: "external content",
      approved: null,
      response_sha256: "sha-external",
      content_type: "text/markdown",
    });
    const props = renderEditor();

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "my edit");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    // envelope message shown, buffer intact, editor still open
    expect(await screen.findByText(/changed on disk/)).toBeInTheDocument();
    expect(textarea).toHaveValue("my edit");
    expect(props.onSaved).not.toHaveBeenCalled();

    // reload shows the now-current content beside the buffer …
    await userEvent.click(
      screen.getByRole("button", { name: "Reload current content" }),
    );
    expect(await screen.findByText("external content")).toBeInTheDocument();
    expect(textarea).toHaveValue("my edit");

    // … and the next save uses the adopted hash
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      response_path: "responses/repair.response.md",
      response_sha256: "sha-3",
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(putResponse).toHaveBeenLastCalledWith("t", "repair", "my edit", "sha-external");
  });

  it("populates the preview on toggle and debounces while typing", async () => {
    vi.mocked(postPreview).mockResolvedValue({ html: "<h1>Rendered</h1>" });
    renderEditor();
    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(postPreview).toHaveBeenCalledWith("original body");
    // Flush the immediate toggle fetch's promise resolution (setPreviewHtml)
    // inside act before moving on, so it never settles unobserved later.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Rendered")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Edit response for repair"), {
      target: { value: "# typed" },
    });
    expect(postPreview).not.toHaveBeenCalledWith("# typed");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(postPreview).toHaveBeenCalledWith("# typed");
  });

  it("shows JSON syntax feedback without replacing the guide buffer", async () => {
    const { postGuidePreview } = await import("../api/client");
    renderEditor({
      content: '{"schema_version":"1.0"}',
      contentType: "application/vnd.education-pipeline.guide+json;version=1.0",
    });

    const textarea = screen.getByLabelText("Edit response for repair");
    fireEvent.change(textarea, { target: { value: "{" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("JSON syntax error");
    expect(textarea).toHaveValue("{");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(postGuidePreview).not.toHaveBeenCalled();
  });

  it("renders executable guide previews only in an opaque sandboxed iframe", async () => {
    const { postGuidePreview } = await import("../api/client");
    vi.mocked(postGuidePreview).mockResolvedValue({
      html: "<!doctype html><script>document.body.dataset.ready='yes'</script>",
      content_sha256: "abc",
      validation: { blocking: 0, errors: 0, warnings: 0 },
    });
    renderEditor({
      content: '{"schema_version":"1.0"}',
      contentType: "application/vnd.education-pipeline.guide+json;version=1.0",
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const frame = await screen.findByTitle("Interactive guide preview");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).not.toHaveAttribute("sandbox", expect.stringContaining("allow-same-origin"));
    expect(frame).toHaveAttribute("srcdoc", expect.stringContaining("<script>"));
    expect(document.querySelector(".preview.content")).toBeNull();
  });

  it("confirms before discarding a dirty buffer on cancel", async () => {
    const props = renderEditor();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.type(textarea, " plus more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("cancels without confirm when the buffer is clean", async () => {
    const props = renderEditor();
    const confirmSpy = vi.spyOn(window, "confirm");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(props.onClose).toHaveBeenCalled();
  });
});
