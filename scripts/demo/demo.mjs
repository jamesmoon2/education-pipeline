// Product demo recorder: drives the real cockpit over a seeded workspace and
// records a captioned, cursor-visible walkthrough. Output: demo.webm (raw).
import { spawn } from "node:child_process";
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Usage: node scripts/demo/demo.mjs <workspace> [out-dir]
//   The workspace comes from scripts/demo/seed.py. Needs web/dist built and
//   web/node_modules installed (Playwright ships with the cockpit dev deps).
//   PLAYWRIGHT_CHROMIUM_EXECUTABLE overrides the browser binary.
const HERE = resolve(process.argv[1], "..");
const REPO = process.env.EP_REPO ?? resolve(HERE, "../..");
const { chromium } = await import(pathToFileURL(join(REPO, "web/node_modules/playwright/index.mjs")).href);
const WS = process.argv[2] ?? "/tmp/ep-demo-ws";
const OUT = process.argv[3] ?? join(HERE, "out");
mkdirSync(OUT, { recursive: true });
const W = 1920, H = 1080;

// ---------------------------------------------------------------- daemon
import { rmSync } from "node:fs";
rmSync(join(WS, ".education-pipeline"), { recursive: true, force: true });
const daemon = spawn("python3", ["-m", "education_pipeline.daemon", WS], {
  cwd: REPO, env: { ...process.env, EP_WEB_DIST: join(REPO, "web/dist") }, stdio: "ignore",
});
const discovery = join(WS, ".education-pipeline", "daemon.json");
let port;
for (let i = 0; i < 100 && !port; i++) {
  await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(discovery)) continue;
  try { port = JSON.parse(readFileSync(discovery, "utf-8")).port; } catch {}
}
if (!port) throw new Error("daemon never became ready");
const base = `http://127.0.0.1:${port}`;

// --------------------------------------------------------------- overlay
// Installed on every document: a cursor that follows real mouse events, a
// click ripple, a caption bar, and a fade cover for scene changes.
const OVERLAY = `
(() => {
  const css = \`
    #demo-cursor { position: fixed; z-index: 100000; width: 28px; height: 28px; pointer-events: none; left: -100px; top: -100px; filter: drop-shadow(0 2px 4px rgba(0,0,0,.45)); transition: transform 120ms ease; }
    #demo-cursor.down { transform: scale(.85); }
    .demo-ripple { position: fixed; z-index: 99999; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; border: 3px solid #c4b5fd; pointer-events: none; animation: demo-ripple 520ms ease-out forwards; }
    @keyframes demo-ripple { from { transform: scale(1); opacity: .9 } to { transform: scale(5); opacity: 0 } }
    #demo-caption { position: fixed; z-index: 90000; left: 50%; bottom: 44px; transform: translate(-50%, 24px); opacity: 0; max-width: 1280px; padding: 20px 30px 20px 26px; border-radius: 20px; background: rgba(13,11,26,.82); color: #edebf8; border: 1px solid rgba(179,157,255,.28); box-shadow: 0 30px 80px -20px rgba(0,0,0,.8), 0 0 0 1px rgba(124,58,237,.15); backdrop-filter: blur(16px); font-family: "Inter","Segoe UI",system-ui,sans-serif; font-size: 30px; line-height: 1.32; letter-spacing: -0.01em; text-wrap: balance; text-align: center; transition: opacity 320ms ease, transform 420ms cubic-bezier(.22,1,.36,1); pointer-events: none; }
    #demo-caption.on { opacity: 1; transform: translate(-50%, 0); }
    #demo-caption::before { content: ""; position: absolute; left: 26px; right: 26px; top: 0; height: 3px; border-radius: 0 0 3px 3px; background: linear-gradient(90deg,#a78bfa,#22d3ee 55%,#fbbf24); }
    #demo-caption .k { display: block; font-size: 15px; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; color: #a78bfa; margin-bottom: 6px; }
    #demo-cover { position: fixed; inset: 0; z-index: 200000; background: #0d0b1a; pointer-events: none; opacity: 0; transition: opacity 380ms ease; }
    #demo-cover.on { opacity: 1; }
  \`;
  const install = () => {
    if (document.getElementById("demo-cursor")) return;
    const style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);
    const cur = document.createElement("div"); cur.id = "demo-cursor";
    cur.innerHTML = '<svg viewBox="0 0 28 28"><path d="M5 3l16 11-7 1.5 4.5 8-3.5 1.8-4.6-8L5 22z" fill="#fff" stroke="#16132b" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cur);
    const cap = document.createElement("div"); cap.id = "demo-caption"; document.body.appendChild(cap);
    const cover = document.createElement("div"); cover.id = "demo-cover"; document.body.appendChild(cover);
    let covered = false; try { covered = sessionStorage.getItem("demo.covered") === "1"; } catch {}
    if (covered) { cover.classList.add("on"); }
    document.addEventListener("mousemove", (e) => { cur.style.left = e.clientX + "px"; cur.style.top = e.clientY + "px"; }, true);
    document.addEventListener("mousedown", (e) => { cur.classList.add("down"); const r = document.createElement("i"); r.className = "demo-ripple"; r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px"; document.body.appendChild(r); setTimeout(() => r.remove(), 600); }, true);
    document.addEventListener("mouseup", () => cur.classList.remove("down"), true);
    window.__demo = {
      caption(kicker, text) { const el = document.getElementById("demo-caption"); if (!text) { el.classList.remove("on"); return; } el.classList.remove("on"); setTimeout(() => { el.innerHTML = (kicker ? '<span class="k">' + kicker + '</span>' : '') + text; el.classList.add("on"); }, 240); },
      cover(on) { const el = document.getElementById("demo-cover"); el.classList.toggle("on", on); try { sessionStorage.setItem("demo.covered", on ? "1" : "0"); } catch {} },
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install); else install();
})();`;

