# Grading Rubric Studio — Verification & Validation Plan

**Version**: 0.3.0
**Date**: 2026-04-16
**Status**: Codebase alignment pass — test counts, line numbers, new test groups documented, IT-SYS table rewritten to match actual 10 tests
**Author**: Wiktor Lisowski

---

## § 1  Test strategy

### Test-level discipline

Each test level validates requirements at the corresponding abstraction level:

| Requirement level | Test level | Scope |
|---|---|---|
| Design Requirements (DR) | Unit tests | Single function / class, deterministic, offline |
| System Requirements (SR) | Integration tests | Multi-stage pipeline or system-level wiring |
| User Requirements (UR) | Acceptance tests | Teacher-facing procedures (manual or Playwright) |
| User Needs (UN) | Validation | Holistic judgement against the three User Needs |

### Auto vs manual split

| Level | Automated | Manual |
|---|---|---|
| Unit (§ 2) | All — `pytest`, offline, deterministic | — |
| Integration (§ 3) | § 3.1 stage chain (stub gateway), § 3.3 DR-INT wiring | § 3.4 system integration (requires live Validance) |
| Acceptance (§ 4) | § 4.2 Playwright E2E (if time permits) | § 4.1 manual UI procedures |
| Validation (§ 5) | — | Inspecting final output + Review screen experience |

### Environments

| Environment | What runs | External dependencies |
|---|---|---|
| **Offline** (CI, laptop) | Unit tests + § 3.1 + § 3.3 | None — no API key, no Validance, no network |
| **Production** (Validance running) | § 3.4 system integration, § 4.1 / § 4.2 acceptance | Validance at `https://api.validance.io`, Anthropic API key |

### Integration test sub-levels

"Integration" splits into two distinct sub-levels:

**(a) L1 offline stage chain** (§ 3.1) — exercises the full pipeline with a stub gateway. Verifies SRs without requiring Validance. All LLM interaction goes through canned responses. This is the primary automated SR-level test.

**(b) System integration** (§ 3.4) — requires a live Validance instance. Verifies that the L3 wiring works end-to-end: workflow registration, proposal submission, **full workflow execution producing a valid `ExplainedRubricFile`**, approval gate round-trip, audit bundle retrieval, re-measurement loop re-entry. Exercises both SRs and DR-INT wiring in a real environment.

**Pragmatic exception — § 3.3**: the DR-INT wiring tests (`test_workflows.py`, `test_harvester.py`) are physically in the `tests/integration/` directory and cross module boundaries (importing from both L1 and L3), but they trace to DRs rather than SRs — they verify our wiring shapes, not system-level behavior.

### External dependency boundary

External dependencies (Validance, Anthropic API, krippendorff library) are trusted, not re-tested. Our tests verify that *we call them correctly*. See § 6 for the full boundary definition. Live API calls are **never** made in automated tests — all LLM interaction goes through the stub gateway in offline mode.

---

## § 2  Unit tests (↔ DR) — automated, offline, deterministic

### § 2.1  Metrics math

Deterministic functions with exact assertions. No LLM calls, no network, no randomness.

| Test ID | Function under test | Location | Inputs | Expected output | Traced DR(s) |
|---|---|---|---|---|---|
| UT-MET-01 | `_confidence_floor()` | `simulation.py:316` | `EvidenceProfile` with `synthetic_responses_used=True`, base score 0.85 | Floor clamped to LOW range (≤ 0.40) | DR-AS-13 |
| UT-MET-02 | `_confidence_floor()` | `simulation.py:316` | `EvidenceProfile` with real copies, base score 0.85 | No clamping (returns base) | DR-AS-13 |
| UT-MET-03 | `AmbiguityEngine.measure_from_simulation()` | `engines.py` | Grade matrix with midscale persona disagreement | Ambiguity finding with `method=LLM_PANEL_AGREEMENT` | DR-AS-06 |
| UT-MET-04 | `ApplicabilityEngine.measure_from_simulation()` | `engines.py` | Grade matrix with edge polarization | Applicability finding with `method=SYNTHETIC_COVERAGE` | DR-AS-07 |
| UT-MET-05 | `scores_from_simulation()` ambiguity guard | `engines.py` | Trivial ceiling/floor grades and too few midscale responses | Ambiguity score confidence forced LOW | DR-AS-06 |
| UT-MET-06 | `DiscriminationEngine.measure_from_simulation()` | `engines.py` | Synthetic intended scores with ceiling effect and rank collapse | Discrimination finding from calibration / ceiling / rank checks | DR-AS-08 |
| UT-MET-07 | `scores_from_simulation()` | `engines.py` | Complete `SimulationEvidence` grade matrix | Three `CriterionScore` records with `method=GRADER_SIMULATION` | DR-SCR-01, DR-SCR-02 |
| UT-MET-08 | `_step2_canonical_order()` | `stage.py:218` | Drafts: `[REMOVE_NODE, ADD_NODE, REPLACE_FIELD]` | Sorted: `[REPLACE_FIELD, ADD_NODE, REMOVE_NODE]` | DR-IM-07 |
| UT-MET-09 | `_step1_conflict_resolution()` | `stage.py:205` | Drafts: `[REMOVE_NODE(X), REPLACE_FIELD(X.desc)]` | `REPLACE_FIELD` superseded, `REMOVE_NODE` kept | DR-IM-07 |
| UT-MET-10 | `_step3_apply_and_wrap()` | `stage.py:393` | Starting rubric + one `REPLACE_FIELD` draft | `application_status=APPLIED`, `teacher_decision=PENDING`, rubric updated | DR-IM-07 |
| UT-MET-11 | `_step3_apply_and_wrap()` superseded draft | `stage.py:393` | Draft marked as superseded by step 1 | `application_status=NOT_APPLIED` | DR-IM-07 |

