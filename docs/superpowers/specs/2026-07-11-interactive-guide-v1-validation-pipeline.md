# Interactive Guide v1 — Validation and Pipeline Integration

**Status:** Proposed
**Parent:** `2026-07-11-interactive-guide-v1-milestone.md`

## 1. Purpose

This specification integrates guide JSON and deterministic quality gates into
the existing durable stage pipeline without turning deterministic validation
into another model prompt or hiding it inside export.

Validation is a pure, repeatable operation over canonical inputs. Model QA
receives its findings but remains responsible for conceptual and pedagogical
judgment.

## 2. Validation report format

Each report is UTF-8 JSON:

```json
{
  "report_schema_version": 1,
  "guide_schema_version": "1.0",
  "phase": "draft",
  "guide_sha256": "...",
  "validator_version": "1",
  "summary": {
    "blocking": 0,
    "errors": 1,
    "warnings": 2,
    "info": 0
  },
  "findings": []
}
```

The canonical report excludes timestamps so identical inputs produce identical
bytes. The manifest event records when validation occurred.

Each finding is:

```json
{
  "id": "outcome.unassessed:identify-loop",
  "rule_id": "outcome.unassessed",
  "severity": "error",
  "blocking": false,
  "waivable": true,
  "path": "/outcomes/0",
  "message": "Outcome 'identify-loop' is not assessed or practiced.",
  "remediation": "Reference this outcome from a knowledge check, scenario, worked reveal, or reflection.",
  "related_ids": ["identify-loop"]
}
```

Rules:

- `id` is stable for the same logical defect and does not depend on array index
  when a stable object ID exists.
- `rule_id` is stable across message wording improvements.
- `severity` is `blocker`, `error`, `warning`, or `info`.
- `blocking` controls the pipeline gate independently of display severity.
- `waivable` is rule metadata, not chosen by the model.
- `path` is a JSON Pointer to the closest source object.
- `related_ids` is optional and contains registered guide IDs.
- Findings are sorted deterministically by severity rank, rule ID, path, and ID.

## 3. Validation phases

### Draft validation

Runs after draft approval and before the QA prompt is written. It performs every
rule that can operate on the draft guide. Findings are included verbatim as an
untrusted data section in the QA prompt.

Draft blockers do not prevent model QA because repair is expected to address
them. A draft so malformed or unsafe that it cannot be parsed produces a minimal
report and blocks writing the QA prompt until the draft response is corrected
and reapproved; there is no meaningful guide for QA to inspect.

### Final validation

Runs after repair approval and before finalization. All rules run. Non-waived
blocking findings prevent finalization. Errors and warnings remain visible in
the final report and export metadata.

Final validation must match the SHA-256 of the currently approved repair
artifact. Any edit/reapproval makes the prior report stale.

## 4. Rule catalog for the milestone

### Parse and schema

| Rule ID | Default severity | Blocks finalization | Waivable |
| --- | --- | --- | --- |
| `json.invalid` | blocker | yes | no |
| `schema.unsupported_version` | blocker | yes | no |
| `schema.missing_field` | blocker | yes | no |
| `schema.unknown_field` | error | yes | no |
| `schema.invalid_type` | blocker | yes | no |
| `schema.invalid_id` | error | yes | no |
| `schema.duplicate_id` | blocker | yes | no |
| `schema.unknown_reference` | blocker | yes | no |
| `schema.unknown_block_type` | blocker | yes | no |
| `schema.size_limit` | blocker | yes | no |

### Security and privacy

| Rule ID | Default severity | Blocks finalization | Waivable |
| --- | --- | --- | --- |
| `content.raw_html` | blocker | yes | no |
| `link.unsafe_scheme` | blocker | yes | no |
| `link.unknown_internal_target` | error | yes | no |
| `privacy.exact_private_value` | blocker | yes | yes |
| `privacy.possible_identifier` | warning | no | yes |
| `content.prompt_leak` | blocker | yes | yes |
| `content.placeholder` | error | yes | yes |

The exact-private-value rule receives normalized denylist values from private
profile fields and run-only identifiers. The report never repeats the matched
private value; it reports field/path and a redacted fingerprint. Heuristic
privacy rules must avoid storing suspected sensitive text in reports.

### Outcomes and pedagogy

