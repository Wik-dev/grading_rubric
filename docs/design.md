# Grading Rubric Studio — Design

**Version**: 0.2.1
**Date**: 2026-04-11
**Status**: Architectural overview filled; technology stack, data models, and DR groups still to be filled
**Author**: Wiktor Lisowski

---

## 1. Introduction

### 1.1 Purpose

This document defines the **design** of *Grading Rubric Studio*: how the system is built in order to satisfy the System Requirements specified in [`requirements.md`](requirements.md) § 5. It is the third layer of the V-shape product development chain (User Needs → User Requirements → System Requirements → **Design Requirements** → Code → Tests).

The Design Requirements (DR) here are the layer at which **technology choices, data models, algorithms, and module decomposition are decided**. The SR layer was deliberately technology-neutral; the DR layer is not. Every choice made here is justified with a brief rationale, because *the differentiator of this submission is engineering rigor*: a reviewer should be able to walk the chain from any DR back up to a SR, a UR, and a UN, and forward to the code that implements it and the test that validates it.

### 1.2 Scope

**In scope**

- The technology stack and the rationale for each choice.
- Module decomposition and dependency direction.
- Data models — the schemas of the *Rubric*, *Assessment finding*, *Proposed change*, *Audit bundle*, and *Explained rubric file*.
- Assessment algorithms — *how* Ambiguity, Applicability, and Discrimination Power are measured.
- LLM usage — prompt design, sampling, structured outputs, validation, retries, deterministic execution policy.
- UI design — framework, screens, state management.
- Input parsing — file formats, OCR for handwritten copies.
- Observability — audit bundle structure, logging.
- Performance — caching, concurrency.
- The *Scorer interface* and the stub `train_scorer` task (the train-button capability).
- Deployment, packaging, orchestration — including how a hermetic task definition allows the same code to run standalone or via Validance.

**Out of scope**

- Anything that belongs at the SR layer (what the system *does*) or at the UR layer (what the *user* must be able to do).
- An actually-trained scorer model (capability not output, per the locked architectural commitments).
- Multi-teacher collaboration, persistent storage across sessions, mobile UI (out of scope of the application itself per [`requirements.md`](requirements.md) § 1.2).

### 1.3 Reference documents

| Document | Notes |
|---|---|
| [`requirements.md`](requirements.md) | UN, UR, SR, glossary, and traceability. Every DR here traces to at least one SR there. |
| [`ui-draft.md`](ui-draft.md) | Initial UI sketch. Superseded for design purposes by § 5.6 *DR-UI* once filled. |

---

## 2. Architectural overview

This section frames the system at a level above any specific technology choice. It establishes the modules and how they interact, and it states the four guiding principles that shape every choice made later in the document.

### 2.1 System diagram

```
+----------------------------------------------------------+
|                          Teacher                          |
+--------------------------+-------------------------------+
                           |
                  +--------v----------+
                  |     UI Layer       |
                  |   (web browser,    |
                  |   local machine)   |
                  +--------+----------+
                           |
                  +--------v----------+
                  |   Orchestrator     |
                  | (one run, hermetic |
                  |   stage chain)     |
                  +--+----+----+---+--+
                     |    |    |   |
        +------------+    |    |   +--------------+
        |                 |    |                  |
   +----v-----+    +------v--+-+----+      +------v-----+
   |  Input   |    |   Assessment    |     | Improvement |
   |  Parser  +--->+     Engine      +---->+  Generator  |
   +----------+    | (Ambiguity /    |     +------+------+
                   |  Applicability /|            |
                   |  Discrimination)|            |
                   +-----------------+            |
                                                  v
                                        +-------------------+
                                        |   Output Writer    |
                                        +---------+---------+
                                                  |
                                                  v
                                        Explained rubric file
                                              (JSON)

  Cross-cutting modules
  ---------------------
  - LLM Gateway       Pluggable backend; Anthropic by default.
                      Single point through which every model call passes.
  - Audit Recorder    Captures the per-run trace -> audit bundle.
                      Subscribes to events from every other module.
  - Scorer interface  Abstraction for the train-button capability.
  - Content cache     Content-hashed memoization of expensive calls
                      (LLM, OCR, parsing) keyed by input fingerprint.
  - Data models       Rubric, Assessment finding, Proposed change,
                      Evidence profile, Audit bundle, Explained rubric
                      file. The contract layer the modules pass between
                      each other.
```