**NOTE — Krippendorff's α**: The inter-rater agreement computation is delegated to the pinned `krippendorff>=0.6` PyPI library. Statistical correctness is trusted (published, peer-reviewed algorithm). We test only that we call it with the correct input shape (see § 6).

**NOTE — Applicability coverage ratio**: Currently a simple heuristic (description length + scoring_guidance presence), not a formal formula. If DR-AS-07's ratio is implemented as a closed-form metric later, add a test case here.

### § 2.2  Stage logic (stub gateway, canned responses)

Each stage's deterministic offline path exercised with a stub gateway returning canned JSON.

| Test ID | Stage | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-STG-01 | `assess` | Canned gateway responses → findings assembled correctly | DR-AS-01 through DR-AS-04 |
| UT-STG-02 | `assess` | Empty rubric (no starting rubric) → degenerate `AssessOutputs` | DR-AS-15 |
| UT-STG-03 | `propose` | Modify-existing path → drafts → applied changes | DR-IM-02, DR-IM-07 |
| UT-STG-04 | `propose` | Generate-from-scratch path → generated rubric | DR-IM-02 |
| UT-STG-05 | `propose` | Empty-improvement path → `PlannerDecision.NO_CHANGES_NEEDED` | DR-IM-02, DR-IM-05 |
| UT-STG-06 | `score` | Findings → severity-weighted criterion scores | DR-SCR-01, DR-SCR-02 |
| UT-STG-07 | `render` | `ExplainedRubricFile` assembled from pipeline outputs | DR-DAT-07 |
| UT-STG-08 | `propose` | `source_findings` on each draft traces back to an `AssessmentFinding.id` | DR-IM-03, DR-IM-09, DR-IM-13 |
| UT-STG-09 | `propose` | Grounding pass: draft contradicting teaching material → `CONTRADICTS` | DR-IM-06 |

### § 2.3  Data model validation (Pydantic invariants)

Existing `test_models.py` coverage (29 tests). Representative cases:

| Test ID | Model | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-MOD-01 | `ConfidenceIndicator` | Valid construction + round-trip serialization | DR-DAT-06 |
| UT-MOD-02 | `Rubric` | Required fields present, invariants hold | DR-DAT-01 |
| UT-MOD-03 | `ProposedChange` | Discriminated union deserialization (all 5 operation types) | DR-IM-02 |
| UT-MOD-04 | `EvidenceProfile` | `synthetic_responses_used` flag | DR-AS-06 |
| UT-MOD-05 | `ExplainedRubricFile` | Full schema round-trip | DR-DAT-07 |
| UT-MOD-06 | `ExplainedRubricFile` | Schema validation against documented shape | DR-DAT-03 |

Existing `test_hashing.py` coverage (17 tests):

| Test ID | Function | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-HSH-01 | `hash_file()` | Known content → SHA-256 match | DR-DAT-06 case (a) |
| UT-HSH-02 | `hash_text()` | UTF-8 encoding → SHA-256 match | DR-DAT-06 case (b) |
| UT-HSH-03 | `canonical_json()` | Sort keys, compact separators, ensure_ascii=False | DR-DAT-06 case (c) |
| UT-HSH-04 | `hash_object()` | Object → canonical JSON → SHA-256 match | DR-DAT-06 case (c) |

Existing `test_audit_emitter.py` coverage (12 tests):

| Test ID | Class | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-AUD-01 | `JsonLineEmitter` | Event serialization to JSONL | DR-OBS-01 |
| UT-AUD-02 | `NullEmitter` | No-op emitter (offline mode) | DR-OBS-01 |
| UT-AUD-03 | `JsonLineEmitter` | LLM call event records purpose, prompt ID, outcome | DR-LLM-08, DR-LLM-11 |
| UT-AUD-04 | `NullEmitter` | Collects events in memory | DR-OBS-01 |
| UT-AUD-05 | `NullEmitter` | No side effects | DR-OBS-01 |
| UT-AUD-06 | `JsonLineEmitter` | LLM call failure outcome recorded | DR-LLM-08 |

Existing `test_proposals.py` coverage (10 tests):

| Test ID | Class | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-PRP-01 | `ForwardMapping` | L1 models → Validance proposal payload | DR-INT-04 |
| UT-PRP-02 | `InverseMapping` | Validance result → L1 models | DR-INT-04 |

Existing `test_llm_integration.py` coverage (4 tests):

| Test ID | Function | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-LLM-01 | `_rubric_to_text()` | Rubric text contains criterion names | DR-AS-04 |
| UT-LLM-02 | `_collect_criterion_paths()` | Collects all leaf criterion paths | DR-AS-06 |
| UT-LLM-03 | `_convert_and_ground()` | Valid draft converts to `ProposedChange` | DR-IM-06, DR-IM-07 |
| UT-LLM-04 | `_convert_and_ground()` | Draft referencing unknown finding is dropped | DR-IM-06 |

Existing `test_ingest_input_root.py` coverage (12 tests):

| Test ID | Class | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-INP-01 | `StructuredInputAdapter` | Minimal exam-only input root | DR-IO-01 |
| UT-INP-02 | `StructuredInputAdapter` | All roles populated (exam, teaching, rubric, copies) | DR-IO-01, DR-IO-02 |
| UT-INP-03 | `StructuredInputAdapter` | Missing exam question directory fails | DR-IO-01 |
| UT-INP-04 | CLI mutual exclusion | `--input` and `--input-root` together fails | DR-ARC-08 |
| UT-INP-05 | CLI mutual exclusion | Neither `--input` nor `--input-root` fails | DR-ARC-08 |
| UT-INP-06 | `StructuredInputAdapter` | File order is deterministic | DR-IO-01 |

Existing `test_simulation.py` coverage (12 tests):

