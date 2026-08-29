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
    expect(await screen.findByText(/hello world/, undefined, { timeout: 3000 })).toBeInTheDocument();
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

describe("JobLogView tail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders only the last N non-empty lines", async () => {
    vi.mocked(getJobLog).mockResolvedValue({
      data: "line one\nline two\n\nline three\nline four",
      offset: 40,
    });
    render(<JobLogView jobId="j3" active={true} tail={3} />);
    const pre = await screen.findByText(/line four/);
    expect(pre).toHaveTextContent("line two line three line four");
    expect(pre).not.toHaveTextContent("line one");
  });

  it("renders the full log when tail is unset", async () => {
    vi.mocked(getJobLog).mockResolvedValue({
      data: "line one\nline two\nline three\nline four",
      offset: 40,
    });
    render(<JobLogView jobId="j4" active={true} />);
    const pre = await screen.findByText(/line four/);
    expect(pre).toHaveTextContent("line one line two line three line four");
  });

  it("keeps polling on the same 1s loop with a tail set", async () => {
    vi.mocked(getJobLog)
      .mockResolvedValueOnce({ data: "first\n", offset: 6 })
      .mockResolvedValueOnce({ data: "second\n", offset: 13 })
      .mockResolvedValue({ data: "", offset: 13 });
    render(<JobLogView jobId="j5" active={true} tail={2} />);
    expect(await screen.findByText(/first/)).toBeInTheDocument();
    expect(
      await screen.findByText(/second/, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(vi.mocked(getJobLog).mock.calls[1]).toEqual(["j5", 6]);
  });
});
