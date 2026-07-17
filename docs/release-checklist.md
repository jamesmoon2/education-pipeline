# `v0.1` release checklist

The engineering deliverables for PRD §10 "P2 — Public `v0.1` release" are
on the branch this file landed with; this checklist is the remaining
owner-driven path to the tag. PRD §11 lists the release criteria this
walks through.

## 1. Verify the release gates (automated)

- [ ] CI green on the release commit: pytest (3.11 + 3.12), web unit +
      build, Playwright e2e, packaging smoke on **ubuntu / macos /
      windows**, artifact-leak guard.
- [ ] `python3 scripts/build_example.py` produces no diff (the shipped
      example export is reproducible from source).

## 2. Manual per-OS sign-off (PRD §11 criterion 9)

CI verifies wheel install, the CLI, and headless cockpit serving. The
interactive parts need one human pass per supported OS:

- [ ] **macOS:** `pip install` the wheel → `education-pipeline ui` →
      first-run workspace creation prompt → complete the documented
      example workflow (`docs/install-and-first-course.md`) → exported
      guide opens from `file:` in Safari.
- [ ] **Linux:** same pass; exported guide opens in Firefox and a
      Chromium-family browser.
- [ ] **Windows:** wheel install and the **manual CLI workflow** work
      (`topic import` → `advance`/`approve` → `export`); exported guide
      opens in Edge. The daemon/cockpit run on Windows and are covered
      by the packaging smoke (`lifecycle.is_pid_alive` uses a ctypes
      `OpenProcess` probe there). **Known limitation:** cancelling a job
      only terminates the provider's root process, not its process tree
      (issue #23).

**Resolved (PRD §15 open question 5):** the lifecycle liveness probe is
portable and the daemon smoke runs on all three OSes in CI; Windows is
not restricted to "CLI + exported guides only".

## 3. Decide distribution

- [ ] Build the release artifacts from the tagged commit:
      `python scripts/build_webdist.py && python -m build --wheel`.
- [ ] Attach the wheel to the GitHub release so
      `docs/install-and-first-course.md`'s packaged-release path is real.
- [ ] **Owner decision:** publish to PyPI or stay GitHub-releases-only
      for `v0.1`. (Docs currently assume a downloaded wheel; publishing
      to PyPI would simplify them to `pip install education-pipeline`.)

## 4. Record the demo (PRD §10 P2)

- [ ] A short (2–4 min) local screen recording: `education-pipeline ui`
      → New Course wizard → one provider or manual stage round-trip →
      approve → findings view → export → open `guide.html` offline.
      The synthetic example's content can be reused so no real learner
      data appears on screen.
- [ ] Link the recording from the GitHub release notes (hosting it in
      the repo is not required).

## 5. Tag

- [ ] Confirm `pyproject.toml` version `0.1.0` and update the
      `Development Status` classifier if desired.
- [ ] Write release notes: what the product does, supported platforms
      (per the §2 decision), the example guide as the showcase link, and
      known limitations (Windows daemon gap if accepted; provider CLIs
      change over time — edit the model catalog).
- [ ] `git tag v0.1.0 && git push origin v0.1.0`, create the GitHub
      release with the wheel + notes + demo link.
- [ ] Update PRD §10 P2 status to "Delivered" with the tag as evidence.

## Reference: what already landed with this milestone

- README rewritten around install → first course → example.
- `examples/feedback-loops/` — polished synthetic project + exported
  guide, pinned by `tests/test_example_project.py`.
- `docs/install-and-first-course.md`, `docs/providers.md`,
  `docs/privacy-and-local-trust.md`, `docs/troubleshooting.md` (kept in
  sync with `errors.py` by test), `docs/backup-and-migration.md`.
- `docs/provenance-review.md` — dependency/asset/font/copied-material
  review, no blocking findings.
- CI packaging smoke across the three OSes.