The diagram is intentionally module-level, not implementation-level. Module decomposition into packages and dependency rules are the subject of § 5.1 *DR-ARC*. Schemas of the contract objects are the subject of § 4.

### 2.2 Hermetic-task philosophy

Each stage in the pipeline (input parsing, assessment, improvement, output writing) is built as a **hermetic task**: it takes structured inputs, produces structured outputs, holds no global state, performs no hidden I/O outside its declared inputs and outputs, and can be invoked from three different execution surfaces using the same code:

1. **Standalone** — a single function call or CLI invocation, useful in tests and during development.
2. **In-process from the orchestrator** — the default mode of the application, where the orchestrator chains the stages.
3. **External orchestrator** — a workflow engine such as Validance, Snakemake, or Airflow, which schedules each task in its own container and persists its outputs to a shared location.

The cost of this discipline is real: no shortcuts via shared mutable state, no global singletons, no implicit caches. The benefit is that every stage is independently testable, every run is replayable from its inputs, and the system is **orchestration-agnostic** by construction.

### 2.3 LLMs as measurement instruments

The dominant pattern in AI applications today is to treat LLMs as **oracles**: ask the model, trust the answer. This system does not. Its job is to *assess the quality of a rubric used to grade students*; an oracle-style call would make its output exactly as defensible as the model's last best guess, which is not defensible enough to hand to a teacher accountable to their students.

Every LLM interaction is therefore framed as a **measurement task** with the following properties:

- **Structured prompt with a defined purpose** — one task per prompt, prompt identifiers logged in the audit bundle (§ 5.8 *DR-OBS*).
- **Structured output validated against a schema** — JSON conforming to a schema declared at the call site, rejected and retried on validation failure (§ 5.2 *DR-LLM*).
- **Multiple samples where reliability matters** — for measurements that drive the *confidence indicator* on findings, the gateway draws several samples and reports both the central tendency and the spread.
- **Classical NLP and statistics inserted wherever they are strictly better** — inter-rater reliability via Krippendorff's α, deterministic span matching for the side-by-side rubric diff, content-hashed caching of identical calls. The LLM is used where its semantic flexibility is the right tool, not as the default for everything.

### 2.4 The system is data-aware

The application is designed to be useful across a wide range of evidence conditions. A teacher arriving with no teaching material, no starting rubric, and no student copies — only the exam question — should still get a result. A teacher arriving with the full course corpus, a polished draft rubric, and a hundred sample copies should get a much more confident result. **The system does not pretend the two situations are the same.**

The mechanism is the *evidence profile* (defined in [`requirements.md`](requirements.md) § 2 and recorded per SR-IN-09). It is computed at the start of every run and drives:

- which assessment paths can fire (SR-AS-04, SR-AS-05, SR-AS-06);
- which evidence is real and which is synthetic (SR-AS-06);
- the *confidence indicator* on every assessment finding (SR-AS-08);
- the warnings shown to the teacher in the UI when evidence is thin.

The quantitative rules for translating an evidence profile into a confidence indicator are specified in § 5.4 *DR-AS*.

### 2.5 Human in the loop

The application proposes; the teacher decides. The system is never the final authority on what the rubric should say — its outputs are *suggestions accompanied by evidence*, not commands. The teacher is the domain expert and is accountable to their students and their grading team.

Concretely, this principle constrains the design in three ways:

- **Every proposed change carries a rationale** (SR-IM-03, SR-UI-08). No silent edits.
- **Per-change accept/reject controls are first-class** (UR-07, SR-UI-09), even though they are only *Could* in the MoSCoW. The architecture supports them; the build prioritization decides whether they ship in this delivery.
- **Re-assessment after teacher edits** (UR-08, SR-UI-10) is supported by the same hermetic-task structure that supports standalone runs — a re-assessment is just another run with a different starting rubric.

