import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("guide runtime opens the deterministic static fixture shell", async ({ page }) => {
  const root = path.resolve(process.cwd(), "..");
  const script = [
    "from pathlib import Path",
    "from education_pipeline.guides import parse_guide, normalize_guide",
    "from education_pipeline.guides.document import assemble_guide_document",
    "p=Path('tests/fixtures/guides/feedback-loops.guide.json')",
    "print(assemble_guide_document(normalize_guide(parse_guide(p.read_bytes()))), end='')",
  ].join(";");
  const document = execFileSync("python3", ["-c", script], { cwd: root, encoding: "utf8" });
  await page.setContent(document, { waitUntil: "load" });
  await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Course sections" })).toBeVisible();
  await expect(page.locator("article.knowledge_check").first()).toContainText("Success increases learning");
  await expect(page.locator("article.worked_reveal")).toContainText("Choose the quantity");
  await expect(page.locator("article.scenario")).toContainText("This treats visible damage");
  await expect(page.locator("article.reflection")).toContainText("Where might a delayed feedback loop");
  await expect(page.locator("[data-guide-status]")).toBeHidden();
});
