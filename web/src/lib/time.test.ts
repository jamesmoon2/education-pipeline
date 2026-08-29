import { describe, expect, it } from "vitest";
import type { Job } from "../api/types";
import { formatDurationMs, jobElapsedMs } from "./time";

describe("formatDurationMs", () => {
  it("formats sub-minute durations as seconds", () => {
    expect(formatDurationMs(42_000)).toBe("42s");
    expect(formatDurationMs(0)).toBe("0s");
  });

  it("formats sub-hour durations as minutes and seconds", () => {
    expect(formatDurationMs(3 * 60_000 + 12_000)).toBe("3m 12s");
  });

  it("pads single-digit seconds within a minute", () => {
    expect(formatDurationMs(60_000 + 4_000)).toBe("1m 04s");
  });

  it("formats hour-scale durations as hours and minutes, dropping seconds", () => {
    expect(formatDurationMs(60 * 60_000 + 4 * 60_000)).toBe("1h 04m");
  });

  it("clamps negative durations to 0 rather than underflowing", () => {
    expect(formatDurationMs(-5_000)).toBe("0s");
  });
});

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1",
    topic_id: "t",
    stage: "draft",
    provider: "fake",
    model: null,
    effort: null,
    status: "running",
    created_at: "2026-07-10T00:00:00.000Z",
    started_at: null,
    ended_at: null,
    exit_code: null,
    error: null,
    ...overrides,
  };
}

const NOW = Date.parse("2026-07-10T00:05:00.000Z"); // created_at + 5min

describe("jobElapsedMs", () => {
  it("measures a running job from started_at against now", () => {
    const job = makeJob({
      status: "running",
      created_at: "2026-07-10T00:00:00.000Z",
      started_at: "2026-07-10T00:01:00.000Z",
    });
    expect(jobElapsedMs(job, NOW)).toBe(4 * 60_000);
  });

  it("measures a queued job (no started_at) from created_at against now", () => {
    const job = makeJob({ status: "queued", started_at: null });
    expect(jobElapsedMs(job, NOW)).toBe(5 * 60_000);
  });

  it("measures a terminal job's own recorded span, ignoring now", () => {
    const job = makeJob({
      status: "succeeded",
      created_at: "2026-07-10T00:00:00.000Z",
      started_at: "2026-07-10T00:01:00.000Z",
      ended_at: "2026-07-10T00:03:30.000Z",
    });
    expect(jobElapsedMs(job, NOW + 10_000_000)).toBe(2 * 60_000 + 30_000);
  });

  it("falls back to created_at when a terminal job has no started_at", () => {
    const job = makeJob({
      status: "canceled",
      created_at: "2026-07-10T00:00:00.000Z",
      started_at: null,
      ended_at: "2026-07-10T00:00:45.000Z",
    });
    expect(jobElapsedMs(job, NOW)).toBe(45_000);
  });

  it("returns null for a terminal job missing ended_at", () => {
    const job = makeJob({ status: "failed", ended_at: null });
    expect(jobElapsedMs(job, NOW)).toBeNull();
  });

  it("returns null when both started_at and created_at are unusable", () => {
    const job = makeJob({ status: "running", created_at: "", started_at: null });
    expect(jobElapsedMs(job, NOW)).toBeNull();
  });

  it("treats an invalid created_at string as missing rather than throwing", () => {
    const job = makeJob({ status: "queued", created_at: "not-a-date", started_at: null });
    expect(() => jobElapsedMs(job, NOW)).not.toThrow();
    expect(jobElapsedMs(job, NOW)).toBeNull();
  });

  it("treats an invalid ended_at string as missing rather than throwing", () => {
    const job = makeJob({
      status: "succeeded",
      started_at: "2026-07-10T00:01:00.000Z",
      ended_at: "not-a-date",
    });
    expect(() => jobElapsedMs(job, NOW)).not.toThrow();
    expect(jobElapsedMs(job, NOW)).toBeNull();
  });

  it("can produce a negative span under clock skew, left for the caller to clamp", () => {
    // jobElapsedMs reports raw elapsed time; formatDurationMs is what clamps
    // negatives, so a skewed pair here should NOT come back null or clamped.
    const job = makeJob({
      status: "succeeded",
      started_at: "2026-07-10T00:05:00.000Z",
      ended_at: "2026-07-10T00:04:00.000Z",
    });
    expect(jobElapsedMs(job, NOW)).toBe(-60_000);
  });
});