| Test ID | Function | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-SIM-01 | `_require_llm()` | Stub backend fails with clear message | DR-AS-03 |
| UT-SIM-02 | `AmbiguityEngine.measure_from_simulation()` | Ambiguity findings from grade matrix | DR-AS-06 |
| UT-SIM-03 | `ApplicabilityEngine.measure_from_simulation()` | Applicability gap findings | DR-AS-07 |
| UT-SIM-04 | `DiscriminationEngine.measure_from_simulation()` | Discrimination findings | DR-AS-08 |
| UT-SIM-05 | `scores_from_simulation()` | Three criterion scores produced | DR-SCR-01, DR-SCR-02 |
| UT-SIM-06 | `run_grader_simulation()` | Injected gateway produces grade entries | DR-AS-03, DR-LLM-01 |

Existing `test_stage_logic.py` coverage (11 tests):

| Test ID | Stage | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-SLG-01 | `assess` | Empty rubric → degenerate `AssessOutputs` | DR-AS-15 |
| UT-SLG-02 | `parse_inputs` | Inline rubric text parsed | DR-IO-07 |
| UT-SLG-03 | `propose` | Modify-existing path with stub gateway | DR-IM-02 |
| UT-SLG-04 | `propose` | From-scratch path with stub gateway | DR-IM-02 |
| UT-SLG-05 | `propose` | No-changes path | DR-IM-05 |

Existing `test_settings.py` coverage (9 tests):

| Test ID | Class | Scenario | Traced DR(s) |
|---|---|---|---|
| UT-SET-01 | `Settings` | Construction from env vars (defaults) | DR-ARC-03 |
| UT-SET-02 | `Settings` | Frozen after construction | DR-ARC-03 |
| UT-SET-03 | `Settings` | Model pin validation (ocr_backend/ocr_model, simulation_backend/simulation_model) | DR-LLM-06 |

### § 2.4  Architectural invariants

**Reclassified from `tests/acceptance/` → unit level.** These are deterministic, offline, grep-based structural checks that verify Design Requirements — not teacher-facing acceptance criteria.

Existing `test_architecture.py` (6 tests):

| Test ID | Test | Assertion | Traced DR(s) |
|---|---|---|---|
| UT-ARC-01 | `test_no_validance_imports_in_l1` | `grep -rn "import validance" grading_rubric/` returns empty | DR-ARC-07 |
| UT-ARC-02 | `test_model_files_in_expected_locations` | Stage-local models in their packages | DR-DAT-01 |
| UT-ARC-03 | `test_no_py_files_in_frontend_src` | No `.py` files in `frontend/src/` | DR-UI-01 |
| UT-ARC-04 | `test_l3_files_present` | L3 files in `validance_integration/` | DR-INT-01 |
| UT-ARC-06 | `test_layer_separation` | L1/L2/L3/L4 boundaries intact | DR-ARC-01 |

### § 2.5  DR group coverage summary

Every DR group has a verification strategy. Representative unit-level procedures per group:

| DR group | Count | Representative tests | Coverage notes |
|---|---|---|---|
| DR-ARC (12) | UT-ARC-01–06, UT-SET-01–02, UT-INP-04/05 | Layer separation, hermetic tasks, frozen settings, CLI mutual exclusion | DR-ARC-08 (CLI subcommands) exercised via § 3.1 stage chain |
| DR-LLM (11) | UT-AUD-03/06, UT-SET-03, UT-LLM-01–04 | Gateway contract, model pin, call logging, rubric helpers, grounding | DR-LLM-01/02 (gateway signature, prompt files) verified structurally |
| DR-DAT (11) | UT-MOD-01–06, UT-HSH-01–04 | Model round-trip, hashing rule, schema validation | DR-DAT-03 (codegen) is a gap — see § 3.2 |
| DR-AS (15) | UT-MET-01–06, UT-STG-01–02, UT-SIM-01–06 | Engines, confidence floor, degenerate assess, simulation wiring | DR-AS-09 (pairwise consistency) via UT-MET-06 sub-method |
| DR-IM (14) | UT-MET-08–11, UT-STG-03–05/08–09, UT-LLM-03/04, UT-SLG-03–05 | Three-step pipeline, three paths, traceability, grounding | DR-IM-10 (idempotency) verified by canonical sort determinism |
| DR-UI (8) | UT-ARC-03 | No `.py` in frontend, tech stack isolation | Remaining DR-UI verified via § 4.1 manual procedures |
| DR-IO (8) | UT-INP-01–06, UT-SLG-02 | Role-tagged ingest, inline-text, no-text-PDF policy, structured input adapter | DR-IO-04/05 (handwritten OCR) via IT-CHN-01 with canned responses |
| DR-OBS (4) | UT-AUD-01–06 | Event serialization, emitter contract, LLM call logging, failure recording | DR-OBS-03/04 via § 3.4 IT-SYS-08 (stage event emission) |
| DR-PER (8) | — | Not unit-testable (concurrency, scale, progress) | DR-PER-03/04/06 via § 3.1 IT-CHN-04; DR-PER-07 via § 3.4 IT-SYS-05 |
| DR-SCR (2) | UT-MET-07, UT-STG-06, UT-SIM-05 | Severity-weight aggregation, criterion scores | — |
| DR-DEP (9) | UT-ARC-06 | Layer boundaries, Docker image separation | — |
| DR-INT (9) | UT-PRP-01/02, IT-WRK-01–03, IT-HRV-01–02 | Payload mapping, workflow definitions, harvester | DR-INT-06 (approval gate) via § 3.4 IT-SYS-05 |

---

## § 3  Integration tests (↔ SR)

### § 3.1  L1 stage chain (stub gateway, offline)

Full pipeline exercised end-to-end with a stub gateway. No Validance, no API key. This is the primary automated SR-level test — it verifies that the pipeline stages compose correctly.

