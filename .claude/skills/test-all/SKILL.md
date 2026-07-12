---
name: test-all
description: Run all three test suites (pytest, vitest, Playwright e2e) plus the web type-check, and report a combined pass/fail summary with counts
---

# Run All Test Suites

Run every suite below from the repo root. Run them all even if an earlier one fails — the goal is a complete picture, not fail-fast.

1. **Python**: `python3 -m pytest` (from repo root)
2. **Web type-check**: `npx tsc --noEmit` (from `web/`)
3. **Web unit**: `npm run test` (from `web/`, vitest)
4. **Web e2e**: `npm run e2e` (from `web/`, Playwright)

The pytest and vitest suites can run in parallel with each other; run tsc before vitest if sequencing.

## Reporting

End with a summary table:

| Suite | Result | Count |
|-------|--------|-------|
| pytest | pass/FAIL | N passed |
| tsc | pass/FAIL | — |
| vitest | pass/FAIL | N passed |
| e2e | pass/FAIL | N passed |

For any failing suite, include the failing test names and the relevant error output — not the full log. If a suite could not run at all (e.g., Playwright browsers not installed: fix with `npx playwright install`), say so explicitly rather than reporting it as a test failure.
