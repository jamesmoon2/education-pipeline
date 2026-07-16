# Interactive Guide v1 — Accessibility Acceptance Record

- **Date:** 2026-07-11
- **Tester:** Claude Code supervisor agent (Chunk 08). All checks below were
  performed by an agent driving headless Chromium via Playwright and inspecting
  rendered screenshots. No human tester has signed off; see
  "Human-required items" for what this record deliberately does not claim.
- **Build/commit:** worktree at `b467e83` (accepted Wave 6 head `f52fc97` is an
  ancestor); export produced by the 0.1.0 wheel installed into a clean venv.
- **Subject:** canonical fixture `tests/fixtures/guides/feedback-loops.guide.json`
  (normalized SHA-256
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`), exported
  with `assemble_guide_document` and opened from `file:` with no daemon.
- **Browser:** Playwright 1.61.1 headless Chromium (macOS, Darwin 25.5.0).
- **Screen reader:** none used (see blockers).

## Automated evidence actually produced

All commands were run on 2026-07-11 against the clean-install export.

1. **Repository acceptance suite** — `cd web && npm run e2e`: **37 passed**,
   including the axe scan (`no serious or critical automated accessibility
   violations`), HTTP/`file:` parity, keyboard-only operation of knowledge
   checks, worked reveals, scenarios, reflections, and section navigation,
   print-media expansion, and persistence checks.
2. **Axe, every section, both themes** — axe-core (`@axe-core/playwright`
   4.12.1) with tags `wcag2a, wcag2aa, wcag21a, wcag21aa` run separately on all
   four sections (`feedback-foundations`, `recognize-loop-types`,
   `delays-and-leverage`, `garden-decision`) in light and dark color schemes:
   **0 violations of any impact in all 8 scans**.
3. **320 CSS-pixel reflow** — viewport 320×720; horizontal overflow of the
   document element measured **0 px in all 4 sections**; screenshot inspection
   confirmed a single-column layout with no clipped or overlapping controls and
   the navigation collapsed behind the "Sections" toggle.
4. **Dark theme** — `prefers-color-scheme: dark` renders the dark palette on
   first load; explicit `dark` selection persists across reload
   (`theme-select` value verified). Screenshot inspection: text, controls, and
   the disabled submit state are legible and distinguishable; correctness
   feedback includes text ("Correct"/"Incorrect"), not color alone.
5. **Reduced motion** — with `prefers-reduced-motion: reduce`, root
   `scroll-behavior` computes to `auto` and transition/animation durations
   compute to ~0s (`1e-06s`).
6. **Print emulation** — `page.emulateMedia({ media: "print" })`: navigation and
   all interactive buttons hidden; both knowledge-check explanations visible;
   full-page screenshot inspected: every section rendered with per-choice
   correct/incorrect markers, worked-reveal steps and conclusions expanded,
   scenario quality labels/feedback/debrief shown, reflection prompt and
   guidance visible with the note textarea absent, and the external source URL
   printed after its link text.
7. **Keyboard focus visibility** — screenshot inspection confirmed a visible
   focus indicator on the skip link and on knowledge-check choices
   (outline-style `solid` when focused).

## Findings

### F1 — Skip link activation is a no-op (defect, frozen surface)

`runtime.js` installs a document-level click handler that calls
`event.preventDefault()` for every `a[href^="#"]` and delegates to
`goToTarget(...)`. The skip link targets `#guide-main`, which is the `<main>`
element — not a guide section and not inside one — so
`resolveOwningSectionId("guide-main")` returns `null` and `goToTarget` returns
without acting. Measured result of pressing Enter on the focused skip link:
`location.hash` unchanged, no scroll (`#guide-main` remained 427 px below the
viewport top), and focus stayed on the link. The skip link is present, first in
DOM order, and passes axe, but activating it does nothing. This fails the
manual checklist row "skip link … jumps to the main content" (WCAG 2.4.1
bypass-blocks intent). Fixing it requires changing frozen runtime behavior,
which Chunk 08 prohibits — recorded as a blocker, not fixed.

**Resolved 2026-07-11 with separate authorization:** `goToTarget` now focuses
in-document targets that no section owns (commit `e2cb6f4`), covered by a new
keyboard e2e test (`skip link: Enter moves focus to the main content without
changing section`; suite now 38 passed). Verified after the fix:
`python3 -m pytest` — 404 passed; `npm run e2e` — 38 passed.

### O1 — Initial Tab starts inside the current section (observation)

On load the runtime normalizes the URL to the current section via
`history.replaceState(null, "", "#<section-id>")`. Chromium then places the
sequential focus navigation starting point at that fragment, so the first Tab
lands inside the section (on the first section, "Next section", because
"Previous section" is disabled) rather than on the skip link. The skip link
remains reachable by Shift+Tab (verified) and is the first focusable in DOM
order. Combined with F1 this weakens the bypass mechanism; on its own it is a
usability nuance of accepted, frozen behavior. Flagged for the post-milestone
audit.

## Human-required items (not performed — exact blockers)

- **Screen-reader smoke pass:** a real assistive-technology pass (e.g. VoiceOver
  with Safari or Chrome) covering announcements for headings/landmarks,
  knowledge-check results, reveal steps, scenario feedback, reflection labels,
  the polite progress live region, and the unknown-fragment announcement. The
  agent has no access to a screen reader; this requires a human.
- **Human confirmation of the manual keyboard pass:** the keyboard-only flows
  are covered by automated Playwright key events and agent screenshot review,
  but the checklist's manual pass (real keyboard, human judgment of focus
  order/visibility) has not been performed by a person.
- **Real print dialog and real-device reflow:** print output was verified via
  print-media emulation and full-page screenshot, not a physical print preview;
  320 px reflow was verified in an emulated viewport, not a real device.

Template: `interactive-guide-v1-manual-acceptance.md` in this directory. A
human pass should copy that template into a new dated entry; this record does
not check any of its boxes on a human's behalf.

## Owner sign-off (2026-07-11)

The project owner manually exercised the cockpit and export during this
session: drove a full run and a paused editing run in the browser, used the
side-by-side prompt/response comparison, confirmed the exported guide is a
working standalone HTML file, and downloaded the canonical JSON. The owner
then **explicitly accepted the milestone with the remaining human-required
items waived without execution** (screen-reader smoke pass, formal manual
keyboard checklist pass, real print dialog, real-device reflow). These items
were not performed; the waiver, not their completion, is what closes the
blocker. They remain recommended before a public release and are flagged for
the Chunk 09 audit.
