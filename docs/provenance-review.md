# Provenance review for `v0.1`

- **Reviewed:** 2026-07-17, on the state of branch `claude/v0-1-p2-item-pph1vo`.
- **Scope (PRD §10 P2):** dependencies, assets, fonts, and copied material.
- **Method:** `pyproject.toml` inspection; license-field sweep of every
  entry in `web/package-lock.json`; grep for `@font-face` and font files;
  inspection of the built cockpit bundle for retained license notices;
  review of runtime assets and fixture/example content for third-party
  origin.

## 1. Python dependencies

| Surface | Finding | Disposition |
| --- | --- | --- |
| Runtime | **None.** `[project]` declares no `dependencies`; the engine is standard-library only (enforced by convention and review). | ✅ Nothing to review. |
| Dev-only | `pytest>=8`, `pytest-timeout` (`[project.optional-dependencies] dev`). MIT licensed; never shipped in the wheel. | ✅ Accepted. |
| Build | `setuptools>=77`, `build` (CI only). | ✅ Accepted. |

## 2. Web (cockpit) dependencies

235 locked packages in `web/package-lock.json`. License sweep of every
installed package's `license` field:

| License | Count | Notes |
| --- | --- | --- |
| MIT / MIT-0 / ISC / BSD-2/3 / Apache-2.0 | 185 | Permissive; fine for both dev use and distribution. |
| MPL-2.0 | 2 | `axe-core` + `@axe-core/playwright` — **dev/test only** (accessibility checks in e2e). Never bundled or shipped. |
| CC-BY-4.0 | 1 | `caniuse-lite` browser-support data — **build-time only** (via browserslist). Not shipped. |
| no license field | 47 | All are *uninstalled optional platform binaries* (`@rollup/rollup-<platform>`, `@esbuild/<platform>`, `fsevents`) whose `package.json` is absent locally; the packages themselves are MIT on the registry. Not shipped. |

**Shipped production dependencies** (what `vite build` bundles into the
cockpit assets that the wheel carries): `react`, `react-dom`,
`react-router-dom` and their transitive runtime helpers (`scheduler`,
`@remix-run/router`, `loose-envify`, `js-tokens`) — **all MIT**. The built
bundle retains the upstream license headers (verified: Facebook/Meta and
Remix Software copyright notices are present in
`education_pipeline/_webdist/assets/index-*.js`), satisfying MIT's notice
requirement for distribution. ✅ Accepted.

## 3. Guide runtime assets

`education_pipeline/guide_runtime/assets/runtime.js` and `runtime.css` are
**first-party maintained source code** written for this project — no
vendored libraries, no minified third-party code, no copied snippets. The
exported `guide.html` therefore contains only first-party code plus the
course content. ✅ Accepted.

## 4. Fonts

No font files are bundled anywhere in the repository (no `woff`/`ttf`/
`otf`, no `@font-face` rules). The guide runtime, cockpit, and legacy
export all use **system font stacks** (`ui-serif`/Georgia,
`system-ui`, `ui-monospace`, etc.), so no font licensing applies and
exports make no network font requests. ✅ Nothing to review.

## 5. Copied material

- All course content in fixtures and in `examples/feedback-loops/` is
  **synthetic, written for this repository**. The example's source entry
  (`meadows-2008`, *Thinking in Systems*) is a **citation** — a title,
  author, and link used to demonstrate the source-reference feature; no
  text from the work is reproduced.
- Prompt templates and blueprint text are first-party and domain-neutral
  per `docs/extraction-manifest.md`; the extraction boundary keeps any
  privately tuned prompt libraries out of this repository.
- No code was copied from external projects into `education_pipeline/`
  or `web/src/` (review of file headers and idioms; everything is
  project-idiomatic first-party code).

✅ Accepted.

## 6. Follow-ups

None blocking. Two standing practices going forward:

1. New web dependencies must keep the shipped-bundle set permissive and
   notice-preserving (check on `npm install`, re-run the license sweep at
   the next release).
2. The Python engine stays dependency-free at runtime; any proposed
   runtime dependency needs prior discussion in an issue (existing repo
   rule).