| Test ID | Scenario | Pipeline path | Expected result | Traced SR(s) |
|---|---|---|---|---|
| IT-CHN-01 | **Modify-existing** (happy path) | ingest → parse → assess → propose → score → render | `ExplainedRubricFile` with `application_status=APPLIED` changes, three quality scores, explanation grouped by criteria | SR-IN-01, SR-IN-03, SR-IN-09, SR-AS-01, SR-AS-02, SR-AS-03, SR-AS-07, SR-IM-01, SR-IM-02, SR-IM-03, SR-OUT-01, SR-OUT-02, SR-OUT-03 |
| IT-CHN-02 | **Generate-from-scratch / empty rubric** | ingest (no starting rubric) → parse → assess (degenerate) → propose (generator path) → score → render | `ExplainedRubricFile` with generated rubric, one HIGH applicability finding, explanation | SR-IN-05, SR-AS-02, SR-IM-01, SR-IM-02, SR-OUT-01 |
| IT-CHN-03 | **Empty-improvement / no changes needed** | ingest → parse → assess (no findings) → propose (`NO_CHANGES_NEEDED`) → score → render | `ExplainedRubricFile` with unchanged rubric, empty `proposed_changes`, explanation | SR-IM-06, SR-OUT-01 |
| IT-CHN-04 | **Partial evidence** (no copies) | ingest (exam + rubric, no copies) → full pipeline | `synthetic_responses_used=True`, confidence indicators reflect LOW range, `evidence_profile` recorded | SR-AS-06, SR-AS-08, SR-IN-09 |
| IT-CHN-05 | **Teaching material grounding** | ingest (exam + rubric + teaching material) → full pipeline | Proposed changes grounded in teaching material; no contradictions | SR-AS-04, SR-IM-04 |
| IT-CHN-06 | **Partial input parsing failure** | ingest with one corrupt PDF + valid exam | Pipeline continues with usable subset; parsing failure surfaced | SR-IN-08 |
| IT-CHN-07 | **Change-to-finding traceability** | Full pipeline → inspect `proposed_changes` | Each `ProposedChange.source_findings` traces to an `AssessmentFinding.id` | SR-IM-05 |
| IT-CHN-08 | **Schema validation** | Full pipeline → validate output against documented JSON schema | `ExplainedRubricFile` conforms to schema | SR-OUT-04 |
| IT-CHN-09 | **Pairwise consistency** | Assess with student copies → inspect discrimination findings | Pairwise inconsistencies reported as discrimination findings; cross-linked ambiguity findings when warranted | SR-AS-10 |

### § 3.1b  Shared grader simulation E2E (stub gateway, offline)

Existing `test_llm_e2e.py` coverage (4 tests). Exercises the full pipeline with a `SmartStubBackend` that dispatches schema-aware canned responses for each gateway call type (synthesis, grading, pairwise, planner). Verifies simulation-backed findings, quality scores, and artifact persistence.

| Test ID | Scenario | Expected result | Traced SR(s) |
|---|---|---|---|
| IT-E2E-01 | Full pipeline with student copies | `ExplainedRubricFile` with three `GRADER_SIMULATION` scores, simulation-derived findings, at least one APPLIED change | SR-AS-01, SR-AS-02, SR-AS-03, SR-IM-01, SR-IM-03, SR-OUT-01 |
| IT-E2E-02 | Stub backend with no API key | `RuntimeError("grader simulation requires")` | DR-AS-03 |
| IT-E2E-03 | No student copies → synthetic path | `synthetic_responses_used=True`, findings still produced | SR-AS-06 |
| IT-E2E-04 | Artifact directory persistence | Stage outputs, simulation evidence, grade matrix, pairwise comparisons, grade distribution all persisted | DR-OBS-01 |

### § 3.2  Schema round-trip (DR-DAT-03)

**STATUS: GAP** — codegen (`make schemas`) is not yet implemented. TypeScript types in `frontend/src/lib/types.ts` are hand-typed.

**Interim check**: structural comparison of Pydantic model exports (field names, types, optionality) vs hand-typed TypeScript shapes. This is a manual inspection, not an automated test.

| Test ID | Check | Status | Traced DR(s) |
|---|---|---|---|
| IT-SCH-01 | Pydantic model fields match TypeScript type fields | **Interim** — manual structural comparison | DR-DAT-03 |
| IT-SCH-02 | `make schemas && git diff --exit-code` (codegen drift detection) | **Planned** — blocked on `make schemas` implementation | DR-DAT-03, DR-UI-01 |

When codegen lands: full Pydantic → JSON Schema → TypeScript drift detection via `make schemas && git diff --exit-code` in CI.

### § 3.3  DR-INT wiring tests (existing, reclassified context)

These are DR-level contract tests using the `validance-sdk` API locally. They verify *our* wiring shapes (task names, dependencies, gate types), not Validance primitives. They are physically in the `tests/integration/` directory and cross module boundaries (importing from both L1 and L3), but trace to DRs rather than SRs — they verify our wiring shapes, not system-level behavior.

Existing `test_workflows.py` (10 tests):

| Test ID | Test | Assertion | Traced DR(s) |
|---|---|---|---|
| IT-WRK-01 | `assess_and_improve` workflow | Correct task names, dependencies, gate types | DR-INT-02 |
| IT-WRK-02 | Workflow registry | Workflow registered, description present | DR-INT-02 |

Existing `test_harvester.py` (6 tests):

| Test ID | Test | Assertion | Traced DR(s) |
|---|---|---|---|
| IT-HRV-01 | `harvest_audit_bundle()` | Returns typed `AuditBundle` from raw Validance audit chain | DR-INT-05 |
| IT-HRV-02 | Protocol compliance | Harvester implements the expected protocol shape | DR-INT-05 |

### § 3.4  System integration (Validance running)

Requires the Validance production API (`https://api.validance.io`). These tests exercise the full L3 wiring in a real environment, including **running the actual `assess_and_improve` workflow end-to-end** and verifying the output.

