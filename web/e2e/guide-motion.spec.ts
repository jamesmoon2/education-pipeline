import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import path from "node:path";

// Schema 1.3 motion diagrams (docs/superpowers/specs/2026-09-27-motion-diagrams-design.md):
// flow particles, a turning concept map, narrated step walkthroughs for a
// timeline and a sequence, and a stack drawn with WebGL (or its SVG).

const ROOT = path.resolve(process.cwd(), "..");
const MOTION_FIXTURE = "tests/fixtures/guides/feedback-loops.motion.guide.json";
const DIAGRAMS_FIXTURE = "tests/fixtures/guides/feedback-loops.diagrams.guide.json";

function assemble(fixture: string): string {
  const script = [
    "from pathlib import Path",
    "from education_pipeline.guides import parse_guide, normalize_guide",
    "from education_pipeline.guides.document import assemble_guide_document",
    `p=Path('${fixture}')`,
    "print(assemble_guide_document(normalize_guide(parse_guide(p.read_bytes()))), end='')",
  ].join(";");
  return execFileSync("python3", ["-c", script], { cwd: ROOT, encoding: "utf8" });
}

let motionHtml: string;
let diagramsHtml: string;

test.beforeAll(() => {
  motionHtml = assemble(MOTION_FIXTURE);
  diagramsHtml = assemble(DIAGRAMS_FIXTURE);
});

async function load(page: Page, html = motionHtml) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setContent(html, { waitUntil: "load" });
  await expect(page.locator("[data-guide-status]")).toBeHidden();
  return errors;
}

// Sections are paged; show the one holding `figure` and bring it on screen.
async function reveal(page: Page, figure: string) {
  await page.evaluate((selector) => {
    const section = document.querySelector(selector)!.closest("section")!;
    location.hash = `#${section.id}`;
  }, figure);
  await page.locator(figure).scrollIntoViewIfNeeded();
}

const transformOf = (page: Page, selector: string) =>
  page.locator(selector).first().getAttribute("transform");

