import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import JobLogView, { boundLogTail } from "./JobLogView";

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

  it("reassembles a line split across a chunk boundary, across several polls, keeping only the tail visible", async () => {
    vi.mocked(getJobLog)
      .mockResolvedValueOnce({ data: "line one\nline t", offset: 15 }) // splits mid-word
      .mockResolvedValueOnce({ data: "wo\nline three\n", offset: 29 })
      .mockResolvedValueOnce({ data: "line four\nline fi", offset: 47 }) // splits again
      .mockResolvedValueOnce({ data: "ve\n", offset: 50 })
      .mockResolvedValue({ data: "", offset: 50 });

    render(<JobLogView jobId="j6" active={true} tail={3} />);

    const pre = await screen.findByText(/line five/, undefined, { timeout: 4000 });
    // "line t" + "wo" and "line fi" + "ve" must reassemble whole, and only
    // the last 3 non-empty lines are shown.
    expect(pre).toHaveTextContent("line three line four line five");
    expect(pre).not.toHaveTextContent("line one");
    expect(pre).not.toHaveTextContent("line two");
  });
});

describe("boundLogTail", () => {
  it("keeps a bounded suffix as the raw buffer grows without limit", () => {
    const raw = Array.from({ length: 5_000 }, (_, i) => `line ${i}`).join("\n");
    const bounded = boundLogTail(raw, 3);
    // Nowhere near the full 5,000-line input -- this is the actual fix:
    // the retained buffer stays small regardless of how much log has
    // streamed by, not just the rendered view of it.
    expect(bounded.length).toBeLessThan(raw.length / 10);
    expect(bounded.split("\n").length).toBeLessThanOrEqual(3 + 50);
    // And it still contains what a 3-line tail needs.
    expect(bounded.endsWith("line 4999")).toBe(true);
  });

  it("preserves a trailing partial (unterminated) line intact", () => {
    const raw = "line one\nline two\npartial-nex";
    const bounded = boundLogTail(raw, 2);
    expect(bounded.endsWith("partial-nex")).toBe(true);
  });

  it("returns the input unchanged when it is already within bounds", () => {
    const raw = "a\nb\nc";
    expect(boundLogTail(raw, 5)).toBe(raw);
  });

  it("stays bounded even under repeated small appends (many poll chunks)", () => {
    let text = "";
    for (let i = 0; i < 1_000; i++) {
      text = boundLogTail(text + `chunk-${i}\n`, 3);
    }
    expect(text.split("\n").length).toBeLessThanOrEqual(3 + 50 + 1);
    expect(text).toContain("chunk-999");
    expect(text).not.toContain("chunk-0\n");
  });
});