// ---------------------------------------------------------------- driver
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const context = await browser.newContext({
  viewport: { width: W, height: H },
  // The exported guide ships a strict CSP that would block the overlay's
  // injected stylesheet; the recording is not a security context.
  bypassCSP: true,
  deviceScaleFactor: 1,
  colorScheme: "dark",
  recordVideo: { dir: OUT, size: { width: W, height: H } },
});
await context.addInitScript(OVERLAY);
const page = await context.newPage();
page.setDefaultTimeout(45000);
process.on("unhandledRejection", async (err) => {
  console.error(err);
  try { await page.screenshot({ path: join(OUT, "fail.png") }); } catch {}
  try { await context.close(); } catch {}
  daemon.kill();
  process.exit(1);
});
let mouse = { x: W / 2, y: H / 2 };
const t0 = Date.now();
const marks = [];
const mark = (name) => marks.push([name, (Date.now() - t0) / 1000]);

const pause = (ms) => page.waitForTimeout(ms);
async function glide(x, y, ms = 420) {
  // One batched move: Playwright interpolates `steps` events in a single
  // CDP exchange, which keeps the cursor smooth without a slow round trip
  // per sub-move.
  await page.mouse.move(x, y, { steps: 4 });
  mouse = { x, y };
  await pause(Math.min(ms, 160));
}
async function hover(locator, ms) {
  const box = await locator.first().boundingBox();
  if (!box) throw new Error("no box for hover");
  await glide(box.x + box.width / 2, box.y + Math.min(box.height / 2, 28), ms);
}
async function click(locator, { settle = 700 } = {}) {
  await locator.first().scrollIntoViewIfNeeded();
  await hover(locator, 560);
  await pause(120);
  await page.mouse.down(); await pause(70); await page.mouse.up();
  await pause(settle);
}
async function type(locator, text, delay = 26) {
  await click(locator, { settle: 200 });
  await locator.first().pressSequentially(text, { delay });
}
async function caption(kicker, text, hold = 0) {
  await page.evaluate(([k, t]) => window.__demo?.caption(k, t), [kicker, text]);
  if (hold) await pause(hold);
}
async function scene(url, { kicker, text, wait = 900 } = {}) {
  await page.evaluate(() => window.__demo?.cover(true)); await pause(420);
  await page.goto(url);
  await page.waitForLoadState("load").catch(() => {});
  await pause(350);
  await page.evaluate(() => window.__demo?.cover(false));
  await pause(wait);
  if (text) await caption(kicker, text);
}
async function scrollTo(y, ms = 900) {
  await page.evaluate((top) => window.scrollTo({ top, behavior: "smooth" }), y);
  await pause(ms);
}
async function setTheme(theme) {
  await page.evaluate((t) => { if (t) localStorage.setItem("ep.theme", t); else localStorage.removeItem("ep.theme"); }, theme);
}

