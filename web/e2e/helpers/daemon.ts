import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Repo root and the built web bundle, resolved relative to this helper file
// (web/e2e/helpers/) so callers don't each re-derive the same paths.
const REPO_ROOT = resolve(import.meta.dirname, "../../..");
const WEB_DIST = resolve(import.meta.dirname, "../../dist");

export interface DaemonHandle {
  daemon: ChildProcess;
  baseURL: string;
  /** The freshly created, isolated workspace directory the daemon serves. */
  ws: string;
}

/**
 * Boot a loopback daemon over a fresh temp workspace and wait until it has
 * published a ready discovery record.
 *
 * This is the daemon-boot + discovery-poll scaffolding every e2e spec needs.
 * It was duplicated inline across the suite; the release-gates spec is well
 * past the third copy, so the poll is extracted here (per the wave audit)
 * instead of pasted a sixth time.
 *
 * @param prefix mkdtemp prefix, e.g. "ep-e2e-release-gates-".
 * @param opts.env extra env vars merged over the daemon's environment
 *   (e.g. a stub-provider PATH). EP_WEB_DIST is always set.
 * @param opts.setup optional hook to seed the workspace before boot
 *   (config files, fixtures) — runs after topics/ is created.
 */
export async function bootDaemon(
  prefix: string,
  opts: { env?: NodeJS.ProcessEnv; setup?: (ws: string) => void } = {},
): Promise<DaemonHandle> {
  const ws = mkdtempSync(join(tmpdir(), prefix));
  try {
    mkdirSync(join(ws, "topics"), { recursive: true });
    opts.setup?.(ws);
  } catch (error) {
    rmSync(ws, { recursive: true, force: true });
    throw error;
  }

  let daemon: ChildProcess;
  try {
    daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
      cwd: REPO_ROOT,
      env: { ...process.env, EP_WEB_DIST: WEB_DIST, ...(opts.env ?? {}) },
      stdio: "inherit",
    });
  } catch (error) {
    rmSync(ws, { recursive: true, force: true });
    throw error;
  }

  let resolveSpawnError!: (error: Error) => void;
  const spawnError = new Promise<Error>((resolveError) => {
    resolveSpawnError = resolveError;
  });
  let firstSpawnError: Error | undefined;
  const onSpawnError = (error: Error) => {
    if (firstSpawnError) return;
    firstSpawnError = error;
    resolveSpawnError(error);
  };
  daemon.on("error", onSpawnError);

  let resolveClose!: () => void;
  const closed = new Promise<void>((resolveClosed) => {
    resolveClose = resolveClosed;
  });
  const onClose = () => resolveClose();
  daemon.once("close", onClose);

  const discovery = join(ws, ".education-pipeline", "daemon.json");
  let record: { port?: number } | undefined;
  try {
    for (let i = 0; i < 100 && !record?.port; i++) {
      const error = await Promise.race([
        new Promise<undefined>((resolveDelay) => setTimeout(resolveDelay, 100)),
        spawnError,
      ]);
      if (error) throw error;
      if (!existsSync(discovery)) continue;
      try {
        record = JSON.parse(readFileSync(discovery, "utf-8")) as { port?: number };
      } catch {
        // partially written record; keep polling
      }
    }
    if (!record?.port) {
      throw new Error("daemon never wrote a ready discovery record");
    }
  } catch (error) {
    if (daemon.exitCode === null && daemon.signalCode === null) daemon.kill();
    await closed;
    daemon.off("error", onSpawnError);
    daemon.off("close", onClose);
    rmSync(ws, { recursive: true, force: true });
    throw error;
  }

  daemon.off("error", onSpawnError);
  daemon.off("close", onClose);
  return { daemon, baseURL: `http://127.0.0.1:${record.port}`, ws };
}