---

## 3. Technology stack and decision register

*To be filled in step 3.*

This section will list each technology decision deferred from the SR layer, the current state of the decision (`pending` / `decided` / `deferred`), the chosen option (when decided), and a brief rationale paragraph. Decisions are tracked in the table below as a register; the discussion lives in the per-decision sub-sections.

| # | Decision | State | Choice | Rationale ref. |
|---|---|---|---|---|
| 1 | LLM provider and SDK | pending | — | § 3.1 |
| 2 | Prompting and structured-output approach | pending | — | § 3.2 |
| 3 | UI framework | pending | — | § 3.3 |
| 4 | File and document parsing libraries | pending | — | § 3.4 |
| 5 | OCR for handwritten student copies | pending | — | § 3.5 |
| 6 | Schema language for the *Explained rubric file* | pending | — | § 3.6 |
| 7 | Configuration mechanism and secret handling | pending | — | § 3.7 |
| 8 | Caching strategy | pending | — | § 3.8 |
| 9 | Deterministic execution policy | pending | — | § 3.9 |
| 10 | Deployment topology, packaging | pending | — | § 3.10 |
| 11 | Orchestration layer | pending | — | § 3.11 |

Locked architectural commitments from `CLAUDE.md` § 6 (not re-litigated here): Anthropic as the default LLM provider; pluggable backend; Validance as one possible execution layer (not embedded in the deliverable).

---

## 4. Data models

*To be filled in step 4.*

This section will define the schemas of the system's contract objects. These are the data structures that the modules pass between each other and that the *Explained rubric file* serializes:

- **Rubric** — the structured form of the rubric (criteria, sub-criteria, point allocations, scoring guidance).
- **Assessment finding** — one observation about the rubric, with criterion tag, evidence references, and confidence indicator.
- **Proposed change** — original passage, modified passage, criterion, rationale, source findings.
- **Evidence profile** — per-run record of which optional inputs were provided.
- **Audit bundle** — per-run trace of inputs, intermediate findings, model invocations, and outputs.
- **Explained rubric file** — the deliverable wrapper containing the improved rubric and the explanation of changes.

Each schema will be presented in the chosen schema language (decision § 3.6) and will trace to the SRs that depend on it.

---

## 5. Design Requirements

Design Requirements describe *how* the system is built in order to satisfy the System Requirements. They are the most numerous layer of the chain (per the healthy-distribution rule of thumb in `CLAUDE.md` § 2 — wider than the SR layer above them). They use the same MoSCoW criticality scale as the layers above (`Must` / `Should` / `Could`).

DRs are organized below into eleven groups by area. Each group has its own intent paragraph and table. *All groups are placeholders until we fill them step by step.*

### 5.1 Architecture and module decomposition (DR-ARC)

*To be filled.*

Defines the package layout, the module boundaries, the dependency direction, and how the hermetic-task structure allows each pipeline stage to run standalone or via an orchestration layer. Establishes the interface contracts between modules.

### 5.2 LLM usage (DR-LLM)

*To be filled.*

Defines prompt design (one prompt per measurement task, structured outputs), sampling strategy (temperature, k samples for reliability estimates), structured-output validation and retry policy, deterministic execution policy, and the abstraction layer that makes the LLM backend pluggable.

### 5.3 Data models and persistence (DR-DAT)

*To be filled.*

Realizes the schemas defined in § 4 in code. Defines validation, serialization, and the (intentionally minimal) persistence model — the application has no cross-session storage (per [`requirements.md`](requirements.md) § 1.2 *out of scope*) but does write the audit bundle and the explained rubric file to disk.

### 5.4 Assessment algorithms (DR-AS)

*To be filled.*

The methodologically dense group. Specifies *how* each of the three quality criteria is measured:

- **Ambiguity** — grader-panel design with persona variance, inter-rater reliability via Krippendorff's α, ambiguity findings tied to spans of the rubric.
- **Applicability** — coverage testing using real student copies when available, falling back to synthetic candidate responses generated under controlled diversity constraints.
- **Discrimination Power** — separation analysis on graded outcomes (real or synthetic) across rubric strata.