test.describe("motion diagrams (schema 1.3)", () => {
  test("the document declares schema 1.3 and runtime 1.3 and boots cleanly", async ({ page }) => {
    const errors = await load(page);
    await expect(page.locator("html")).toHaveAttribute("data-guide-schema", "1.3");
    await expect(page.locator("html")).toHaveAttribute("data-guide-runtime", "1.3");
    for (const id of ["growth-loop-flow", "loop-kinds-map", "watering-delay-timeline", "watering-timer-sequence", "garden-bed-stack"]) {
      await expect(page.locator(`figure#${id}`)).toHaveAttribute("data-diagram-state", "drawn");
    }
    expect(errors).toEqual([]);
  });

  test("a flowing flow streams particles along its edges and pauses on request", async ({ page }) => {
    await load(page);
    const figure = "figure#growth-loop-flow";
    await reveal(page, figure);
    await expect(page.locator(figure)).toHaveAttribute("data-motion-state", "playing");
    const particles = page.locator(`${figure} .diagram-motion .diagram-particle`);
    expect(await particles.count()).toBeGreaterThan(8);
    await expect(page.locator(`${figure} .diagram-motion`)).toHaveAttribute("aria-hidden", "true");
    const before = await transformOf(page, `${figure} .diagram-particle`);
    await expect.poll(() => transformOf(page, `${figure} .diagram-particle`)).not.toBe(before);

    const toggle = page.locator(`${figure} [data-role="diagram-motion-toggle"]`);
    await expect(toggle).toHaveText("Pause motion");
    await toggle.click();
    await expect(toggle).toHaveText("Play motion");
    await expect(page.locator(figure)).toHaveAttribute("data-motion-state", "paused");
    const frozen = await transformOf(page, `${figure} .diagram-particle`);
    await page.waitForTimeout(300);
    expect(await transformOf(page, `${figure} .diagram-particle`)).toBe(frozen);
  });

  test("a rotating concept map turns its ring around the hub", async ({ page }) => {
    await load(page);
    const figure = "figure#loop-kinds-map";
    await reveal(page, figure);
    const ring = `${figure} .diagram-node:not(.diagram-node--hub)`;
    const first = await transformOf(page, ring);
    await expect.poll(() => transformOf(page, ring)).not.toBe(first);
    await expect(page.locator(`${figure} .diagram-node--hub`)).not.toHaveAttribute("transform", /./);
  });

  test("a sequence is drawn as participants, lifelines and numbered messages", async ({ page }) => {
    await load(page);
    const svg = page.locator("figure#watering-timer-sequence svg");
    await expect(svg).toHaveCount(1);
    await expect(svg).toHaveClass("diagram-svg diagram-svg--sequence");
    await expect(svg).toHaveAttribute("role", "img");
    await expect(svg.locator("desc")).toHaveText(
      "Sequence diagram with 3 participants and 4 messages: 1. Soil sensor to Watering timer: Moisture is 18%; " +
        "2. Watering timer to Valve: Open for 10 minutes; 3. Valve to Watering timer: Watering done; " +
        "4. Watering timer to Soil sensor: Check again in an hour.",
    );
    await expect(svg.locator("g.diagram-actor")).toHaveCount(3);
    await expect(svg.locator("line.diagram-lifeline")).toHaveCount(3);
    await expect(svg.locator("g.diagram-message")).toHaveCount(4);
    await expect(svg.locator(".diagram-message-number")).toHaveText(["1", "2", "3", "4"]);
  });

  test("a step walkthrough autoplays with narration and yields to Next step and Restart", async ({ page }) => {
    await load(page);
    const figure = "figure#watering-timer-sequence";
    await reveal(page, figure);
    const status = page.locator(`${figure} [data-role="diagram-step-status"]`);
    await expect(status).toHaveText(
      "Step 1 of 4: Soil sensor → Watering timer: Moisture is 18%. Below the 25% target, so the timer acts.",
    );
    await expect(status).toHaveAttribute("role", "status");
    // Autoplay is not announced; the learner's own steps are.
    await expect(status).toHaveAttribute("aria-live", "off");
    await expect(page.locator(`${figure} g.diagram-message`).first()).toHaveClass(/is-active/);

    await page.locator(`${figure} [data-role="diagram-step-next"]`).click();
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(page.locator(`${figure} [data-role="diagram-step-toggle"]`)).toHaveText("Play walkthrough");
    await page.locator(`${figure} [data-role="diagram-step-next"]`).click();
    await expect(status).toHaveText("Step 2 of 4: Watering timer → Valve: Open for 10 minutes.");
    await expect(page.locator(figure)).toHaveAttribute("data-motion-step", "2");
    for (let i = 0; i < 6; i++) await page.locator(`${figure} [data-role="diagram-step-next"]`).click();
    await expect(status).toHaveText(/^Walkthrough complete: 4 steps\./);
    await expect(page.locator(`${figure} [data-role="diagram-step-toggle"]`)).toHaveText("Replay walkthrough");
    await expect(page.locator(`${figure} g.diagram-message.is-active`)).toHaveCount(0);

    await page.locator(`${figure} [data-role="diagram-step-restart"]`).click();
    await expect(status).toHaveText(/^Step 1 of 4:/);
    await expect(page.locator(figure)).toHaveAttribute("data-motion-state", "playing");
  });

  test("a timeline walkthrough lights each event in order", async ({ page }) => {
    await load(page);
    const figure = "figure#watering-delay-timeline";
    await reveal(page, figure);
    await page.locator(`${figure} [data-role="diagram-step-toggle"]`).click();
    await page.locator(`${figure} [data-role="diagram-step-next"]`).click();
    await page.locator(`${figure} [data-role="diagram-step-next"]`).click();
    await expect(page.locator(`${figure} [data-role="diagram-step-status"]`)).toHaveText(
      "Step 2 of 4: Day 1, evening: Surface still looks dry.",
    );
    const horizontal = page.locator(`${figure} svg.diagram-svg--timeline-h`);
    await expect(horizontal.locator(".diagram-event-marker.is-visited")).toHaveCount(1);
    await expect(horizontal.locator("text.is-current")).toHaveCount(1);
  });

  test("a stack keeps its SVG as the image and adds a WebGL canvas when it can", async ({ page }) => {
    await load(page);
    const figure = page.locator("figure#garden-bed-stack");
    const svg = figure.locator("svg.diagram-svg--stack");
    await expect(svg).toHaveAttribute("role", "img");
    await expect(svg.locator("desc")).toHaveText(
      "Layer stack of 4 layers, from top to bottom: Mulch; Topsoil; Root zone; Drainage gravel.",
    );
    await expect(svg.locator("g.diagram-stack-layer")).toHaveCount(4);
    await expect(svg.locator("text.diagram-stack-label")).toHaveText(["Mulch", "Topsoil", "Root zone", "Drainage gravel"]);
    const render = await figure.getAttribute("data-diagram-render");
    expect(["webgl", "svg"]).toContain(render);
    const canvas = figure.locator("canvas.diagram-stack-canvas");
    if (render === "webgl") await expect(canvas).toHaveAttribute("aria-hidden", "true");
    else await expect(canvas).toHaveCount(0);
  });

  test("under reduced motion nothing moves until the learner asks", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await load(page);
    const flow = "figure#growth-loop-flow";
    await reveal(page, flow);
    await expect(page.locator(flow)).toHaveAttribute("data-motion-state", "idle");
    await expect(page.locator(`${flow} [data-role="diagram-motion-toggle"]`)).toHaveText("Play motion");
    const sequence = "figure#watering-timer-sequence";
    await reveal(page, sequence);
    await expect(page.locator(sequence)).toHaveAttribute("data-motion-state", "idle");
    await expect(page.locator(`${sequence} [data-role="diagram-step-status"]`)).toHaveText("");
    await page.locator(`${sequence} [data-role="diagram-step-next"]`).click();
    await expect(page.locator(`${sequence} [data-role="diagram-step-status"]`)).toHaveText(/^Step 1 of 4:/);
  });

  test("motion diagrams add no serious accessibility violations", async ({ page }) => {
    await load(page);
    for (const figure of ["figure#growth-loop-flow", "figure#watering-timer-sequence"]) {
      await reveal(page, figure);
      const results = await new AxeBuilder({ page }).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
    }
  });

  test("still pictures are byte-deterministic across loads", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const markup = async () => {
      await load(page);
      return page.evaluate(() =>
        ["watering-timer-sequence", "garden-bed-stack"].map((id) => {
          const svg = document.querySelector(`figure#${id} svg`)!.cloneNode(true) as Element;
          svg.querySelectorAll(".diagram-motion").forEach((node) => node.remove());
          return svg.outerHTML;
        }),
      );
    };
    expect(await markup()).toEqual(await markup());
  });

  test("a schema 1.2 guide never moves", async ({ page }) => {
    const errors = await load(page, diagramsHtml);
    await expect(page.locator('[data-role="diagram-motion-controls"]')).toHaveCount(0);
    await expect(page.locator(".diagram-motion")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
