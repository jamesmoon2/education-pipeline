import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ExportControls from "./ExportControls";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    postExport: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
  };
});

import { ApiRequestError, downloadExport, downloadFinal, postExport } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("ExportControls", () => {
  it("exports the selected format", async () => {
    vi.mocked(postExport).mockResolvedValue({
      topic_id: "t",
      format: "markdown",
      export_path: "final/guide.bundle.md",
    });
    render(<ExportControls topicId="t" />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "markdown");
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(postExport).toHaveBeenCalledWith("t", "markdown");
    expect(await screen.findByText("Exported markdown.")).toBeInTheDocument();
  });

  it("retries export with overwrite after a confirmed 409", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postExport)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "html export already exists"))
      .mockResolvedValueOnce({ topic_id: "t", format: "html", export_path: "final/guide.html" });
    render(<ExportControls topicId="t" />);
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(postExport).toHaveBeenNthCalledWith(1, "t", "html");
    expect(postExport).toHaveBeenNthCalledWith(2, "t", "html", true);
  });

  it("triggers downloads and surfaces a missing-export 404 inline", async () => {
    vi.mocked(downloadFinal).mockResolvedValue(undefined);
    vi.mocked(downloadExport).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no markdown export produced for topic 't'"),
    );
    render(<ExportControls topicId="t" />);
    await userEvent.click(screen.getByRole("button", { name: "Download final guide" }));
    expect(downloadFinal).toHaveBeenCalledWith("t");
    await userEvent.click(screen.getByRole("button", { name: "Download markdown export" }));
    expect(downloadExport).toHaveBeenCalledWith("t", "markdown");
    expect(
      await screen.findByText(/no markdown export produced/),
    ).toBeInTheDocument();
  });
});
