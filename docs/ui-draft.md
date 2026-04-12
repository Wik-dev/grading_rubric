# Grading Rubric Studio — UI specification

**Version**: 1.0.0
**Date**: 2026-04-11
**Status**: Final
**Author**: Wiktor Lisowski

---

## 1. Purpose

This document specifies the user interface for *Grading Rubric Studio*. It defines the three screens of the application, the architectural role each screen plays in the four-layer system, the design principles that govern them, and the realization rules that link them to the User Requirements (UR-01 through UR-09) in [`requirements.md`](requirements.md).

The UI is the **L4 layer** of the four-layer architecture locked in [`design.md`](design.md) § 2.1: a **custom single-page application** (Vite + React + shadcn + Tailwind) that talks to **Validance's REST API** as its backend. There is no custom HTTP server in the deliverable. The L4 SPA orchestrates a single Validance workflow run per session, from input collection through review and download.

The screens described here cover the three logical stages of the user experience:

1. **Input** — the teacher provides whatever materials they have.
2. **Running** — the application works while keeping the teacher informed.
3. **Review** — the teacher reviews proposed changes, decides which to keep, and exports the result.

These three screens collectively realize User Requirements UR-01 through UR-09. The realization rules are summarized in § 5 below.

---

## 2. Architectural role

The UI is one of two paths a reviewer can take through the deliverable:

| Path | Surface | Use case |
|---|---|---|
| **Path A — CLI** | `docker run <image> grading-rubric-cli <stage> ...` | Inspect a single pipeline stage in isolation. |
| **Path B — SPA over Validance** | The SPA in this document, talking to Validance's REST API | Run the full V-model experience: ingest → assess → propose → approve → score → render, with audit chain, human approvals, retries, and the deliverable JSON. |

The SPA is the **only** path that exercises the human-in-the-loop approval flow (UR-07) and the iteration loop (UR-08), because both depend on Validance primitives that the CLI does not invoke. The CLI path is for stage-level inspection; the SPA path is for the end-to-end experience the brief asks for.

**The SPA does not host its own state machine.** Validance's workflow run is the source of truth for what stage is currently executing, what the approval gate is waiting on, what the partial outputs look like, and what the deliverable will contain. The SPA polls Validance via TanStack Query (DR-PER-07, DR-INT-06) at a cadence of ~1–2 seconds during the running phase and on-demand for everything else. There is no SPA-side caching across reloads — a browser refresh during a run discovers the run state from Validance, not from `localStorage`.

This is intentional: the SPA is a thin teacher-facing surface over a stateful backend, not a stateful client in its own right. It honours the same hermeticity discipline (DR-ARC-03) that the L1 task code does — no global state, no hidden caches, every screen is a function of the current Validance run state.

---

## 3. Design principles

These principles govern the screens and constrain future changes to them.

- **Single unified flow.** Whether the teacher arrives with nothing, with a sentence of grading intentions, or with a polished draft rubric, they follow the same flow. The application adapts to what is provided rather than forcing the teacher into a different mode. SR-IN-05 (the *no starting rubric* path) is realized by the same screens as the *polished rubric* path.
- **One mandatory input, the rest optional.** Only the exam question is required (UR-01 / SR-IN-01). Every other input field is clearly marked optional and can be left empty.
- **No internal vocabulary.** The interface speaks in the teacher's language (*"check for ambiguous wording"*) rather than the system's (*"run measurement engine with persona variance"*). Internal names like `LLM_PANEL_AGREEMENT`, `KRIPPENDORFF_ALPHA`, `ProposedChange`, *workflow*, *approval gate* never appear in screen text. The teacher does not need to know how the application works internally to trust its output.
- **Trust through transparency.** Every proposed change is shown together with which of the three quality criteria it addresses and a human-readable rationale (UR-06 / SR-IM-03 / SR-OUT-03). A *Why?* affordance lets the teacher drill into more detail — the assessment finding(s) that motivated the change, the confidence indicator, the evidence the engine used.
- **Confidence is a first-class label.** Each proposed change carries a confidence indicator (LOW / MEDIUM / HIGH) computed by the assess and score stages. The screens surface this prominently, not as a footnote. A teacher must never look at a change and wonder how strong the evidence behind it is — especially when synthetic responses were used (SR-AS-06).
- **The teacher is in charge.** The application proposes; the teacher decides. Each change can be individually accepted or rejected (UR-07 / SR-OUT-05), and the assessment can be re-run after edits (UR-08 / SR-AS-09). The application never autonomously iterates — every iteration is teacher-triggered.
- **Hermetic per session.** Each session is one Validance workflow run, self-contained. No state crosses sessions. Closing the browser tab abandons the run; opening a new tab starts a fresh one. This matches the operational scenario in [`requirements.md`](requirements.md) § 1.4.