| Test ID | Scenario | Steps | Expected result | Traced SR(s) / DR(s) |
|---|---|---|---|---|
| IT-SYS-01 | Workflow registration | `python -m validance_integration.register` | Workflow visible in Validance catalog | DR-INT-02 |
| IT-SYS-02 | Proposal submission | `POST /api/proposals` with `assess_and_improve` payload | Proposal accepted, run starts | DR-INT-04, SR-IM-01 |
| IT-SYS-03 | All six tasks succeed | Wait for run completion, inspect task statuses | All tasks have `status=completed` | DR-INT-02, SR-PRF-01 |
| IT-SYS-04 | Workflow completes successfully | Full run reaches `completed` status | Run status is `completed` | DR-INT-02 |
| IT-SYS-05 | Status endpoint returns tasks | Poll `GET /api/runs/{runId}` | Status transitions visible, task list populated | DR-INT-06, SR-PRF-02 |
| IT-SYS-06 | **ExplainedRubricFile downloadable** | Retrieve final output from render task | Valid `ExplainedRubricFile` JSON | SR-OUT-01, SR-OUT-02, DR-INT-04 |
| IT-SYS-07 | **Intermediate outputs available** | Retrieve assess, propose outputs from completed tasks | Stage outputs are downloadable JSON | DR-INT-05, SR-OBS-01 |
| IT-SYS-08 | **Ingest emits stage events** | Inspect ingest task audit events | Stage start/end events present | DR-OBS-01, DR-OBS-03 |
| IT-SYS-09 | Run appears in listing | `GET /api/runs` | Submitted run visible in run listing | DR-INT-06 |
| IT-SYS-10 | Missing input file fails task | Submit with non-existent file path | Task fails with clear error | DR-IO-01 |

---

## § 4  Acceptance tests (↔ UR) — teacher-facing only

### § 4.1  Manual UI procedures

Each procedure row: **step #** | **user action** | **expected result** | **PASS/FAIL** | **evidence**.

Evidence = screenshot filename or "—" if not yet captured. Error/empty-state screenshots are included alongside happy-path.

**Prerequisite**: § 3.4 IT-SYS-06 (full workflow execution) must PASS before acceptance procedures begin. Acceptance tests verify the *teacher experience*, not whether the pipeline produces output.

#### INPUT SCREEN

Realizes: UR-01 (exam question), UR-02 (teaching material), UR-03 (starting rubric), UR-04 (student copies), UR-05 (trigger).

**Procedure AT-INP-01: Happy path — all four inputs provided**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | Navigate to the application URL | Input screen loads with four input fields and *Build my rubric* button | | |
| 2 | Paste exam question text into the exam question field | Field accepts text, no validation error | | |
| 3 | Upload teaching material PDF | File accepted, filename displayed | | |
| 4 | Paste existing rubric into the rubric field | Field accepts text | | |
| 5 | Upload 3 student copy PDFs | Files accepted, filenames displayed | | |
| 6 | Click *Build my rubric* | Navigates to Running screen, progress indicator appears | | |

**Procedure AT-INP-02: Minimal input — exam question only**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | Navigate to the application URL | Input screen loads | | |
| 2 | Paste exam question text | Field accepts text | | |
| 3 | Leave teaching material, rubric, and student copies empty | No validation error on optional fields | | |
| 4 | Click *Build my rubric* | Navigates to Running screen (generate-from-scratch path) | | |

**Procedure AT-INP-03: Error state — no exam question**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | Navigate to the application URL | Input screen loads | | |
| 2 | Leave all fields empty | — | | |
| 3 | Click *Build my rubric* | Validation error: exam question is required. Does NOT navigate away. | | |

#### RUNNING SCREEN

The Running screen realizes **SR-PRF-02** (visible progress signal) and **SR-OBS-01** (audit-chain handle). It does **not** realize any UR — it is an operational prerequisite, not a teacher acceptance criterion.

**Procedure AT-RUN-01: Progress visibility**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | (Triggered by AT-INP-01 step 6) | Running screen displays | | |
| 2 | Observe progress indicator | Stage labels update as pipeline progresses (e.g., "Assessing…", "Proposing…") | | |
| 3 | Wait for pipeline completion | Screen transitions to Review screen automatically or shows completion state | | |

#### REVIEW SCREEN

Realizes: UR-06 (view changes with criterion + rationale), UR-07 (accept/reject individually), UR-09 (download JSON).

**Procedure AT-REV-01: View and interact with proposed changes**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | (Arrived from Running screen) | Review screen shows suggested changes list + side-by-side rubric diff | | |
| 2 | Click on a proposed change | Change detail shows: criterion, rationale, severity, confidence | | |
| 3 | Click *Why?* affordance on a change | Shows: paraphrased finding, evidence type with synthetic flag, confidence rationale | | |
| 4 | Click *Accept* on the first change | Change status updates to ACCEPTED | | |
| 5 | Click *Reject* on the second change | Change status updates to REJECTED | | |
| 6 | Observe quality scores strip | Three criterion scores displayed (Ambiguity, Applicability, Discrimination Power) | | |

**Procedure AT-REV-02: Download JSON**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | (On Review screen with changes accepted/rejected) | *Download JSON* button visible | | |
| 2 | Click *Download JSON* | Browser downloads `ExplainedRubricFile` JSON | | |
| 3 | Open downloaded JSON | Valid JSON with `improved_rubric`, `explanation`, `proposed_changes` with `teacher_decision` reflecting step 4/5 choices, `quality_scores` | | |

**Procedure AT-REV-03: Empty state — no changes proposed**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | (Pipeline completed with `NO_CHANGES_NEEDED`) | Review screen shows "no changes proposed" message | | |
| 2 | Observe quality scores | Scores reflect no issues found | | |
| 3 | Click *Download JSON* | JSON with unchanged rubric, empty `proposed_changes` | | |