Also defines confidence calibration: how the *confidence indicator* on each finding is computed from the *evidence profile*.

### 5.5 Improvement generation (DR-IM)

*To be filled.*

Defines how *assessment findings* are turned into *proposed changes* on the rubric: how the original rubric is modified, how rationale is generated, how proposed changes are constrained to not contradict the teaching material, and how the empty-improvement case is handled.

### 5.6 User interface (DR-UI)

*To be filled.*

Realizes the SR-UI requirements in the chosen UI framework. Specifies screen composition, state management, the side-by-side rubric diff component, the per-change accept/reject controls, and the progress feedback mechanism. Supersedes [`ui-draft.md`](ui-draft.md) for design purposes.

### 5.7 Input parsing and OCR (DR-IO)

*To be filled.*

Defines how exam questions, teaching material, starting rubrics, and student copies are loaded from disk and turned into the structured text the assessment stage expects. Includes OCR for handwritten student copies (decision § 3.5) and partial-failure handling per SR-IN-08.

### 5.8 Observability (DR-OBS)

*To be filled.*

Defines the on-disk layout of the *audit bundle*, the logging format for model invocations, and the API by which the UI retrieves the bundle for the current run.

### 5.9 Performance, caching, and concurrency (DR-PER)

*To be filled.*

Defines the caching strategy (decision § 3.8) — likely a content-hashed cache borrowed from patterns proven in adjacent repositories — and how concurrent processing of multiple student copies is handled while keeping the run hermetic.

### 5.10 Scorer interface and train-button capability (DR-SCR)

*To be filled.*

Defines the **Scorer interface** (the abstraction that any future trained model would implement) and the stub `train_scorer` task (the build-time wiring that makes the train button real even though no actual model is trained for this delivery). This is the design-layer realization of locked architectural commitment #5.

### 5.11 Deployment, packaging, orchestration (DR-DEP)

*To be filled.*

Defines how the application is packaged, how the hermetic tasks are exposed both to a standalone runner and to an external orchestration layer (Validance is one possibility, Snakemake or Airflow would also work), and how the deliverable is structured so that a reviewer can clone the repository and run it end-to-end in under a minute.

---

## 6. Traceability — System Requirements to Design Requirements

*To be filled as DR groups land.*

| System Requirement | Covered by |
|---|---|
| *to be populated* | *to be populated* |

Every DR shall trace back to at least one SR. Every SR shall be covered by at least one DR. The traceability table will be regenerated at each iteration as DRs are added.

---

## Modification log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.2.1 | 2026-04-11 | Wiktor Lisowski | § 2 trim pass: removed redundant repetitions of *"Validance is one possible execution layer"*, *"orchestration-agnostic"*, *"pluggable backend"*, and the mechanical *"design-layer realization of locked architectural commitment #X"* footers from § 2.3 / § 2.4 / § 2.5. Tightened § 2.3 opening paragraph. No content lost; the same points are now made once each. |
| 0.2.0 | 2026-04-11 | Wiktor Lisowski | Filled § 2 *Architectural overview*: § 2.1 system diagram (eight modules — UI, Orchestrator, Input Parser, Assessment Engine, Improvement Generator, Output Writer, plus the cross-cutting LLM Gateway / Audit Recorder / Scorer interface / Content cache / Data models), and § 2.2–2.5 stating the four guiding principles (hermetic tasks, LLMs as measurement instruments, data-aware system, human in the loop) as the design-layer realizations of locked architectural commitments #2, #4, #5, #6, and #7. No DRs added. No technology decisions made yet. |
| 0.1.0 | 2026-04-11 | Wiktor Lisowski | Initial skeleton. Section 1 (intro, scope, references) drafted. Sections 2 (architectural overview), 3 (technology stack and decision register — 11 pending decisions listed), 4 (data models), 5 (eleven DR groups DR-ARC through DR-DEP, each with an intent paragraph), 6 (traceability), and 7 (modlog) created as placeholders to be filled iteratively. No DRs and no technology decisions made yet. |