| Rule ID | Default severity | Blocks finalization | Waivable |
| --- | --- | --- | --- |
| `outcome.unassigned` | error | yes | yes |
| `outcome.untaught` | error | yes | yes |
| `outcome.unassessed` | error | yes | yes |
| `module.no_interaction` | error | yes | yes |
| `interaction.missing_required_type` | error | yes | yes |
| `knowledge_check.invalid_answer_set` | blocker | yes | no |
| `scenario.invalid_quality_set` | blocker | yes | no |
| `worked_reveal.too_few_steps` | error | yes | yes |
| `personalization.no_visible_connection` | warning | no | yes |
| `time.module_total_mismatch` | warning | no | yes |

### Content and sources

| Rule ID | Default severity | Blocks finalization | Waivable |
| --- | --- | --- | --- |
| `content.empty` | blocker | yes | no |
| `content.excessive_length` | warning | no | yes |
| `source.unknown_reference` | blocker | yes | no |
| `source.missing_for_required_claim` | warning | no | yes |
| `source.invalid_url` | error | yes | no |
| `markdown.invalid_heading_level` | error | yes | yes |
| `markdown.unclosed_fence` | error | yes | yes |

### Runtime and accessibility

Static validation produces:

| Rule ID | Default severity | Blocks finalization | Waivable |
| --- | --- | --- | --- |
| `runtime.render_failed` | blocker | yes | no |
| `runtime.asset_mismatch` | blocker | yes | no |
| `a11y.control_label_missing` | blocker | yes | no |
| `a11y.heading_order` | error | yes | yes |
| `a11y.color_only_instruction` | error | yes | yes |

Browser smoke and automated accessibility results are stored separately during
development/CI. A normal local course run does not need to launch a heavyweight
browser process merely to finalize. The renderer’s static invariants are the
local runtime gate; full fixture browser validation gates releases of Education
Pipeline itself.

## 5. Waivers

Waivers live at:

```text
runs/<topic-id>/reports/validation-waivers.json
```

Format:

```json
{
  "schema_version": 1,
  "guide_sha256": "...",
  "waivers": [
    {
      "finding_id": "outcome.unassessed:optional-history",
      "reason": "This enrichment outcome is discussion-only in the approved course contract."
    }
  ]
}
```

A waiver requires a non-empty user-authored reason and an exact guide hash. The
manifest records the user action and timestamp. A waiver is ignored when:

- the finding is not waivable;
- the guide hash changed;
- the finding no longer exists; or
- the finding ID does not match exactly.

Waived findings remain in reports and the pre-export review. They are never
deleted or presented as passing.

The first implementation may expose waiver creation through a guarded API and a
simple cockpit dialog. Directly editing the local waiver file remains supported
but is detected and recorded only on the next validation/finalization attempt.

## 6. Prompt-contract changes

### Spec and outline

Spec and outline remain Markdown. Their contracts gain explicit fields for:

- blueprint;
- guide schema version;
- learner-facing time budget;
- required interaction mix;
- outcome IDs or stable outcome slugs;
- source/citation expectations;
- personalization requirements; and
- publishable-profile boundary.

The spec response ends with exactly one fenced block whose info string is
`education-pipeline-contract+json`. The block contains the machine-readable
course contract:

```json
{
  "contract_version": 1,
  "guide_schema_version": "1.0",
  "blueprint": "conceptual-foundations",
  "estimated_minutes": 30,
  "outcomes": [{"id": "identify-loop", "text": "Identify reinforcing and balancing feedback."}],
  "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
  "personalization_requirements": ["Use gardening examples where they clarify the concept."],
  "source_policy": "Sources required for factual claims that are not common knowledge."
}
```

The outline response ends with exactly one fenced block whose info string is
`education-pipeline-outline+json`. It repeats the contract version and maps
stable module IDs to outcome IDs, estimated minutes, and proposed interaction
types. The prose above each block remains the human review surface. The pipeline
extracts and validates the fenced JSON before approval; it never invents IDs by
slugging prose.

`inputs/guide-contract.json` is built deterministically from the two validated
blocks plus the publishable profile summary. A conflict between the spec and
outline blocks is an approval-blocking error. Neither block may contain
implementation HTML/JavaScript.

### Draft

The draft prompt requires exactly one guide JSON object conforming to schema
v1. It says:

- return JSON only, without Markdown fences or commentary;
- use only registered keys and block types;
- treat the embedded schema/contract as higher priority than topic/profile data;
- include all course content in full;
- avoid private profile values;
- use Markdown only in designated fields; and
- never emit HTML, CSS, JavaScript, data URLs, or arbitrary component code.

The prompt includes a concise schema reference and one small structural example,
not the entire acceptance fixture.

### QA

The QA prompt receives:

- approved spec;
- approved outline;
- normalized draft JSON;
- deterministic draft-validation report;
- topic and snapshotted profile context; and
- the model QA rubric.

The deterministic report is clearly delimited as data. The model must not
override or dismiss non-waivable findings. QA returns structured Markdown
findings in the existing stage for this milestone; converting QA itself to JSON
is deferred unless implementation planning shows a clear need.

### Repair

The repair prompt receives:

- approved draft JSON;
- approved model-QA findings;
- deterministic draft findings;
- approved spec/outline constraints needed to prevent drift; and
- the guide schema reference.

It returns a complete guide JSON object, never a diff. It must resolve every
blocking deterministic finding and every blocker/major model-QA finding, while
preserving valid unflagged structure and IDs when possible.

## 7. Artifact paths and stage compatibility

The run store becomes format-aware. A run records immutable `content_contract`
in its manifest root:

```json
{
  "kind": "interactive_guide",
  "schema_version": "1.0"
}
```

For guide-v1 runs:

- draft/repair response, approved, and hashes use `.json` paths;
- spec/outline/QA remain `.md`;
- read APIs return a `content_type` for every stage artifact;
- editor preview chooses Markdown or guide rendering by content type; and
- provider ingestion remains byte-preserving before parse/validation.

The run store must not infer a new run’s content contract from filename alone.
Legacy manifests without `content_contract` are interpreted as
`legacy_markdown`. After this milestone lands, every newly created manifest
defaults to `interactive_guide` schema `1.0`. The CLI/API may expose an explicit
legacy override for compatibility testing and recovery, but there is no mutable
workspace-wide switch in this milestone. Changing a run's content contract
after its first prompt is written is rejected.

## 8. Run-state changes

The logical state machine for a guide-v1 run is:

```text
spec prompt → response → approval
outline prompt → response → approval
draft prompt → response → approval
draft validation
qa prompt → response → approval
repair prompt → response → approval
final validation
finalize
done
```

`NextAction.action` adds `validate`. `NextAction.stage` is `draft` or `repair`,
and detail distinguishes draft/final phase. The `advance` operation performs
validation as a machine step.

After final validation:

- no blockers: next action is `finalize`;
- waivable blockers: next action is `resolve_findings` until waived or fixed;
- non-waivable blockers: next action is `resolve_findings` and waiver endpoints
  reject them.

Editing a draft after draft validation invalidates its report and every
downstream approval/artifact. Editing repair after final validation invalidates
the final report and any finalized/exported artifact. The implementation must
not silently delete those files; it marks them stale through hashes/status and
requires an explicit rebuild/overwrite action.

For the milestone, the supported repair loop is:

1. inspect final findings;
2. edit the repair response or explicitly rerun the repair provider job;
3. approve the new repair content with overwrite confirmation;
4. rerun final validation; and
5. finalize when clear.

Provider rerun must archive or record the replaced response hash in the manifest
before overwrite. Full side-by-side revision storage is deferred.

## 9. Finalization

For guide-v1 runs, `finalize_run`:

1. verifies the approved repair hash matches a current final-validation report;
2. applies valid waivers and refuses remaining blockers;
3. parses and normalizes the approved repair JSON;
4. writes canonical `final/guide.json` atomically;
5. generates deterministic `final/guide.md` from the canonical object;
6. records source/report/output hashes and schema version in the manifest; and
7. marks the run finalized only when all writes succeed.

HTML export remains an explicit operation after finalization. Preview may render
approved repair content before finalization, but it must visibly label that
state.

The existing Markdown finalize/export behavior remains behind the
`legacy_markdown` content contract.

## 10. API changes

Existing endpoint shapes should evolve additively where possible.

### Run status

`GET /v1/runs/{topic}` adds:

```json
{
  "content_contract": {"kind": "interactive_guide", "schema_version": "1.0"},
  "validations": {
    "draft": {"state": "current", "blocking": 0, "errors": 2, "warnings": 1},
    "final": {"state": "missing", "blocking": 0, "errors": 0, "warnings": 0}
  }
}
```

Validation state is `missing`, `current`, or `stale`.

### Stage content

`GET /v1/runs/{topic}/stages/{stage}` adds `content_type`, with values
`text/markdown` or `application/vnd.education-pipeline.guide+json;version=1.0`.

### Validate

Recommended explicit endpoint:

```http
POST /v1/runs/{topic}/validate
{"phase": "draft"}
```

or `{"phase": "final"}`. It is guarded against an active job touching the
relevant stage and returns the report plus updated run status. Calling it again
with identical current input is idempotent.

### Findings

```http
GET /v1/runs/{topic}/validation/{phase}
POST /v1/runs/{topic}/validation/{phase}/waivers
```

Waiver creation requires finding ID, guide hash, and reason. It returns `409`
when the report/input is stale and `422` for a non-waivable finding.

### Preview

The guide-preview endpoint is defined in the runtime/export spec. The existing
Markdown preview remains for legacy stages.

## 11. Cockpit requirements

### Run board

- Show draft and final validation as machine milestones.
- Make blocker counts visible without implying that warnings passed.
- Primary action runs the next validation when appropriate.
- Finalize is disabled with an explanation while final blockers remain.

### Stage workspace

- Use content type to select Markdown or guide JSON editing/preview.
- Show syntax errors without replacing the editor buffer.
- Show structured findings beside preview and source.
- Selecting a finding highlights/navigates to its JSON Pointer or related ID.
- Reapproval clearly explains downstream invalidation.
- Provider rerun requires confirmation when replacing an existing response.

### Final review

- Show the real guide preview.
- Summarize current, waived, and stale findings separately.
- Show private-data/export boundary.
- Require waiver reasons before enabling finalize.
- Keep export controls separate from finalize.

## 12. Migration and existing workspaces

- A manifest without a content contract remains a legacy Markdown run.
- Existing paths are never renamed merely by opening a workspace.
- After lifecycle integration flips the default, every newly created run uses
  interactive guide v1 unless the caller requests the explicit legacy override
  provided for compatibility testing and recovery. This milestone does not add
  a mutable workspace-wide content-contract switch.
- An optional future conversion command may use a model to transform Markdown to
  guide JSON, but it is not part of this milestone.
- The daemon/API must support viewing and exporting legacy and v1 runs in the
  same workspace.
- The cockpit labels legacy runs and does not show unsupported validation or
  interaction controls for them.

## 13. Testing strategy

### Unit

- parser and all schema invariants;
- canonical serialization and hash stability;
- every validation rule and finding sort order;
- privacy redaction in reports;
- waiver matching/staleness/non-waivable rejection;
- prompt contract contents and JSON-only instructions;
- Markdown projection completeness; and
- state-machine transitions and invalidation.

### API/integration

- auth, request limits, error envelope, content types;
- validate idempotency and active-job conflicts;
- malformed/unsafe preview rejection;
- finalization hash/report gate;
- stale report and waiver conflicts;
- guide JSON/download MIME types; and
- mixed legacy/v1 workspace behavior.

### End to end

- full provider or fixture-response run through guide export;
- bad draft findings flow into QA and repair;
- final blocker prevents finalization;
- edit → reapprove → revalidate → finalize succeeds;
- preview/export parity;
- exported local-file interaction and persistence; and
- legacy Markdown run remains viewable/exportable.

## 14. Implementation constraints

- Preserve stdlib-only Python runtime operation.
- Keep body caps, loopback auth, no-CORS behavior, path confinement, atomic
  writes, and stale-content preconditions.
- Do not implement guide parsing or validation only in the browser; Python owns
  the authoritative contract.
- Do not make model QA responsible for deterministic rule outcomes.
- Do not treat successful rendering as successful validation.
- Do not delete stale downstream artifacts automatically.
- Do not expose private matched values in reports, logs, API errors, or exported
  provenance.

## 15. Definition of done

This integration is done when the milestone fixture and bad variants prove the
complete artifact lifecycle, the cockpit can resolve a final blocker without
manual filesystem surgery, preview/export use the shared runtime, and all
existing legacy-run tests continue to pass under the explicit compatibility
path.