**Procedure AT-REV-04: Audit bundle access**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | (On Review screen) | *View audit bundle* link visible | | |
| 2 | Click *View audit bundle* | Opens `AuditBundle` JSON (via `GET /api/runs/{runId}/audit_bundle`) | | |
| 3 | Inspect audit bundle | Contains operation records with timestamps and event data | | |

#### RE-MEASUREMENT LOOP (UR-08) — dedicated cross-screen procedure

This is the most complex teacher workflow. It exercises the `ApprovalGate` integration, the iteration counter (`max_iterations=3`), before/after quality scores, and the `was:` annotations on changes.

**Procedure AT-LOOP-01: Full re-assessment cycle**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | Complete AT-INP-01 (provide all inputs) | Arrives at Running screen | | |
| 2 | Wait for pipeline completion | Arrives at Review screen with proposed changes | | |
| 3 | Note the quality scores (before) | Record: Ambiguity = ___, Applicability = ___, Discrimination = ___ | | |
| 4 | Accept 2 changes, reject 1 change | Status updates on each change | | |
| 5 | Click *Re-assess after my edits* | Navigates back to Running screen | | |
| 6 | Observe Running screen | Progress indicator shows assess + propose stages running again | | |
| 7 | Wait for re-assessment completion | Arrives at Review screen again | | |
| 8 | Note the quality scores (after) | Fresh scores are shown; previous scores preserved as `previous_quality_scores`; before/after evidence is visible | | |
| 9 | Verify `was:` annotations | Changed criteria show previous values alongside current values | | |
| 10 | Verify iteration count | Iteration indicator shows 2 (or equivalent) | | |
| 11 | Download JSON | `ExplainedRubricFile` contains `previous_quality_scores` and updated `proposed_changes` | | |

**Procedure AT-LOOP-02: Max iterations guard**

| Step | User action | Expected result | Result | Evidence |
|---|---|---|---|---|
| 1 | Complete AT-LOOP-01 through step 7 (iteration 2) | On Review screen, iteration 2 | | |
| 2 | Accept/reject changes, click *Re-assess* | Iteration 3 runs | | |
| 3 | On iteration 3's Review screen | *Re-assess after my edits* button is **disabled** (max_iterations=3 reached) | | |

### § 4.2  Playwright E2E (if time permits)

Automated equivalents of § 4.1 procedures. Priority order:

1. AT-INP-01 + AT-REV-01 + AT-REV-02 (happy path end-to-end)
2. AT-LOOP-01 (re-measurement loop)
3. AT-INP-03 (error state)
4. AT-REV-03 (empty state)

---

## § 5  Validation (↔ UN)

Validation assesses whether the system fulfils the three User Needs. This is a holistic judgement, not a pass/fail test. The evaluator inspects the final `ExplainedRubricFile` JSON output and the Review screen experience.

| UN | Need | Validation criteria | Evidence artifact | Reviewer | Notes |
|---|---|---|---|---|---|
| UN-01 | Teacher gets a high-quality rubric for fair and fast grading | The improved rubric is structurally complete (criteria, point allocations, scoring guidance), addresses the exam question, and reflects the teaching material when provided. A domain expert can confirm the rubric would produce consistent grading across graders. | Downloaded `ExplainedRubricFile` JSON + Review screen screenshot | | |
| UN-02 | Teacher trusts and understands proposed changes | Each proposed change on the Review screen has a clear criterion, rationale, and *Why?* explanation. The teacher can make an informed accept/reject decision without needing to understand the system's internals. Confidence indicators honestly reflect evidence quality (synthetic vs real copies). | Review screen screenshots (change detail + *Why?* affordance) | | |
| UN-03 | Portable JSON artifact for graders | The downloaded `ExplainedRubricFile` JSON is self-contained, includes the improved rubric, explanation, and provenance. It can be shared with graders without requiring access to the application. The schema is documented and stable. | Downloaded JSON file + schema documentation | | |

---

## § 6  External dependency coverage (what we test vs what we trust)

### Validance primitives (trusted)

ApprovalGate, audit chain, workflow orchestration, secret store, task execution, REST API, SDK (`Task`, `Workflow`, `definition_hash`). Validance has its own test suite. We do not re-test these.

### Our wiring to Validance (tested)

| What | Test ref | Traced DR(s) |
|---|---|---|
| Proposal-payload mapping (L1 → Validance shapes) | `test_proposals.py` (UT-PRP-01/02) | DR-INT-04 |
| Polling cadence / status mapping (SPA label table) | § 3.4 IT-SYS-05 | DR-INT-06 |
| Workflow definitions (task names, deps, gates) | `test_workflows.py` (IT-WRK-01/02) | DR-INT-02 |
| Audit-bundle harvester (raw chain → typed view) | `test_harvester.py` (IT-HRV-01/02) | DR-INT-05 |
| Full workflow execution (output correctness) | § 3.4 IT-SYS-06 | DR-INT-04, SR-IM-01, SR-OUT-01 |
| Re-measurement loop re-entry | § 4.1 AT-LOOP-01 | DR-INT-06, SR-AS-09 |

### Anthropic API (trusted, always stubbed in automated tests)

We trust the Anthropic SDK to make correct API calls. We test that our gateway wraps it correctly (unit level — stub gateway returns canned responses, we verify our code handles them). We **never** make live API calls in automated tests — all LLM interaction goes through the stub gateway in offline mode. Live API calls occur only in manual § 4.1 procedures and § 3.4 system integration tests when the full pipeline runs against the Validance production API.

### Krippendorff library (trusted)

Pinned `krippendorff>=0.6` in `pyproject.toml`. Statistical correctness trusted (published, peer-reviewed algorithm with small-sample correction, missing-data path, single-category collapse handling). We test that we call it with the correct input shape (correct matrix dimensions, correct data types).

---

## § 7  Test evidence log

### SR coverage matrix

