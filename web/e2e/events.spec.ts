import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// T62 (plan decisions 9-13; design note §7 e2e): with the events stream up,
// an open run board stops polling, and a CLI write from another process —
// which no in-daemon bus could see — reaches it as a change notice.

const REPO_ROOT = resolve(import.meta.dirname, "../..");
const TOPIC = "ev-board";
const RUN_PATH = `/v1/runs/${TOPIC}`;

let handle: DaemonHandle;

function cli(...args: string[]): string {
  return execFileSync("python3", ["-m", "education_pipeline", "-C", handle.ws, ...args], {
    cwd: REPO_ROOT,
    encoding: "utf-8",
  });
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-events-", {
    setup: (ws) => {
      writeFileSync(
        join(ws, "topics", `${TOPIC}.toml`),
        `schema_version = 1\nid = "${TOPIC}"\ntitle = "Events board"\n`,
        "utf-8",
      );
    },
  });
  cli("create", TOPIC, "--legacy-markdown");
});

test.afterAll(() => {
  handle?.daemon.kill();
});

test("a CLI advance reaches an open run board through the events stream, with no poll", async ({
  page,
}) => {
  // Only the board's own status route: /v1/runs/{t} exactly, not its
  // /plan, /stages/... or the rail's routes.
  let requests = 0;
  let responses = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === RUN_PATH) requests += 1;
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === RUN_PATH) responses += 1;
  });

  // Count every transition of <html data-events> into "up": a reconnect's
  // hello would add one, so an unchanged count proves the stream stayed up.
  await page.addInitScript(() => {
    const w = window as unknown as { __epEventsUps: number };
    w.__epEventsUps = 0;
    let last: string | undefined;
    new MutationObserver(() => {
      const value = document.documentElement.dataset.events;
      if (value === "up" && last !== "up") w.__epEventsUps += 1;
      last = value;
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-events"] });
  });
  const ups = () =>
    page.evaluate(() => (window as unknown as { __epEventsUps: number }).__epEventsUps);

  await page.goto(`${handle.baseURL}/topics/${TOPIC}`);
  const next = page.locator(".next-action");
  await expect(next).toContainText(`Write the spec prompt for '${TOPIC}'`);

  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-events", "up");
  // The post-hello resync can start after the attribute flips. Wait for its
  // response (the second one, after the mount tick's) and for nothing to be
  // in flight, so it lands before the counting window, not inside it.
  await expect.poll(() => responses).toBeGreaterThanOrEqual(2);
  await expect.poll(() => requests - responses).toBe(0);

  const windowStart = requests;
  const upsAtStart = await ups();
  await page.waitForTimeout(6_000); // longer than the board's 5 s status poll
  expect(requests - windowStart, "no /v1/runs/{t} poll while the stream is up").toBe(0);
  await expect(root).toHaveAttribute("data-events", "up");

  cli("advance", TOPIC);
  await expect(next).toContainText("Run the spec prompt", { timeout: 3_000 });
  expect(requests - windowStart).toBeGreaterThanOrEqual(1);
  // The stream stayed up throughout: the update came from a notice, not a
  // reconnect's resync or a fallback poll.
  await expect(root).toHaveAttribute("data-events", "up");
  expect(await ups()).toBe(upsAtStart);
});
