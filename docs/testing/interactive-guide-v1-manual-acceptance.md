# Interactive Guide v1 — Manual Acceptance Checklist

Use this checklist to record human verification of the guide runtime that automated
tests cannot fully cover (real assistive technology, real device reflow, real print
preview). Automated coverage (pytest, vitest, Playwright, axe) is necessary but not
sufficient per the runtime spec (§13).

Copy this template into a dated entry for each milestone acceptance pass. Test against
the canonical fixture (`tests/fixtures/guides/feedback-loops.guide.json`) exported both
as an HTTP-served document and as a local `file://` export, unless a row says otherwise.

## Run record

- Date:
- Tester:
- Build/commit:
- Browser(s) and OS:
- Screen reader (if used):

## 1. Keyboard-only operation

- [ ] Skip link is the first focusable element and jumps to the main content.
- [ ] Tab order through the course header, controls, navigation, and main content is
      logical and never traps focus.
- [ ] Every knowledge check can be answered, submitted, and retried using only the
      keyboard (Tab/Shift+Tab, Space/arrow keys for choices, Enter/Space for buttons).
- [ ] Every worked reveal can be stepped through, shown all, and reset using only the
      keyboard.
- [ ] Every scenario can be chosen and submitted using only the keyboard.
- [ ] The reflection textarea, skip control, and reset control are all reachable and
      operable by keyboard; the reset confirmation dialog can be accepted/dismissed by
      keyboard.
- [ ] Previous/next section controls, the mark-complete control, the theme select, and
      the reset-progress control are all reachable and operable by keyboard.
- [ ] The download-progress and restore-progress controls, and both buttons of the
      carry-over offer banner ("Resume that progress" / "Start fresh"), are reachable
      and operable by keyboard; the restore control opens the file picker from the
      keyboard and the hidden file input is never itself a tab stop.
- [ ] Visible focus indicator is present on every interactive element.

## 2. Screen reader smoke test

- [ ] Page title and heading structure announce the course name and current section.
- [ ] Landmarks (navigation, main, header) are announced correctly.
- [ ] Submitting a knowledge check announces correct/incorrect state and the
      explanation without moving focus away from the control.
- [ ] Revealing a worked-reveal step announces the new step content without moving
      focus.
- [ ] Submitting a scenario choice announces the feedback and debrief.
- [ ] The reflection area's label, guidance, and local-storage explanation are
      announced.
- [ ] Progress summary changes are announced as a polite live region (not disruptive).
- [ ] An unknown URL fragment announcement is heard but does not steal focus.

## 3. 320px reflow

- [ ] At a 320 CSS-pixel viewport width, layout is a single column with no horizontal
      scrolling of the page body.
- [ ] Section navigation collapses into a toggleable drawer and remains usable.
- [ ] All controls remain legible and tappable (no overlapping or clipped text).

## 4. Dark theme

- [ ] Theme select's "Match system" option follows the OS/browser
      `prefers-color-scheme` on first load (no stored preference).
- [ ] Explicit "Dark" and "Light" selections persist across reload.
- [ ] Text, controls, and focus indicators meet contrast in the dark theme by visual
      inspection (spot-check with a contrast tool if available: 4.5:1 normal text,
      3:1 large text/UI).
- [ ] No state (correct/incorrect, quality label, disabled) is conveyed by color alone
      in either theme.

## 5. Reduced motion

- [ ] With `prefers-reduced-motion: reduce` enabled at the OS level, section changes,
      reveals, and scrolling show no nonessential animation or smooth-scroll.

## 6. Print inspection

- [ ] Print preview (or `page.emulateMedia({ media: "print" })` equivalent in
      DevTools) hides navigation, course controls, and all interactive buttons.
- [ ] Every knowledge check shows all choices plus each choice's correct/incorrect
      marker and the explanation.
- [ ] Every worked reveal shows all steps and the conclusion, expanded.
- [ ] Every scenario shows all choices' quality/feedback and the debrief.
- [ ] Reflection prompts and guidance are visible; the note textarea and any saved
      note text are absent from print output.
- [ ] External link destinations are legible (URL shown after link text).
- [ ] No pathological page breaks split a block awkwardly across pages.

## Notes / defects found

(Record any deviations, filing issues as needed.)
