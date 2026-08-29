import type { Job } from "../api/types";

/** Formats a millisecond duration as a compact, plain-language string:
 *  "42s", "3m 12s", "1h 04m". Negative durations clamp to 0 -- clock skew
 *  between the daemon's timestamps and the browser's `now` is routine, not
 *  exceptional, and should read as "just started" rather than underflow. */
export function formatDurationMs(ms: number): string {
  const totalSeconds = Math.floor(Math.max(0, ms) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

const JOB_ACTIVE_STATUSES = new Set<Job["status"]>(["queued", "running"]);

function parseTimestampMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/** Elapsed time for a job, in milliseconds. Active jobs (queued or running)
 *  are measured against `now` so the caller can tick; terminal jobs are
 *  measured over their own recorded span. Returns null -- render "—", never
 *  a fabricated number -- when a stamp the calculation needs is missing or
 *  unparsable, so a malformed payload can never throw during render. */
export function jobElapsedMs(
  job: Pick<Job, "status" | "created_at" | "started_at" | "ended_at">,
  now: number,
): number | null {
  const start = parseTimestampMs(job.started_at) ?? parseTimestampMs(job.created_at);
  if (start === null) return null;
  if (JOB_ACTIVE_STATUSES.has(job.status)) return now - start;
  const end = parseTimestampMs(job.ended_at);
  return end === null ? null : end - start;
}