Every SR has at least one verification procedure or an explicit gap/rationale entry. The authoritative SR → DR mapping lives in `design.md` § 6; this matrix extends it one level to the right.

| SR | Criticality | Requirement (short) | Verification procedure(s) | Status |
|---|---|---|---|---|
| SR-IN-01 | Must | Accept exam as text/markdown/PDF | IT-CHN-01, AT-INP-01 | Covered |
| SR-IN-02 | Must | Refuse to start without exam | AT-INP-03 | Covered |
| SR-IN-03 | Must | Extract structured text from exam | IT-CHN-01 | Covered |
| SR-IN-04 | Should | Accept teaching material | IT-CHN-05, AT-INP-01 step 3 | Covered |
| SR-IN-05 | Should | Accept starting rubric (file/paste/empty) | IT-CHN-02, AT-INP-02 | Covered |
| SR-IN-06 | Could | Accept student copies | IT-CHN-01, AT-INP-01 step 5 | Covered |
| SR-IN-07 | Could | Extract text from handwritten copies | IT-CHN-01 (canned OCR response via stub gateway) | Covered (stub); live OCR via § 4.1 AT-INP-01 |
| SR-IN-08 | Should | Surface partial parsing failures | IT-CHN-06 | Covered |
| SR-IN-09 | Must | Record evidence profile per run | IT-CHN-01, IT-CHN-04 | Covered |
| SR-AS-01 | Must | Produce Ambiguity assessment | IT-CHN-01, UT-MET-03–05, IT-SYS-06 | Covered |
| SR-AS-02 | Must | Produce Applicability assessment | IT-CHN-01, IT-CHN-02, IT-SYS-06 | Covered |
| SR-AS-03 | Must | Produce Discrimination Power assessment | IT-CHN-01, UT-MET-06, IT-SYS-06 | Covered |
| SR-AS-04 | Should | Ground judgments in teaching material | IT-CHN-05, UT-STG-09 | Covered |
| SR-AS-05 | Should | Use student copies for testing | IT-CHN-01 (with copies in input) | Covered |
| SR-AS-06 | Could | Fall back to synthetic responses | IT-CHN-04, UT-MOD-04 | Covered |
| SR-AS-07 | Must | Tag findings with exactly one criterion | IT-CHN-01 (assert criterion field), UT-STG-01 | Covered |
| SR-AS-08 | Should | Attach confidence indicator | IT-CHN-04, UT-MET-01–02 | Covered |
| SR-AS-09 | Should | Re-measure before/after quality scores | AT-LOOP-01 | Covered (manual) |
| SR-AS-10 | Should | Pairwise consistency check | IT-CHN-09 | Covered |
| SR-IM-01 | Must | Produce improved rubric | IT-CHN-01, IT-CHN-02, IT-SYS-06 | Covered |
| SR-IM-02 | Must | Improved rubric is structured | IT-CHN-01 (assert criteria/points/guidance), UT-MOD-02 | Covered |
| SR-IM-03 | Must | Produce proposed changes list | IT-CHN-01, IT-SYS-06 | Covered |
| SR-IM-04 | Should | No contradiction with teaching material | IT-CHN-05, UT-STG-09 | Covered |
| SR-IM-05 | Should | Change traces to finding | IT-CHN-07, UT-STG-08 | Covered |
| SR-IM-06 | Could | Empty changes with explanation | IT-CHN-03 | Covered |
| SR-UI-01 | Must | Web browser GUI | AT-INP-01 step 1 | Manual |
| SR-UI-02 | Must | Single input screen with four fields | AT-INP-01 | Manual |
| SR-UI-03 | Must | Mark fields required/optional | AT-INP-01 step 1, AT-INP-03 | Manual |
| SR-UI-04 | Must | Single trigger action | AT-INP-01 step 6 | Manual |
| SR-UI-05 | Should | Progress feedback while running | AT-RUN-01 | Manual |
| SR-UI-06 | Should | Teacher-native language | AT-REV-01, AT-REV-02 (inspect for internal terminology) | Manual |
| SR-UI-07 | Must | Side-by-side rubric display | AT-REV-01 step 1 | Manual |
| SR-UI-08 | Must | Changes with criterion + rationale | AT-REV-01 steps 2–3 | Manual |
| SR-UI-09 | Could | Per-change accept/reject | AT-REV-01 steps 4–5 | Manual |
| SR-UI-10 | Should | Re-run after edits | AT-LOOP-01 | Covered (manual) |
| SR-OUT-01 | Must | Produce explained rubric file | IT-CHN-01, IT-SYS-06, AT-REV-02 | Covered |
| SR-OUT-02 | Must | Root fields: rubric + explanation | IT-CHN-01 (assert root keys) | Covered |
| SR-OUT-03 | Must | Explanation grouped by three criteria | IT-CHN-01 (assert three-criteria grouping) | Covered |
| SR-OUT-04 | Should | Validate against documented schema | IT-CHN-08, UT-MOD-06 | Covered |
| SR-OUT-05 | Could | Reflect teacher decisions in JSON | IT-SYS-03, AT-REV-02 step 3 | Covered |
| SR-OBS-01 | Should | Record audit bundle per run | IT-SYS-07, IT-SYS-08, AT-RUN-01, AT-REV-04 | Covered |
| SR-OBS-02 | Should | Log every model invocation | IT-SYS-08 (assert stage events), UT-AUD-03/06 | Covered |
| SR-OBS-03 | Could | Audit bundle retrievable from UI | IT-SYS-07, AT-REV-04 | Covered |
| SR-PRF-01 | Should | Scale to 100 copies | Not exercised in v0.2.0 plan — requires dedicated scale/stress fixture with 100 synthetic copies. Deferred to v0.3.0 or post-delivery. | **Gap** |
| SR-PRF-02 | Must | Visible progress (>5s) | IT-SYS-05, AT-RUN-01 | Covered |
| SR-PRF-03 | Could | Cancellation / responsiveness | Not exercised in v0.2.0 plan — requires cancel-during-run UI interaction. Deferred: Could-priority, DR-PER-08 weakened `SIGTERM` semantics. | **Gap (Could)** |