---

## 4. Screens

### 4.1 Input

```
┌─────────────────────────────────────────────────────────────┐
│  Grading Rubric Studio                                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Provide your exam materials                                │
│                                                             │
│  Exam question                                  (required)  │
│  ┌───────────────────────────────────────────────────┐     │
│  │  Drop a file here or click to upload              │     │
│  │  Accepted: .txt  .md  .pdf                        │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│  Teaching material                               (optional) │
│  ┌───────────────────────────────────────────────────┐     │
│  │  Drop a file here or click to upload              │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│  Existing rubric or grading intentions           (optional) │
│  ┌───────────────────────────────────────────────────┐     │
│  │  Drop a file, paste text, or leave empty          │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│  Sample student copies                           (optional) │
│  ┌───────────────────────────────────────────────────┐     │
│  │  Drop one or more files                           │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│                                  [ Build my rubric ]        │
└─────────────────────────────────────────────────────────────┘
```

**Realization notes**

- Covers UR-01 (provide exam question) through UR-04 (provide student copies) and UR-05 (trigger with a single action).
- The four input fields map directly to the four `InputSource` roles on `InputProvenance` (`design.md` § 4.4): `EXAM_QUESTION`, `TEACHING_MATERIAL`, `RUBRIC_INPUT`, `STUDENT_COPY`. Any combination of file uploads and (for the rubric input) inline text is supported per the role-tagged `InputSource` discriminated union, with `INLINE_TEXT` carrying the SR-IN-05 *paste a sentence of intent* path.
- Field optionality is shown directly in the field label. There are no hidden requirements.
- The action button label, *Build my rubric*, intentionally covers both the *modify an existing rubric* case and the *generate a rubric from scratch* case (per design commitment #5 and DR-IM-02). The application is unified around a single operation; the teacher does not select a mode.
- On submit, the SPA uploads the inputs to Validance and triggers the registered `grading_rubric.assess_and_improve` workflow (DR-INT-02). The workflow run id is held in SPA state for the lifetime of the session.

### 4.2 Running

```
┌─────────────────────────────────────────────────────────────┐
│  Building your rubric…                                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✓  Reading your exam question                              │
│  ✓  Reading teaching material                               │
│  ◐  Checking for ambiguous wording                          │
│  ○  Checking coverage of student responses                  │
│  ○  Checking how well the rubric separates quality levels   │
│  ○  Building the improved rubric                            │
│                                                             │
│  ████████░░░░░░░░░░░░░░░░░░  40 %                           │
└─────────────────────────────────────────────────────────────┘
```

**Realization notes**

- Each step is described in user language. The three middle steps map to the three quality criteria (Ambiguity, Applicability, Discrimination Power) without using the formal names; the criteria are introduced explicitly only in the Review screen.
- The progress display is driven by polling Validance's REST API for the workflow run state at ~1–2 second cadence (DR-PER-07, DR-INT-06). The SPA does **not** receive webhooks (browsers cannot host inbound webhooks); the polling cadence is the SR-PRF-02 *visible progress signal*.
- The check marks, spinner, and percentage are derived from Validance's stage-level state on the running workflow. The mapping from Validance stage names to teacher-facing step labels is done in the SPA (one mapping table, six entries).
- If a stage fails, the running screen surfaces the failure as a red marker on the failing step, with a *Show details* affordance that displays the error in plain language. The teacher's options are to retry from inputs (a fresh workflow run) or to abandon the session.

### 4.3 Review

```
┌─────────────────────────────────────────────────────────────┐
│  Results                          [ Download JSON ]   [ × ] │
├─────────────────────────────────────────────────────────────┤
│  Quality scores                                             │
│  ┌───────────────────────────────────────────────────┐     │
│  │  Ambiguity            ●●●○○   medium  (was: low)  │     │
│  │  Applicability        ●●●●○   high    (was: med)  │     │
│  │  Discrimination       ●●●○○   medium  (was: low)  │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│  ┌───────────────────────────┬───────────────────────────┐ │
│  │  Original                  │  Improved                 │ │
│  ├───────────────────────────┼───────────────────────────┤ │
│  │  1 point per action        │  1 point per action       │ │
│  │   • 0.5 if action          │   • 0.4 Category          │ │
│  │     corresponds to         │     Alignment             │ │
│  │     the category           │     – Full credit: …      │ │
│  │   • 0.5 if description     │     – Partial: …          │ │
│  │     makes clear how        │     – No credit: …        │ │
│  │     it is harmful          │   • 0.3 Scenario          │ │
│  │                            │     Specificity …         │ │
│  │                            │   • 0.3 Impact            │ │
│  │                            │     Description …         │ │
│  └───────────────────────────┴───────────────────────────┘ │
│                                                             │
│  Suggested changes                                          │
│  ┌───────────────────────────────────────────────────┐     │
│  │  AMBIGUITY                          confidence ●●○│     │
│  │  Replace "corresponds to the category" with three │     │
│  │  explicit scoring levels (full / partial / none). │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  ├───────────────────────────────────────────────────┤     │
│  │  APPLICABILITY                      confidence ●●●│     │
│  │  Add a penalty for responses that show            │     │
│  │  fundamental misunderstanding of the strategy.    │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  ├───────────────────────────────────────────────────┤     │
│  │  DISCRIMINATION POWER               confidence ●●○│     │
│  │  Split the 0.5 / 0.5 sub-criteria into            │     │
│  │  0.4 / 0.3 / 0.3 to better separate quality       │     │
│  │  levels.                                          │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│                  [ Re-assess after my edits ]               │
└─────────────────────────────────────────────────────────────┘
```

**Realization notes**

- The **Quality scores** strip at the top surfaces the three headline `CriterionScore` values produced by the score stage (DR-SCR-01 / DR-SCR-02), with confidence indicators rendered as filled dots. When a previous iteration exists (the teacher already re-ran once), the *was: ...* annotations show the prior values from `ExplainedRubricFile.previous_quality_scores` (`design.md` § 4.9). On the first iteration the *was* annotations are absent.
- The **side-by-side rubric view** (UR-06) lets the teacher compare the original and improved rubric directly. The two columns are rendered from `ExplainedRubricFile.original_rubric` and `ExplainedRubricFile.improved_rubric`. Visual diff highlighting (insertions, deletions, changes) is rendered against the `ProposedChange` discriminated union (`design.md` § 4.6) so a `REPLACE_FIELD` highlights the field, an `ADD_NODE` highlights the new node in green, a `REMOVE_NODE` strikes through the removed node, and so on.
- The **Suggested changes** list surfaces the `proposed_changes: list[ProposedChange]` from the propose stage. Each card shows the `primary_criterion` as a coloured tag, the `rationale` as the headline text, and the `confidence` as filled dots — exactly the three pieces of information the teacher needs to make an accept/reject decision.
- Each change offers individual **Accept** / **Reject** controls (UR-07). Accept and reject decisions are POSTed to Validance's `ApprovalGate` resolver via the proposal-payload mapping (DR-INT-04), which sets `ProposedChange.teacher_decision` and triggers the score stage to run on the resolved improved rubric. Accept-all is the default — clicking *Download JSON* with no decisions made accepts everything.
- The **Why?** affordance expands a panel containing: (a) the originating assessment finding(s) (paraphrased, not by id); (b) the evidence the finding was based on (real student copies vs synthetic responses, with the synthetic flag from `EvidenceProfile.synthetic_responses_used` displayed prominently); (c) the confidence indicator's `rationale` field. Trust without leaking implementation details.
- The **Re-assess after my edits** button realizes UR-08 (iteration). It triggers a fresh Validance workflow run against the current improved rubric (with the teacher's accept/reject decisions applied). The fresh run goes through the full pipeline (ingest → assess → propose → approve → score → render) and produces a new Review screen with updated quality scores and updated *was: ...* annotations. `Settings.max_iterations` (default 3, per DR-AS-13 / DR-IM-11) is enforced by the orchestrator — once the teacher has hit the bound, the *Re-assess after my edits* button is disabled with a tooltip explaining why.
- The **Download JSON** button realizes UR-09 (download the final rubric and explanation as JSON). The downloaded file is the `ExplainedRubricFile` (`design.md` § 4.9) reflecting the teacher's current acceptance state per SR-OUT-05. It is downloaded via a standard browser blob — no Validance round-trip beyond the initial fetch.
- The **× (close)** affordance abandons the run and returns to the Input screen. The Validance workflow run is left in its terminal state on the backend; the SPA simply forgets the run id.

---

## 5. Realization map (UR ↔ screen)

| User Requirement | Screen(s) | Realization element |
|---|---|---|
| **UR-01** Provide the exam question | Input | *Exam question* field (required) |
| **UR-02** Provide the teaching material | Input | *Teaching material* field (optional) |
| **UR-03** Provide an existing rubric or grading intentions | Input | *Existing rubric or grading intentions* field (optional, accepts file or pasted text) |
| **UR-04** Provide sample student copies | Input | *Sample student copies* field (optional, multi-file) |
| **UR-05** Trigger the operation with a single action | Input | *Build my rubric* button |
| **UR-06** View each change with criterion and rationale | Review | *Suggested changes* list (criterion tag + rationale + confidence dots + *Why?*) and side-by-side rubric view |
| **UR-07** Accept or reject changes individually | Review | *Accept* / *Reject* buttons on each suggested change card |
| **UR-08** Re-run the assessment after edits | Review | *Re-assess after my edits* button |
| **UR-09** Download the final rubric and explanation as JSON | Review | *Download JSON* button |

The Running screen does not realize a UR directly — it realizes **SR-PRF-02** (the visible progress signal that the running operation must surface) and **SR-OBS-01** (the audit-chain handle that the *Why?* affordance dereferences). It is operationally required to make the rest of the flow honest about what is happening.

---

## 6. Architectural decisions resolved at v1.0.0

The following decisions were left open in earlier drafts of this document and are now locked.

| Decision | Resolution | Locked by |
|---|---|---|
| **SPA vs multi-page** | Single-page application (Vite + React + shadcn + Tailwind) with three top-level screens managed by client-side routing inside one bundle. | DR-ARC-08, DR-INT-02 |
| **State persistence across reloads** | None. The SPA holds the Validance workflow run id in memory only. A browser refresh during a run discovers the run state from Validance via polling (DR-INT-06); a refresh after the run terminates abandons the session. This matches the *hermetic per session* design principle and the operational scenario in [`requirements.md`](requirements.md) § 1.4. | DR-INT-06, DR-ARC-03 |
| **Drilldown depth in *Why?*** | Three pieces: (a) the originating assessment finding(s) in the teacher's words, (b) the evidence type with the synthetic flag, (c) the confidence rationale. No raw operation events, no model names, no token counts. | SR-OUT-03, design principle *no internal vocabulary* |
| **Large input volumes** | The student-copies field accepts arbitrary file lists; the SPA renders the list as a scrollable virtualized component when N > 20. The Validance backend handles the actual upload, so SPA performance does not depend on file content size. | DR-PER-04 |
| **Error and empty states** | Three explicit states: (a) **input validation failure** — inline error on the offending field, *Build my rubric* button disabled until resolved; (b) **stage failure during running** — red marker on the failing step in the Running screen, *Show details* affordance surfaces a plain-language error, *Try again* returns to inputs; (c) **empty improvement** — Review screen with the *Suggested changes* list explicitly stating *"The rubric is already in good shape — no changes were proposed against the three quality criteria."* per SR-IM-06 / DR-IM-05. | SR-IM-06, DR-IM-05 |

---

## 7. What this document does **not** specify

- **Visual design** (colours, typography, iconography). The shadcn defaults plus a minimal Tailwind theme are the starting point; the visual layer is owned by the implementation, not by this document.
- **Accessibility specifics** (WCAG conformance level, keyboard shortcuts, screen-reader behaviour). The SPA targets WCAG 2.1 AA as a baseline goal; concrete conformance is an implementation concern and is not in scope for this specification.
- **Internationalization.** The application is English-only for the recruitment deliverable.
- **Mobile/tablet layouts.** The teacher operates from a desktop browser per the operational scenario in [`requirements.md`](requirements.md) § 1.4. Responsive collapse below ~1024px is acceptable but not engineered.
- **The DR-UI design requirements.** A small `design.md` § 5.6 *DR-UI* group will land in a follow-up round as a thin DR layer that maps the locked screens to the SR-UI requirements (state management, side-by-side diff component contract, polling cadence, accept/reject control wiring). This document is the **product surface**; § 5.6 will be the **implementation contract**.

---

## Modification log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0.0 | 2026-04-11 | Wiktor Lisowski | **Bumped from initial draft to final.** Status changed from *Initial draft* to *Final*. Document retitled from *UI Draft* to *UI specification*. Three screens locked: **Input** (was *Inputs*), **Running** (was *Progress*), **Review** (was *Review and download*). New § 2 *Architectural role* anchoring the SPA as the L4 layer of the four-layer architecture, talking to Validance's REST API as its backend (no custom HTTP server in the deliverable), with explicit framing of the CLI vs SPA paths and the *no SPA-side state* discipline. Design principles extended with *Confidence is a first-class label* and *Hermetic per session* (the latter aligning with the operational scenario in `requirements.md` § 1.4). Input screen realization notes now reference the role-tagged `InputSource` discriminated union (`design.md` § 4.4) and the SR-IN-05 inline-text path. Running screen realization notes now lock TanStack Query polling at ~1–2s cadence (DR-PER-07, DR-INT-06) and explain why the SPA does not receive webhooks. Review screen extended with the **Quality scores** strip surfacing the three headline `CriterionScore` values from the score stage (DR-SCR-01 / DR-SCR-02) with *was: ...* annotations from `ExplainedRubricFile.previous_quality_scores`, and per-change **confidence indicators** rendered as filled dots; *Why?* affordance contents specified (originating finding paraphrased, evidence type with synthetic flag, confidence rationale); *Re-assess after my edits* now references the `Settings.max_iterations` orchestrator-enforced bound (DR-AS-13 / DR-IM-11); *Download JSON* references `ExplainedRubricFile` (§ 4.9) and SR-OUT-05. New § 5 *Realization map* tabulating UR ↔ screen ↔ realization element. New § 6 *Architectural decisions resolved at v1.0.0* — the five open questions from v0.1.0 (*Open design questions*) are all resolved: SPA vs multi-page → SPA, state persistence → none, *Why?* drilldown → three pieces, large input volumes → virtualized list, error/empty states → three explicit states with the empty-improvement case linked to SR-IM-06 / DR-IM-05. New § 7 *What this document does not specify* explicitly carves out visual design, accessibility specifics, internationalization, mobile layouts, and the DR-UI implementation contract (deferred to a follow-up `design.md` § 5.6 round). Vocabulary discipline: no development-tool names appear anywhere in the document (CLAUDE.md § 4 convention enforced). |
| 0.1.0 | 2026-04-10 | Wiktor Lisowski | Initial draft. Three screens (inputs, progress, review and download), design principles, open questions. |
