import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import JobLogView from "./JobLogView";

vi.mock("../api/client", () => ({
  getJobLog: vi.fn(),
}));

import { getJobLog } from "../api/client";

describe("JobLogView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("accumulates chunks using the returned offset", async () => {
    vi.mocked(getJobLog)
      .mockResolvedValueOnce({ data: "hello ", offset: 6 })
      .mockResolvedValueOnce({ data: "world", offset: 11 })
      .mockResolvedValue({ data: "", offset: 11 });

    render(<JobLogView jobId="j1" active={true} />);

    expect(await screen.findByText(/hello/)).toBeInTheDocument();
    expect(await screen.findByText(/hello world/)).toBeInTheDocument();
    // second call must pass the cursor from the first response
    expect(vi.mocked(getJobLog).mock.calls[1]).toEqual(["j1", 6]);
  });

  it("fetches once when the job is not active", async () => {
    vi.mocked(getJobLog).mockResolvedValue({ data: "done output", offset: 11 });
    render(<JobLogView jobId="j2" active={false} />);
    expect(await screen.findByText(/done output/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(vi.mocked(getJobLog)).toHaveBeenCalledTimes(1);
  });
});
