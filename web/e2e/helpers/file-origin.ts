import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { Page } from "@playwright/test";

/**
 * Open a file:// document in a way that lets its localStorage writes survive
 * the next navigation.
 *
 * In a fresh Playwright page, Chromium intermittently loses every
 * localStorage write made by the *first* file:// document the page commits:
 * the next document (a reload included) starts from the storage the page had
 * before that document, never from what it wrote. Reproduced with a one-line
 * page and no guide runtime at all (~3-5% of runs under 6 workers, more when
 * an init script writes storage); only the first file:// document is ever
 * affected, and http:// origins never are. A test that writes through the
 * first document and then reloads -- the carry-over offer's "Resume that
 * progress" -- therefore read the pre-write record back at random.
 *
 * So the page commits a throwaway file:// document next to the target first.
 * The target is then never the page's first file:// document, and what it
 * stores is what the next document reads. Init scripts registered on the
 * page run in the primer too, so seeded records are in place either way.
 */
export async function gotoFileUrl(page: Page, fileUrl: string): Promise<void> {
  const primerPath = path.join(path.dirname(fileURLToPath(fileUrl)), "file-origin-primer.html");
  writeFileSync(
    primerPath,
    "<!doctype html><title>file origin primer</title>" +
      "<script>try { window.localStorage.length; } catch (_error) {}</script>",
    "utf8",
  );
  await page.goto(pathToFileURL(primerPath).href, { waitUntil: "load" });
  await page.goto(fileUrl, { waitUntil: "load" });
}