### UR coverage matrix

Every UR-01 through UR-09 must have at least one test case or manual procedure tracing to it.

| UR | Requirement | Procedure ref(s) | Date | Result | Evidence |
|---|---|---|---|---|---|
| UR-01 | Provide exam question | AT-INP-01 step 2, AT-INP-02 step 2 | | | |
| UR-02 | Provide teaching material | AT-INP-01 step 3 | | | |
| UR-03 | Provide starting rubric | AT-INP-01 step 4 | | | |
| UR-04 | Provide sample student copies | AT-INP-01 step 5 | | | |
| UR-05 | Trigger with single action | AT-INP-01 step 6, AT-INP-02 step 4 | | | |
| UR-06 | View changes with criterion + rationale | AT-REV-01 steps 2–3 | | | |
| UR-07 | Accept/reject individually | AT-REV-01 steps 4–5 | | | |
| UR-08 | Re-assess after edits | AT-LOOP-01 (full cross-screen loop) | | | |
| UR-09 | Download final JSON | AT-REV-02 steps 2–3 | | | |

### Error / empty-state coverage

| Scenario | Procedure ref | Date | Result | Evidence |
|---|---|---|---|---|
| No exam question (error) | AT-INP-03 | | | |
| No changes proposed (empty) | AT-REV-03 | | | |
| Max iterations reached (guard) | AT-LOOP-02 | | | |
| Minimal input / no copies (partial evidence) | AT-INP-02, IT-CHN-04 | | | |

---

## Modification log

| Version | Date | Change |
|---|---|---|
| 0.3.0 | 2026-04-16 | **Codebase alignment pass.** (1) Fixed stale line number references in § 2.1: `_confidence_floor()` → `simulation.py:316`, `_step1/_step2/_step3` updated to current `stage.py` offsets. (2) Updated test counts: `test_models.py` 27→29, `test_audit_emitter.py` 9→12 (added UT-AUD-04/05/06), `test_settings.py` 8→9 (field rename). (3) Documented four previously undocumented unit test files: `test_llm_integration.py` (4 tests, UT-LLM-01–04), `test_ingest_input_root.py` (12 tests, UT-INP-01–06), `test_simulation.py` (12 tests, UT-SIM-01–06), `test_stage_logic.py` (11 tests, UT-SLG-01–05). (4) Added § 3.1b for `test_llm_e2e.py` (4 tests, IT-E2E-01–04). (5) Rewrote IT-SYS table (§ 3.4) to match actual 10 system integration tests (IT-SYS-01 through IT-SYS-10). (6) Updated § 2.5 DR group coverage summary with newly documented test groups. (7) Fixed stale IT-SYS references in § 6 (re-measurement → AT-LOOP-01) and § 7 SR matrix (SR-OBS-01/02/03 → IT-SYS-07/08, SR-AS-09/SR-UI-10 → manual-only). (8) Settings field names updated throughout to match the `GR_SIMULATION_*` / `GR_OCR_*` rename. |
| 0.2.0 | 2026-04-12 | **Review feedback absorbed.** (1) Added SR coverage matrix (§ 7) — all 46 SRs enumerated with verification procedures; SR-PRF-01 and SR-PRF-03 marked as explicit gaps with rationale. (2) Added DR group coverage summary (§ 2.5) — one row per DR group with representative procedures. (3) Added live workflow execution tests: IT-SYS-06 (full `assess_and_improve` run → valid `ExplainedRubricFile`) and IT-SYS-07 (re-measurement loop re-entry), closing the gap between API-mechanics tests and manual acceptance procedures. (4) [IT-SYS-08 removed in v0.3.0 — train-button capability removed.] (5) Broadened IT-CHN-01 SR traces to include SR-AS-02, SR-AS-03, SR-IM-02, SR-IM-03, SR-OUT-02, SR-OUT-03, SR-IN-03, SR-IN-09, SR-AS-07. (6) Fixed IT-CHN-04 trace from SR-IN-05 → SR-AS-06, SR-AS-08, SR-IN-09. (7) Added IT-CHN-05 (teaching material grounding, SR-AS-04/SR-IM-04), IT-CHN-06 (partial parse failure, SR-IN-08), IT-CHN-07 (change-to-finding traceability, SR-IM-05), IT-CHN-08 (schema validation, SR-OUT-04), IT-CHN-09 (pairwise consistency, SR-AS-10). (8) Added UT-STG-08 (source_findings traceability), UT-STG-09 (grounding contradiction), UT-AUD-03 (LLM call logging), UT-MOD-06 (schema validation). (9) Fixed UT-MET-01 expected output: "clamped to LOW range (≤ 0.40)" not "0.20". (10) Fixed AT-LOOP-01 step 8: "fresh scores shown, previous preserved" instead of "scores differ". (11) Added evidence artifact / reviewer / notes columns to § 5 validation table. (12) Added § 1 pragmatic exception note for § 3.3 DR-INT wiring tests. (13) Made § 4.1 prerequisite explicit: IT-SYS-06 must PASS before acceptance. (14) Updated § 6 Validance wiring table with IT-SYS-06/07. |
| 0.1.0 | 2026-04-12 | Initial verification plan. Covers 95 existing unit-level tests (§ 2), reclassifies `test_architecture.py` from acceptance to § 2.4 architectural invariants, frames DR-INT wiring tests as § 3.3 (DR-level, not SR-level), identifies § 3.2 schema round-trip as a gap, defines § 3.1 offline stage chain and § 3.4 system integration test cases, writes manual acceptance procedures for all three screens plus a dedicated cross-screen re-measurement loop (UR-08), and enumerates external dependency boundaries in § 6. |
