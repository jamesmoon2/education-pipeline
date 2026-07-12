# Interactive Guide v1 — Wave 5 API Freeze

The Wave 5 daemon contract is additive. Existing legacy fields and
`POST /v1/preview` remain unchanged.

- Run status adds `content_contract` and `validations`. Each validation phase
  has `state` (`missing`, `current`, or `stale`) plus integer `blocking`,
  `errors`, and `warnings` counts. Legacy runs report the legacy contract and
  two missing, zero-count phases.
- Stage content adds `content_type`: `text/markdown` or
  `application/vnd.education-pipeline.guide+json;version=1.0`.
- `POST /v1/runs/{topic}/validate` accepts `{ "phase": "draft" | "final" }`
  and returns `{ state, report, status }`.
- `GET /v1/runs/{topic}/validation/{phase}` returns `{ state, report }`.
- `POST /v1/runs/{topic}/validation/{phase}/waivers` accepts `finding_id`,
  exact `guide_sha256`, and non-empty `reason`; it returns `{ waivers, state,
  report }`.
- `POST /v1/guide-preview` accepts guide JSON text and returns `{ html,
  content_sha256, validation: { blocking, errors, warnings } }`.

Malformed request JSON and malformed guide JSON use HTTP 400. Missing resources
use 404, stale hashes/reports use 409, and safe but unrenderable guides or
non-waivable findings use 422 through the standard error envelope.
