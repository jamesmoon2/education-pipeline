import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Course-library management acceptance (first-run milestone, spec §8):
// archive → hidden by default → filter shows → unarchive; duplicate → new
// course at spec; reveal fallback (opener failure) shows a copyable path.

let handle: DaemonHandle;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-library-", {
    // Force the reveal opener to fail so the UI exercises the
    // reveal_unsupported fallback path deterministically.
    env: { EP_REVEAL_OPENER: "/bin/false" },
    setup: (ws) => {
      writeFileSync(
        join(ws, "topics", "lib-topic.toml"),
        'schema_version = 1\nid = "lib-topic"\ntitle = "Library Topic"\n',
        "utf-8",
      );
    },
  });
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", handle.ws, "create", "lib-topic", "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
});

test.afterAll(() => {
  handle?.daemon.kill();
});

test("archive hides a course until the filter shows it; unarchive restores it", async ({
  page,
}) => {
  await page.goto(`${handle.baseURL}/`);
  const row = page.getByRole("link", { name: "lib-topic", exact: true });
  await expect(row).toBeVisible();

  await page.getByRole("button", { name: "Archive lib-topic" }).click();
  await expect(row).toBeHidden();

  await page.getByLabel("Show archived").check();
  await expect(row).toBeVisible();
  await expect(page.getByText("archived", { exact: false }).first()).toBeVisible();

  await page.getByRole("button", { name: "Unarchive lib-topic" }).click();
  await expect(page.getByRole("button", { name: "Archive lib-topic" })).toBeVisible();
  await page.getByLabel("Show archived").uncheck();
  await expect(row).toBeVisible();
});

test("duplicate starts a new course at spec from the same brief", async ({ page }) => {
  await page.goto(`${handle.baseURL}/`);
  await page.getByRole("button", { name: "Duplicate lib-topic" }).click();

  const copy = page.getByRole("link", { name: "lib-topic-copy", exact: true });
  await expect(copy).toBeVisible();
  const copyRow = page.getByRole("row").filter({ has: copy });
  await expect(copyRow.getByText("no run")).toBeVisible();
});

test("reveal falls back to a copyable path when the opener fails", async ({ page }) => {
  await page.goto(`${handle.baseURL}/`);
  await page.getByRole("button", { name: "Reveal lib-topic", exact: true }).click();

  const notice = page.getByRole("alert");
  await expect(notice).toContainText(/file manager could not be opened/i);
  await expect(notice.locator("code")).toContainText(/runs\/lib-topic$/);
  await expect(notice.getByRole("button", { name: /copy path/i })).toBeVisible();
});