const fileUrl = (name) => "file://" + join(HERE, name);

// ================================================================ scenes
try {
mark("title");
await page.goto(fileUrl("title.html"));
await pause(3600);

// 1. Library
await page.goto(`${base}/`); // set storage on the right origin first
await setTheme("dark");
await scene(`${base}/`, { kicker: "The workbench", text: "Every course, its next safe move, and what it has cost. All of it plain files on this computer." });
mark("library");
await pause(900);
await hover(page.getByRole("link", { name: "Review and approve" }).first(), 900).catch(() => {});
await pause(400);
await caption("The workbench", "The <b>Next action</b> column always names the one safe move — click it and you land exactly where that work happens.");
await hover(page.getByRole("link", { name: "feedback-loops", exact: true }), 700);
await pause(1200);

// 2. New course wizard
await caption("Create", "Start with a brief, not a template.");
await click(page.getByRole("link", { name: "Start a new course" }));
mark("wizard");
await pause(600);
await caption("Create", "Attach a learner profile and every example, depth choice and practice item adapts to that person.");
await click(page.getByLabel("Learner profile"), { settle: 300 });
await page.getByLabel("Learner profile").selectOption("example-learner");
await pause(600);
await click(page.getByRole("button", { name: "Continue" }));
await caption("Create", "Describe what you want to learn, for whom, and what they should be able to do afterwards.");
await type(page.getByLabel("Topic id", { exact: true }), "bayes-intuition", 40);
await type(page.getByLabel("Title"), "Bayesian Intuition for Practitioners", 30);
await type(page.getByLabel("Brief", { exact: true }), "A working intuition for updating beliefs with evidence, built from everyday decisions rather than formulas.", 13);
await type(page.getByLabel("Audience", { exact: true }), "a product manager who runs A/B tests but never took statistics", 13);
await type(page.getByLabel("Goals (one per line)"), "explain a posterior in plain words\nspot base-rate neglect", 14);
await pause(300);
await click(page.getByRole("button", { name: "Continue" }));
await caption("Create", "A pedagogical <b>blueprint</b> is recommended for the brief and explained in plain language.");
await pause(1000);
await hover(page.getByRole("radio").first(), 700);
await pause(900);
await click(page.getByRole("button", { name: "Continue" }));
await caption("Create", "Choose which model runs each stage — Claude Code, Codex, or paste prompts into anything you already use.");
await pause(1800);
await click(page.getByRole("button", { name: "Continue" }));
await caption("Create", "Review, then create. The course folder and its first prompt are written to disk immediately.");
await pause(1300);
await click(page.getByRole("button", { name: "Create course" }));
mark("run-board-new");

// 3. Run board: approve a stage
await page.getByRole("heading", { name: "bayes-intuition" }).waitFor();
await pause(700);
await caption("Run", "The board leads with the one next move. Nothing runs, and nothing advances, without you.");
await pause(1800);
await caption("Run", "Each stage writes a prompt. Copy it into your model, paste the response back — or let a provider run it.");
await hover(page.getByRole("button", { name: "Copy prompt" }), 600);
await pause(600);
await click(page.getByRole("button", { name: "Paste response…", exact: true }));
const spec = `# Course Specification: Bayesian Intuition for Practitioners

A 20-minute course for a product manager who runs A/B tests but never took a
statistics course. Every idea is introduced through a decision they already
make; formulas appear only after the intuition is in place.

## Learning Outcomes

- Explain a posterior in plain words as "what you believed, updated by what you saw."
- Spot base-rate neglect in a real product decision and correct for it.
- Judge when one more experiment is worth running.

\`\`\`education-pipeline-contract+json
{"contract_version": 1, "guide_schema_version": "1.1", "blueprint": "conceptual-foundations", "estimated_minutes": 20, "outcomes": [{"id": "posterior", "text": "Explain a posterior in plain words."}, {"id": "base-rates", "text": "Spot base-rate neglect in a real decision."}, {"id": "next-test", "text": "Judge when one more experiment is worth running."}], "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"], "personalization_requirements": ["Use A/B testing examples."], "source_policy": "Sources required for factual claims that are not common knowledge."}
\`\`\`
`;
const responseBox = page.getByLabel("Response for spec", { exact: true }).first();
await click(responseBox, { settle: 200 });
const typedPrefix = spec.split("\n").slice(0, 3).join("\n");
await responseBox.pressSequentially(typedPrefix, { delay: 8 });
await pause(300);
// The field is focused; insert the rest at the caret (no actionability wait).
await page.keyboard.insertText(spec.slice(typedPrefix.length));
await pause(700);
await click(page.getByRole("button", { name: "Save response", exact: true }));
await caption("Run", "<b>Approve &amp; continue</b> accepts this stage and writes the next prompt. The thread moves one node — never two.");
await pause(1100);
await click(page.getByRole("button", { name: "Approve spec & continue", exact: true }));
await page.getByText(/Run the outline prompt/).waitFor();
await pause(600);
await hover(page.getByRole("listitem", { name: "outline stage" }), 800);
await pause(1600);

// 4. Finished run
await scene(`${base}/topics/feedback-loops`, { kicker: "Quality", text: "A finished run is a quality record: validation milestones, personalization fit, a live preview, and export." });
mark("run-board-complete");
await pause(1300);
await scrollTo(760, 1200);
await pause(900);
await caption("Quality", "Validation checks the guide's structure with no model involved. Blocking findings must be fixed or deliberately waived.");
await scrollTo(1700, 1300);
await pause(1700);

// 5. Stage viewer
await scene(`${base}/topics/feedback-loops/stages/outline?tab=response`, { kicker: "Inspect", text: "Every artifact is readable prose or a collapsible tree — and the exact raw bytes are one click away." });
mark("stage-viewer");
await pause(1500);
await click(page.getByRole("button", { name: "Raw" }));
await pause(1200);
await click(page.getByRole("button", { name: "Rendered" }));
await pause(700);

// 6. The learner's guide
await scene("file://" + join(WS, "runs/feedback-loops/final/guide.html"), { kicker: "The payoff", text: "The learner gets one offline HTML file: knowledge checks, worked reveals, scenarios, reflections — progress stays in their browser." });
mark("guide");
await pause(900);
const themeSelect = page.getByLabel(/theme/i).first();
if (await themeSelect.count()) { await click(themeSelect, { settle: 250 }); await themeSelect.selectOption({ label: "Dark" }).catch(() => {}); }
await pause(1400);
await scrollTo(700, 1400);
await pause(1200);
const nextSection = page.getByRole("button", { name: "Next section" }).first();
if (await nextSection.count()) { await click(nextSection); }
await pause(2000);

// 7. Tour + theme
await scene(`${base}/`, { kicker: "Onboarding", text: "New here? A two-minute guided tour explains every surface, and every run board can explain itself." });
mark("tour");
await click(page.getByRole("button", { name: "Take the tour" }));
await pause(1800);
await click(page.getByRole("button", { name: "Next" }));
await pause(1600);
await click(page.getByRole("button", { name: "Next" }));
await pause(1800);
await page.keyboard.press("Escape");
await pause(600);
await caption("Your call", "Light or dark. It follows your system until you choose.");
await click(page.getByRole("radio", { name: "Light" }));
await pause(1700);
await click(page.getByRole("radio", { name: "Dark" }));
await pause(1200);
await caption("", "");
await pause(400);

// 8. End card
await page.evaluate(() => window.__demo?.cover(true)); await pause(500);
await page.goto(fileUrl("end.html"));
mark("end");
await page.evaluate(() => window.__demo?.cover(false));
await pause(5200);

} catch (err) {
  console.error("DEMO FAILED at", marks.at(-1), err.message.split("\n").slice(0, 14).join(" | "));
  await page.screenshot({ path: join(OUT, "fail.png") }).catch(() => {});
  await page.evaluate(() => document.body.innerText.slice(0, 1500)).then((t) => console.error(t)).catch(() => {});
}
await context.close();
await browser.close();
daemon.kill();
const video = await page.video()?.path();
console.log(JSON.stringify({ video, marks }));
