# Grading Rubric Studio — Design

**Version**: 0.11.0
**Date**: 2026-04-11
**Status**: Architectural overview filled; **all 11 technology-stack decisions locked**; data models and DR groups still to be filled
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

### 1.4 Design glossary

This section anchors terms that appear in the design layer but not in [`requirements.md`](requirements.md) § 2. The user-facing glossary in `requirements.md` remains the canonical source for shared vocabulary; entries here are strictly design-internal.

| Term | Definition |
|---|---|
| **Sample (LLM)** | One independent draw from the LLM for a given call. The same prompt with the same inputs and the same model can be drawn multiple times; because the model is stochastic, the resulting outputs differ. The system uses multiple samples per call where the *spread across samples* is itself the measurement — for example, when measuring how reliably independent graders agree on the interpretation of a rubric phrase. Tasks that need only a single answer (extraction, classification) draw one sample; tasks that drive an *assessment finding* and a *confidence indicator* draw several. |

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

This makes every stage independently testable, every run replayable from its inputs, and the system **orchestration-agnostic** by construction.

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

Each technology decision deferred from the SR layer is tracked in the register below. State is one of `pending` / `decided` / `deferred`. Decisions are filled iteratively; each `decided` row points to a sub-section that holds the chosen option and the rationale.

| # | Decision | State | Choice | Rationale ref. |
|---|---|---|---|---|
| 1 | LLM provider, SDK, and default model | **decided** | Anthropic via `anthropic` Python SDK (≥ 0.40); default model `claude-sonnet-4-6`; per-call override supported by the LLM Gateway | § 3.1 |
| 2 | Prompting and structured-output approach | **decided** | Anthropic tool use for structured output; prompts as content-hashed markdown files with YAML front-matter; Pydantic schemas; retry-once on validation failure; single `gateway.measure()` entry point | § 3.2 |
| 3 | UI framework | **decided** | Vite + React 18 + TypeScript front-end with shadcn/ui (Radix + Tailwind), React Router, TanStack Query, react-hook-form + zod, Recharts, Sonner; Vitest + Testing Library for unit, Playwright for E2E; talks to the Python back-end over HTTP/JSON | § 3.3 |
| 4 | File and document parsing libraries | **decided** | `pypdf` for simple PDF text extraction, `pdfplumber` when layout matters, stdlib for `.txt`, `markdown-it-py` for `.md`, `python-docx` for `.docx`; a single `InputParser` module returns a uniform `ParsedDocument` regardless of source format | § 3.4 |
| 5 | OCR for handwritten student copies | **decided** | Claude Sonnet 4.6 multimodal input as the primary OCR path, invoked through the same LLM Gateway as every other model call; `StudentCopyReader` interface in DR-IO keeps the backend swappable for a dedicated OCR service | § 3.5 |
| 6 | Schema language for the *Explained rubric file* | **decided** | Pydantic is the single source of truth; a `make schemas` step emits a versioned JSON Schema file that ships alongside the deliverable; the front-end derives its TypeScript types and zod validators from the same JSON Schema | § 3.6 |
| 7 | Configuration mechanism and secret handling | **decided** | `pydantic-settings` `Settings` class as the typed loader; environment variables as the only runtime source; gitignored `.env` for dev convenience; secrets held as `SecretStr`; workflows registered with an external orchestrator declare required secret *names*, not values | § 3.7 |
| 8 | Caching strategy | **decided** | No application-level cache. Cost is not a concern; cross-run deduplication is the external orchestrator's job at the task granularity; transient-error retries are the Anthropic SDK's job; test reproducibility is handled by mocking at the Gateway seam. | § 3.8 |
| 9 | Deterministic execution policy | **decided** | Temperature 0 for single-sample extraction/classification calls, temperature > 0 for `samples > 1` reliability measurements, model pinned to a snapshot version when the provider publishes one; bit-identity explicitly *not* claimed — the guarantee is measurement-level stability plus audit-level reconstructability | § 3.9 |
| 10 | Deployment topology, packaging | **decided** | FastAPI back-end; pip-installable Python project via `pyproject.toml` with console-script entry points for the API server and the CLI; Vite static build for the front-end; a top-level `Makefile` is the single entry-point surface (`install` / `dev` / `build` / `test` / `schemas`) | § 3.10 |
| 11 | Orchestration layer | **decided** | None embedded in the deliverable — default mode is a single Python process plus a static SPA; the hermetic-task structure of § 2.2 makes the same code wrappable by any external engine, with one concrete reference example in § 5.11 *DR-DEP* | § 3.11 |

Locked architectural commitments from `CLAUDE.md` § 6 (not re-litigated here): Anthropic as the default LLM provider; pluggable backend; Validance as one possible execution layer (not embedded in the deliverable).

### 3.1 LLM provider, SDK, and default model

**Decision.** Anthropic, accessed via the official `anthropic` Python SDK (≥ 0.40). Default model: **Claude Sonnet 4.6** (`claude-sonnet-4-6`). Every LLM call in this delivery uses the default; the LLM Gateway supports per-call model override so future cost-aware routing is a local change.

**Rationale.**

- **Provider** — Locked in CLAUDE.md commitment #3. The Gateway abstraction makes the provider swappable without touching application code, which matters for the anticipated EPFL on-prem path (RCP / local LLMs).
- **SDK** — No realistic alternative for a Python application calling Claude.
- **Default model** — Sonnet 4.6 is the workhorse: strong reasoning at moderate cost. Haiku would underperform on the methodology-dense assessment and improvement tasks; Opus would add marginal capability at substantially higher cost without meaningfully changing what a reviewer sees.
- **Single default vs. per-task routing** — Routing is more efficient but adds complexity at every call site. It is a refinement that lands cleanly later (the Gateway already supports per-call override), and over-engineering it on day one contradicts the anti-patterns in `CLAUDE.md` § 7.4.

### 3.2 Prompting and structured-output approach

**Decision.** Every LLM call in the system goes through a single function on the LLM Gateway:

```python
gateway.measure(
    prompt_id: str,
    inputs: dict,
    schema: type[BaseModel],
    samples: int = 1,
    model: str | None = None,
) -> list[BaseModel]
```

The implementation choices behind this signature are:

- **Structured output via Anthropic *tool use*.** The schema is converted to an Anthropic tool definition; the model is forced to call the tool; the tool arguments are the structured response. No free-text JSON parsing, no `response_format` shims, no third-party wrapper layer (no `instructor`, no `langchain`, no `dspy`).
- **Prompts as files, not strings in code.** Each `prompt_id` resolves to a file `prompts/{prompt_id}.md` with a YAML front-matter header (`id`, `version`, `description`, `expected_inputs`) followed by the prompt body. Templating uses plain `str.format` placeholders against the `inputs` dict — no Jinja, no second template language.
- **Content-hashed prompt identity.** The Gateway computes a SHA-256 over the rendered prompt body and the schema definition. The hash is recorded in the *audit bundle* for every call, so the exact prompt and schema used for any past run are reconstructable from disk.
- **Schemas are Pydantic models.** Each call site declares its expected output as a Pydantic class. Pydantic validates the model's tool arguments before the Gateway returns them.
- **Retry-once on validation failure.** If validation fails, the Gateway re-issues the call once, appending the validation error message to the prompt context. A second failure raises and is recorded in the audit bundle as a measurement failure for that call. There is no infinite retry loop and no silent fallback to "best-effort" parsing.
- **Sampling is a parameter, not a separate code path.** `samples=1` covers the extraction-style calls; `samples=k` covers reliability-style measurements where the *spread across samples* is the signal (see § 1.4 *Design glossary*). The Gateway parallelizes the `k` draws but otherwise treats them identically. Aggregation (mean, agreement coefficient, panel inter-rater reliability) is the caller's responsibility, not the Gateway's, because aggregation logic is measurement-specific.
- **One door to the API.** No module other than the LLM Gateway holds an `anthropic.Anthropic` client. This is what makes the backend pluggable (swap the implementation behind `gateway.measure`) and what makes the audit bundle complete (every call passes through one place).

**Rationale.**

- **Why tool use directly rather than `instructor` / `langchain` / `dspy`.** Each adds a dependency, an abstraction layer, and an opinionated control flow that the audit bundle would have to reverse-engineer. Anthropic tool use is the native mechanism for forcing structured output from Claude; using it directly is the shortest path between the schema and the validated object, and it keeps the dependency footprint to `anthropic` + `pydantic`.
- **Why prompt files rather than f-strings in code.** Prompts are the most-edited surface of an LLM system. Keeping them in markdown files lets the reviewer read them without reading Python, lets `git diff` show prompt evolution clearly, and gives the audit bundle a stable filename + version + content hash to record. F-strings scattered across modules would scatter the same information across the codebase.
- **Why content hashing.** The brief asks for engineering rigor. A reviewer reading an audit bundle should be able to point at any historical run and answer *which prompt was used, in which version, with which schema*. SHA-256 over the rendered prompt and schema is the smallest mechanism that gives a precise answer to that question.
- **Why retry-once and not retry-N.** Retry-once handles the realistic failure mode (transient validation slip the model can fix when shown the error). Retry-N hides systematic prompt-schema mismatches that should be fixed in the prompt, not papered over with brute force.
- **Why aggregation lives outside the Gateway.** Different measurements aggregate differently — Krippendorff's α for grader-panel agreement, simple majority vote for classification, mean ± stdev for numeric scores. Putting aggregation in the Gateway would force one shape on all measurements; putting it in the caller keeps the Gateway thin and the measurement logic where it can be unit-tested.

### 3.3 UI framework

**Decision.** The user interface is a **single-page application** built with the following stack:

| Concern | Choice |
|---|---|
| Build tool | **Vite** (`@vitejs/plugin-react-swc`) |
| Language | **TypeScript** (strict) |
| Framework | **React 18** |
| Component primitives | **shadcn/ui** (Radix UI primitives + Tailwind variants) |
| Styling | **Tailwind CSS** with `tailwindcss-animate` and `@tailwindcss/typography` |
| Routing | **React Router** (`react-router-dom`) |
| Server state | **TanStack Query** (`@tanstack/react-query`) |
| Forms and validation | **react-hook-form** + **zod** via `@hookform/resolvers` |
| Charts | **Recharts** |
| Notifications | **Sonner** (toasts) |
| Animation | **Framer Motion** (sparingly) |
| Icons | **lucide-react** |
| Unit / component tests | **Vitest** + **@testing-library/react** + **jsdom** |
| End-to-end tests | **Playwright** |

The SPA is a **separate deployable** from the Python back-end. The two communicate over **HTTP with JSON bodies**. The front-end reads the back-end base URL from a Vite environment variable (`VITE_API_BASE`) so the same build runs against a local dev server, a packaged local application, and any future hosted deployment without code changes.

The specific Python HTTP server that exposes the back-end is the subject of decision **#10 (deployment topology, packaging)** — this decision locks only the boundary (HTTP/JSON) and the front-end stack.

**Rationale.**

- **Why a React SPA rather than Streamlit / Gradio / a Python-native UI.** The user interface described in [`requirements.md`](requirements.md) § 5.1.4 (SR-UI) and sketched in [`ui-draft.md`](ui-draft.md) is not a notebook-style demo. It is a three-screen flow with a side-by-side diff component, per-change accept/reject controls, progress feedback, and re-assessment iteration. Streamlit and Gradio are strong for the *"show a model on a page"* case and weak for the *"custom component with state"* case. A proper front-end framework is the right shape for these screens, and the additional complexity is modest because the stack below is opinionated and production-proven.
- **Why Vite + React + TypeScript.** This is the de-facto modern React starter. Vite gives fast HMR and a tiny config surface; React 18 is the long-term target for the ecosystem; TypeScript catches interface drift between the front-end and the back-end API contract at build time, which matters specifically because both ends of that contract are under active design in this deliverable.
- **Why shadcn/ui + Tailwind.** shadcn provides unstyled, accessible Radix primitives with a Tailwind styling layer. Crucially, components are vendored into `src/components/ui/` rather than imported from a runtime dependency — the project owns the source of every primitive it uses, which keeps the dependency surface small and the components trivially customizable. Tailwind avoids the CSS-in-JS vs. stylesheets debate entirely; it matches the "less glue, more leverage" preference expressed in CLAUDE.md § 7.4.
- **Why TanStack Query.** The front-end's job is to start a run, poll its progress, and render the result — a near-textbook *server state* problem. TanStack Query handles the polling, caching, stale-while-revalidate, and retry concerns that would otherwise be reimplemented by hand in `useEffect` hooks. It is also the clean insertion point for the progress-feedback requirement SR-UI-04.
- **Why react-hook-form + zod.** The Inputs screen ([`ui-draft.md`](ui-draft.md) § 3.1) has one required field, three optional ones, and non-trivial upload semantics. react-hook-form avoids re-render storms; zod gives the validation schema a single source of truth that *also* generates TypeScript types for the same form. The `@hookform/resolvers` package bridges the two.
- **Why Recharts.** The *confidence indicator*, the per-criterion score bars, and any reliability/spread visualisations ([`requirements.md`](requirements.md) § 5.2 SR-UI-07) need a charting library. Recharts is composable, accessible, and works inside React's rendering model without imperative canvas code.
- **Why Vitest + Testing Library + Playwright.** Vitest shares Vite's config and runs unit/component tests against jsdom at native speed. Testing Library enforces the *"test behaviour, not implementation"* discipline that matches the V-model's acceptance-tests-at-the-top of this project. Playwright covers the SR-UI requirements end-to-end in a real browser — the level at which those requirements actually mean something.
- **Why the HTTP/JSON boundary.** Keeping the UI and the Python back-end as two deployables matches the hermetic-task philosophy (§ 2.2): each side is testable standalone, and the same back-end can be driven from the SPA, from the CLI, or from an external orchestrator without any front-end concerns leaking into the Python modules. It also matches the architecture of the adjacent projects in this repository group, so the deployment story in § 5.11 *DR-DEP* will be a short step from the pattern already in use.
- **What this decision does not commit.** The Python HTTP server (FastAPI, Flask, Starlette, etc.) is deferred to decision **#10**. Authentication is not in scope — the application is a single-user local tool per [`requirements.md`](requirements.md) § 1.2 *out of scope*. Multi-page vs. multi-route navigation inside the SPA is a DR-UI concern, not a technology-stack concern, and is deferred to § 5.6.

### 3.4 File and document parsing libraries

**Decision.** A single `InputParser` module is the only component that reads teacher-provided files from disk. It exposes one entry point per supported format, each of which returns the same data structure — a `ParsedDocument` containing the extracted text, per-page or per-section metadata, and a provenance record (source filename, content hash, parser name, parser version). The Assessment stage never branches on file format.

The per-format implementations are:

| Format | Library | Used for |
|---|---|---|
| `.txt` | Python stdlib (`pathlib` + encoding detection via `charset-normalizer`) | Exam question, starting rubric text, plain-text teaching material |
| `.md` | `markdown-it-py` | Rubric drafts written in markdown, teaching material in markdown |
| `.pdf` (text layer) | `pypdf` (default), `pdfplumber` (when layout matters) | Exam question, teaching material, starting rubric, student copies that are typed |
| `.docx` | `python-docx` | Rubric drafts exported from Word |
| Image / handwritten PDF | *Delegated to OCR, decision § 3.5* | Scanned student copies |

**Rationale.**

- **Why a single `InputParser` module with a uniform output.** The Assessment Engine, the Improvement Generator, and the Audit Recorder all consume *text plus provenance*; they should be unaware of whether that text came from a `.pdf`, a `.docx`, or a `.txt`. Putting format handling anywhere else leaks file-format branching into modules that have nothing to do with file formats. This realisation of the dispatch pattern also matches SR-IN-08 (partial-failure reporting): the one place that needs to know which files failed to parse is the parser itself.
- **Why `pypdf` as the default PDF library.** It is pure-Python, dependency-light, actively maintained, and handles the majority of text-layer PDF extractions correctly. It is the right default for teaching material and rubric drafts, which are almost always text-layer PDFs exported from Word or LaTeX.
- **Why `pdfplumber` as the fallback.** PDFs that carry layout (two-column exam sheets, tables of rubric criteria, boxed answer regions) need layout-aware extraction. `pdfplumber` provides page-level geometry, table extraction, and bounding boxes — the primitives needed when `pypdf`'s flat-text output scrambles the reading order. The `InputParser` tries `pypdf` first and falls back to `pdfplumber` when the extracted text looks degenerate (very short, no sentence punctuation, or otherwise below a defensive threshold); the specific fallback rule is a DR-IO concern (§ 5.7) rather than a technology decision.
- **Why `markdown-it-py` rather than stripping markdown with a regex.** Teachers who write in markdown use headers, bullet lists, and bold emphasis deliberately — those structures carry meaning for the Assessment Engine (a criterion named in a heading is structurally different from a criterion named in a bullet). `markdown-it-py` gives an AST that the parser collapses to clean text while preserving structural tags in the `ParsedDocument` metadata. A regex would discard that signal.
- **Why `python-docx` rather than converting `.docx` to `.pdf` first.** Round-tripping through PDF loses the document's native structure (styles, headings, numbered lists) that `python-docx` exposes directly. The dependency is small and the output is higher-fidelity than any conversion chain.
- **Why stdlib + `charset-normalizer` for `.txt`.** Plain text is a trap: the file is almost always ASCII or UTF-8, but the one time it is not, a silent decoding error corrupts the exam question. `charset-normalizer` is a tiny, pure-Python encoding detector that fails loudly when the input is unreadable rather than returning garbage.
- **What this decision does not commit.** OCR for handwritten student copies is decision **#5** (§ 3.5). The content-cache strategy that keys on the content hash of parsed documents is decision **#8** (§ 3.8). The shape of the `ParsedDocument` data class itself is a DR-IO concern and is specified in § 5.7.

### 3.5 OCR for handwritten student copies

**Decision.** Handwritten student copies are transcribed by sending each page as a multimodal image input to **Claude Sonnet 4.6** through the same `gateway.measure()` entry point locked in § 3.2. The OCR call is a normal structured-output measurement: the prompt is `prompts/ocr_student_copy.md`, the output schema is a `TranscribedPage` Pydantic model (per-page text, a confidence indicator, and any "unreadable region" markers), and the call is subject to the same content-hash caching, audit logging, and retry-once validation as every other model call in the system.

The `InputParser` module delegates to a `StudentCopyReader` interface for every file it identifies as a handwritten student copy (either a scanned PDF with no text layer, or a raw image). The primary implementation of that interface is the Claude-backed reader; a dedicated-OCR backend (Azure Document Intelligence, AWS Textract, Google Cloud Vision, or a self-hosted TrOCR model) can replace it without touching any other module. The interface contract is specified in § 5.7 *DR-IO*.

**Rationale.**

- **Why Claude multimodal as the primary path rather than a dedicated OCR service.** The system already has exactly one external dependency for model calls (Anthropic, locked in § 3.1). Adding a dedicated OCR service would introduce a second cloud dependency, a second set of credentials, a second rate-limit regime, a second billing stream, and a second code path in the audit bundle — all to solve one corner of one input type. Claude Sonnet 4.6 accepts images natively through the existing SDK, so the OCR call uses the same Gateway, the same caching, the same logging, and the same failure semantics as the rest of the system.
- **Why a multimodal LLM is competitive with dedicated OCR on this task.** Frontier multimodal models are now strong at handwritten-text transcription, particularly when the task is bounded (student answers to a known exam question, not arbitrary scanned archives). The accuracy loss against a specialised service is small, and the specialised service's advantage narrows further once the contextual anchoring of the exam question is added to the prompt — which is natural to do here because the exam question is already in hand.
- **Why the `StudentCopyReader` interface matters even though there is only one implementation today.** The interface is a defensive seam. If a reviewer wants to see a different OCR backend, or if a future deployment target (EPFL on-prem RCP, local LLMs per CLAUDE.md § 6) rules out cloud multimodal calls, a second implementation slots in without any ripple. This realises the locked architectural commitment #3 (pluggable backend) for the OCR path specifically.
- **Why routing the call through `gateway.measure()` rather than a bespoke OCR code path.** Two concrete benefits: first, the audit bundle becomes complete — every model call, OCR or otherwise, has the same trace shape and the same content-hash identity. Second, the retry-once validation behaviour from § 3.2 applies to OCR failures for free: if the model returns a `TranscribedPage` that does not match the schema (for example, because the image was blank or corrupted), the Gateway retries once with the validation error in context before recording a measurement failure.
- **What this decision does not commit.** The specific prompt text in `prompts/ocr_student_copy.md`, the exact shape of the `TranscribedPage` schema, the page-splitting strategy for multi-page scans, and the per-page confidence-indicator calibration are all DR-IO concerns and are specified in § 5.7. The decision to use OCR at all — as opposed to asking the teacher to type in transcriptions manually — is implicit in SR-IN-06 and is not revisited here.

### 3.6 Schema language for the *Explained rubric file*

**Decision.** The contract of the *Explained rubric file* (see [`requirements.md`](requirements.md) § 2 and SR-OUT-01 to SR-OUT-05) is expressed as a **Pydantic model** in the Python back-end. At build time, a `make schemas` step calls `model_json_schema()` on that model and writes the result to a versioned file on disk:

```
schemas/explained_rubric_file.v{MAJOR}.{MINOR}.schema.json
```

The JSON Schema file is **checked into the repository**. It is the inspectable artefact a reviewer can open without running any Python. The front-end derives two things from the same JSON Schema file:

- **TypeScript types** via `json-schema-to-typescript` (build-time codegen into `src/types/explained-rubric-file.ts`).
- **Runtime zod validators** via `json-schema-to-zod` (build-time codegen into `src/lib/schemas/explained-rubric-file.ts`).

This means every layer of the system — Python back-end, JSON Schema file, TypeScript types, zod validators — has **one source of truth** and three derived artefacts, all traceable to a single Pydantic class.

The Pydantic model and the JSON Schema file are versioned together following semver on the `ExplainedRubricFile` contract itself, independent of the application version:

- **MAJOR** bump when a field is removed or its type changes incompatibly.
- **MINOR** bump when a field is added.
- **Patch** bumps are not used (schema changes are always tracked).

The file itself carries its schema version in a top-level `schema_version` field (SR-OUT-02), so any consumer — the download button in the UI, a reviewer inspecting the JSON, a future graders' tool reading the rubric — can assert the contract it reads against.

**Rationale.**

- **Why Pydantic as the source of truth.** Pydantic is already locked in § 3.2 as the validation layer for LLM structured outputs. Reusing it for the deliverable file's contract means one validation library, one schema format, one mental model. A call to `gateway.measure(..., schema=ExplainedRubricFile)` and a call to `ExplainedRubricFile.model_validate_json(downloaded_file)` share the same class — there is no second definition to drift.
- **Why also emit a standalone JSON Schema file.** The brief asks for a JSON file as the deliverable. The reviewer should be able to look at the shape of that file without running any Python. A standalone JSON Schema file is that inspection artefact: self-describing, language-agnostic, and directly consumable by any JSON-Schema-aware tool (`jq`, IDE plugins, API documentation generators).
- **Why generated, not hand-written, JSON Schema.** Hand-writing the JSON Schema alongside the Pydantic class would immediately create a drift surface between two definitions of the same contract. Pydantic's `model_json_schema()` emits a JSON-Schema-draft-2020-12 document directly from the class — the Python class is the definition, and the file is its projection.
- **Why generate TypeScript types and zod validators from the JSON Schema rather than writing them by hand.** Same argument at the front-end boundary: the TypeScript types and the zod validators are projections of the JSON Schema, not independent rewrites. The build pipeline fails if the generated TypeScript does not compile, which catches contract-drift at front-end build time rather than at runtime in the teacher's browser.
- **Why a checked-in schema file rather than serving it from the back-end API.** The schema is not runtime data — it is a build-time artefact of the code that produced it. Checking it in makes the contract part of the codebase's version history, and it makes the reviewer's first question (*"what does the output file look like?"*) answerable by opening one file on GitHub. A runtime `GET /api/schema` endpoint adds nothing and creates a second path to the same information.
- **Why an independent version on the schema itself.** The application might ship many releases without changing the contract shape; conversely, a contract change might happen on a mid-release refactor. Tying the schema version to the application version would either delay needed bumps or force spurious ones. A separate semver on `ExplainedRubricFile` lets the contract evolve at its own pace and lets consumers assert what they rely on.
- **What this decision does not commit.** The *content* of the schema — the specific fields of `ExplainedRubricFile`, their types, their required/optional status — is § 4 *Data models* and § 5.3 *DR-DAT*. The versioning policy for the schemas of *non-deliverable* objects (Assessment finding, Proposed change, Audit bundle) is also a DR-DAT concern; this decision covers the deliverable file only.

### 3.7 Configuration mechanism and secret handling

**Decision.** All runtime configuration is held in a single typed `Settings` class built on `pydantic-settings`. It reads from process environment variables; for developer convenience, it also loads a **gitignored `.env`** file if present. Secrets are held as `SecretStr`, whose raw value is only ever read at the single call site that needs it. A committed `.env.example` enumerates every variable the application understands, with empty values for all secrets.

No secret ever appears in any artefact that is committed to the repository, baked into a Docker image, or recorded in an audit bundle. The only place a secret exists is the environment of the process that needs it.

```python
# (illustrative — actual definition lives in DR-ARC, § 5.1)
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",                 # dev-only convenience; ignored if absent
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # Secrets
    anthropic_api_key: SecretStr
    # Non-secret runtime config
    default_model: str = "claude-sonnet-4-6"
    llm_max_samples: int = 5
    audit_bundle_dir: Path = Path("runs")
    prompts_dir: Path = Path("prompts")
    schemas_dir: Path = Path("schemas")
    # HTTP back-end
    api_host: str = "127.0.0.1"
    api_port: int = 8765
```

This class is instantiated once at process start, imported by the modules that need it, and never mutated at runtime.

**Rationale.**

- **Why `pydantic-settings` rather than a hand-rolled config loader.** Pydantic is already in the stack (§ 3.2 for LLM structured output validation, § 3.6 for the deliverable's schema). Reusing it for application configuration means one validation library, one typed-model mental model, and one way to talk about required versus optional fields. The `Settings` class is also the auditable list of every tunable the application exposes — if a reviewer wants to know *what can be configured*, the answer is to open one file.
- **Why environment variables as the only runtime source.** This is the 12-factor default and is also the pattern that orchestrators (Validance, Snakemake, Airflow, plain `docker run`) already know how to feed into a process. Anything more elaborate creates a second path the orchestrator must learn to populate.
- **Why `.env` is *dev-only convenience*, not a config format.** The `.env` loader is strictly syntactic sugar on top of the environment-variable path: if the file exists, its entries are loaded into `os.environ` before `Settings` reads them. A reviewer cloning the repository copies `.env.example` to `.env`, fills in `ANTHROPIC_API_KEY`, and the application runs. In any environment that already supplies the variables (CI, container runtime, orchestrator), the `.env` file is simply absent and the loader is a no-op. The application has **no two modes** — there is only one path, and `.env` is an optional entry-point to it.
- **Why `SecretStr` rather than `str`.** `SecretStr` makes accidental leakage structurally difficult. Its default repr is `SecretStr('**********')`; it never stringifies to its value; serialising it to JSON emits a redaction token rather than the secret. The only way to get the raw bytes is `get_secret_value()`, which is called in exactly one place — inside the LLM Gateway, when constructing the Anthropic client. This means secrets are structurally impossible to land in log lines, stack traces, or the audit bundle (§ 5.8 *DR-OBS*).
- **Why a committed `.env.example` rather than hand-maintained documentation.** The example file is the single source of truth for *which variables exist*. It is generated from the `Settings` class (or kept in lock-step with it by a small check in tests) so a new field cannot be added without the reviewer also seeing it in the example. A prose README table would drift.

**Runtime under an external orchestrator.**

The same `Settings` class and the same code run unchanged whether the application is invoked standalone or as one task in an external workflow engine. The difference is only in *who puts variables into the environment*:

| Mode | Source of `ANTHROPIC_API_KEY` | Source of `default_model` etc. |
|---|---|---|
| Standalone | Reviewer's `.env` file, loaded by `pydantic-settings` at boot | Same, or the built-in defaults on the `Settings` class |
| External orchestrator (e.g. Validance) | The orchestrator's secret store, injected as an env var when the task container starts | Task parameters in the workflow definition, passed through to the task container as env vars |

The workflow definition that registers the application as a task with such an orchestrator declares **the *names* of the environment variables it requires**, not their values. The secret store and the workflow definition are therefore two separate things: the workflow is secret-free by construction, and any committed artefact that describes it (catalog entry, compose file, registration script) is also secret-free. At task launch, the orchestrator resolves the declared names against its secret store and injects the resulting env vars into the container; the task then boots the same `Settings` class and is unaware that a different layer supplied them.

This arrangement is the concrete realisation of the hermetic-task philosophy from § 2.2 on the *configuration* axis: the task declares its inputs (including the names of secrets it requires), and the environment that supplies them is pluggable. The application therefore satisfies both locked architectural commitment #4 (*Validance is one possible execution layer, the deliverable runs standalone with no Validance dependency*) and the invariant that registered workflows must never carry secret values.

- **What this decision does not commit.** The deterministic-execution policy (temperature, seed, sampling discipline) that `llm_max_samples` ties into is decision **#9** (§ 3.9). The packaging and deployment topology that decides whether the back-end is a long-running server, a one-shot task, or both is decision **#10** (§ 3.10). The exact list of `Settings` fields will grow as later decisions land — this section locks the mechanism, not the full field list.

### 3.8 Caching strategy

**Decision.** The application has **no application-level cache**. No on-disk cache directory, no in-memory content-hash map, no request deduplication inside the LLM Gateway or the `InputParser`. Every run performs every call it needs from scratch.

**Rationale.**

A caching layer solves one or more of four concerns. For this deliverable, none of the four belongs in application code:

| Concern | Why it is not a reason to cache at the application layer |
|---|---|
| *Cost of repeated external calls* | A run is on the order of a handful of model calls; at the per-call cost of the default model (§ 3.1), repeating a run is negligible compared to the engineering cost of a cache invalidation surface. Cost is not a decision driver at this scale. |
| *Cross-run deduplication when the same inputs are seen twice* | This is the **external orchestrator's** job at the *task* granularity. Content-hashed task caching is a first-class feature of Validance, Snakemake, Airflow, and every comparable engine. A second cache inside the application competes with the orchestrator's cache at a finer granularity, with different keys and different invalidation semantics — that is a bug surface, not a feature. |
| *Recovery from transient API errors* | This is the **Anthropic SDK's** job. The SDK retries on rate limits and 5xx responses with exponential backoff. Re-implementing retry inside the Gateway would duplicate well-tested behaviour. |
| *Reproducibility of tests without live API calls* | Handled by **mocking at the Gateway seam**: unit tests replace `gateway.measure()` with a stub that returns canned responses. This is test hygiene, not caching. It also keeps CI deterministic and offline, which a cache would not. |

The positive consequences of **not** building a cache are:

- **Hermetic tasks stay hermetic.** A task that reads from and writes to an undeclared cache directory has hidden I/O. The hermetic-task philosophy of § 2.2 is undermined. Dropping the cache means every input and output of every task is declared and visible.
- **One source of truth per run.** With no cache, an audit bundle describes *everything* the run did. With a cache, part of the story is *"we did not run this step because a previous run had the same key"*, which the audit bundle would have to reconstruct after the fact. Removing the cache removes this whole category of audit-log complexity.
- **Orchestrator compatibility is clean.** Under Validance (or any other external engine), the engine's task-level cache works exactly as designed. The application does not fight it, does not shadow it, and does not need to know it exists.

- **What this decision does not commit.** Deterministic execution (temperature, sampling discipline) is decision **#9** (§ 3.9). The test fixture strategy for mocking `gateway.measure()` is a DR-LLM concern (§ 5.2). The orchestrator's cache behaviour is out of scope for this document — we rely on it being present in any orchestrated deployment without specifying its implementation.

### 3.9 Deterministic execution policy

**Decision.** The application makes two separate claims about reproducibility:

1. **Bit-identical reproducibility of LLM outputs is explicitly *not* claimed.** It is not achievable for hosted LLM inference in 2026, regardless of temperature settings, and claiming it would mislead a reviewer.
2. **What is claimed is (a) *measurement-level stability* — the same structured finding is returned for the overwhelming majority of inputs across repeated runs — and (b) *audit-level reconstructability* — every call's prompt hash, schema hash, inputs, model identifier, temperature, and raw response are recorded, so a reviewer can reconstruct what happened on any past run.**

The operational rules that flow from these claims:

| Call class | Temperature | Samples | Why |
|---|---|---|---|
| Extraction, classification, "single correct answer" measurements | `0.0` | `1` | Token-level flips are rare at temperature 0; the tool-use structured output collapses any remaining surface variation to the same Pydantic value. |
| Reliability measurements that drive the *confidence indicator* (grader panels, paraphrase agreement, span-level ambiguity) | `> 0.0` (default `0.7`) | `k > 1` (default `5`) | Spread across samples *is* the signal. Forcing temperature 0 here would defeat the purpose. |

The default model pointer (`claude-sonnet-4-6` in § 3.1) is replaced by a specific snapshot version whenever the provider publishes one. The pinned snapshot is stored in the `default_model` field of the `Settings` class (§ 3.7) and recorded in every audit bundle entry.

**Rationale.**

- **Why not claim bit-identity.** Temperature 0 does not make hosted LLM inference deterministic. GPU floating-point non-associativity and server-side batching effects produce logits that differ in the last few bits between runs, and at a near-tie those bits decide the argmax token. The Anthropic Messages API does not currently expose a `seed` parameter (unlike OpenAI's *"mostly deterministic"* `seed` + `system_fingerprint` pair), so there is no knob to ask the provider for stronger guarantees. Claiming bit-identity in a design document is factually wrong and a red flag to any reviewer who has run production LLM workloads.
- **Why temperature 0 for single-sample calls anyway.** It is still the right choice for measurements that have one correct answer — extraction, classification, JSON field population. At temperature 0, token-level flips are rare enough that the *structured* output (the Pydantic object returned by the tool call) is empirically stable across runs for the overwhelming majority of inputs. The tool-use schema from § 3.2 acts as a projection that collapses surface-level variation to the same measurement value, which further stabilises the result.
- **Why temperature > 0 for sampling calls.** Determinism here is explicitly *unwanted*. The grader panel, the paraphrase agreement measurement, and the span-level ambiguity measurement all draw `k` samples *because* they want to observe disagreement. Forcing temperature 0 would flatten the spread to near-zero, hide genuine ambiguity, and produce an inflated *confidence indicator*. The statistical signal depends on the temperature being non-zero; `0.7` is the default unless a specific measurement has calibrated a different value.
- **Why pin the model to a snapshot version.** `claude-sonnet-4-6` is a provider-maintained pointer that can be silently updated. A reviewer running the same deliverable a month later against an updated snapshot is running a subtly different measurement instrument. Pinning to a published snapshot tag turns *"we used Sonnet"* into *"we used Sonnet at this specific weights version"* — a meaningfully stronger claim, at no cost.
- **Why audit-level reconstructability is the honest guarantee.** The audit bundle (§ 5.8 *DR-OBS*) records the prompt hash, the schema hash, the inputs hash, the pinned model identifier, the temperature, the number of samples, and the raw response of every LLM call. This does not let a reviewer **reproduce** a past run (that requires a time machine for the inference server's internal state), but it lets them **reconstruct** exactly what the system did, examine the inputs and outputs, and decide whether the measurement was reasonable. For an engineering-rigor deliverable, *reconstructability* is the meaningful property; *reproducibility* is a marketing word.

- **What this decision does not commit.** The numerical default of `k` (number of samples for reliability measurements) and the per-measurement temperature calibration are DR-LLM concerns (§ 5.2). The exact format of audit bundle entries is a DR-OBS concern (§ 5.8). The fallback behaviour when the provider deprecates a pinned snapshot is an operational concern, not a design one, and is noted in § 5.11 *DR-DEP*.

### 3.10 Deployment topology, packaging

**Decision.** The application ships as **two artefacts that together form one deliverable**:

1. **A Python package** for the back-end (Orchestrator, Input Parser, Assessment Engine, Improvement Generator, Output Writer, LLM Gateway, Audit Recorder). Packaging uses `pyproject.toml` (PEP 621). Two console-script entry points are exposed:
   - `grading-rubric-api` — runs the FastAPI HTTP server that the front-end talks to.
   - `grading-rubric-cli` — runs a single assessment end-to-end from the command line without the front-end, driving the same Orchestrator over the same hermetic tasks.
2. **A Vite static build** for the front-end (SPA from § 3.3). Output is a directory of static files (`index.html`, JS bundles, CSS, assets) that any static file server can serve.

The HTTP server is **FastAPI** (locking the deferred "specific Python HTTP server" question from § 3.3 and § 3.7):

- **FastAPI is Pydantic-native.** The same Pydantic classes that define the LLM structured-output schemas (§ 3.2), the `ExplainedRubricFile` contract (§ 3.6), and the `Settings` loader (§ 3.7) become the API response and request bodies with no second mapping layer. Contract drift between the internal models and the API is structurally impossible.
- **FastAPI generates an OpenAPI document from the route signatures at runtime**, which is the natural transport contract for the SPA's `fetch` layer and an inspectable artefact for a reviewer.
- **Async is native**, which matches the streaming-progress requirement SR-UI-04 and the polling model TanStack Query uses on the front-end.

A top-level `Makefile` is the single entry-point surface a reviewer actually touches:

| Target | What it does |
|---|---|
| `make install` | Creates a Python virtualenv, installs the back-end package in editable mode, runs `npm install` / `bun install` in the front-end. |
| `make dev` | Starts the FastAPI back-end on `127.0.0.1:8765` and the Vite dev server on `127.0.0.1:5173` with HMR. |
| `make build` | Runs the Vite production build; outputs the static SPA to `frontend/dist/`. |
| `make test` | Runs `pytest` for the back-end, `vitest` for the front-end unit tests, and `playwright test` for the front-end E2E tests. |
| `make schemas` | Regenerates `schemas/explained_rubric_file.v*.schema.json` from the Pydantic source of truth (§ 3.6), plus the generated TypeScript types and zod validators. |
| `make run` | Convenience target that runs `make build` and then starts the back-end in a single process that also serves the built SPA as static files — the "reviewer clones and runs the deliverable" path. |

The repository layout is two top-level directories (`backend/` for the Python package, `frontend/` for the Vite project) plus the top-level `Makefile`, `README.md`, `.env.example`, and `schemas/` directory. DR-ARC (§ 5.1) and DR-DEP (§ 5.11) specify the internal package layout of each.

**Rationale.**

- **Why FastAPI and not Flask / Starlette / Django.** Starlette alone is too low-level for the automatic Pydantic ↔ API-body integration we actually want. Flask is battle-tested but has no native Pydantic story, and pairing it with one of several Pydantic-for-Flask adapters adds a layer whose only job is to replicate what FastAPI does natively. Django is over-scoped for a single-user local tool with no database, no ORM, and no admin interface. FastAPI is the shape-matched choice, and it is also the lingua franca of modern Python AI back-ends, which minimises the reviewer's surprise.
- **Why ship a CLI entry point alongside the API server.** The CLI is the direct proof that the back-end is hermetic: a reviewer who does not want to touch the SPA can run `grading-rubric-cli --exam exam.pdf --rubric draft.md` and get an `ExplainedRubricFile` on disk. It is also the entry point that any external orchestrator calls. The same code path, driven from two entry points, is the concrete realisation of the hermetic-task philosophy from § 2.2 on the *invocation* axis.
- **Why a `Makefile` as the single entry-point surface.** A reviewer should not need to learn the repository's internals to run it. `make install && make run` must work after a fresh clone. A Makefile is the universally-understood "here are the verbs" document; a `README.md` table of commands would drift; a shell script would hide the steps. The Makefile targets are the verbs; their bodies are the documentation.
- **Why a `make run` target that serves the built SPA from the FastAPI process.** In development the Vite dev server is the right answer (HMR, source maps). For the "clone and demo" path we want one command and one process, no nginx, no separate static server. FastAPI can serve the static SPA from the same process by mounting `frontend/dist/` as a `StaticFiles` route. This keeps the deliverable to one port and one process in demo mode, and the dual-process mode in development.
- **Why two top-level directories (`backend/` and `frontend/`) rather than a single package.** The two sides are two build systems and two language ecosystems. Physically separating them in the repository tree is the honest representation; a single monolithic tree would obscure which files belong to which build. It also matches the adjacent projects' layout in this repository group, so a reviewer familiar with any one of them knows where to look.
- **Why not ship a Docker image as the primary deliverable.** Docker is a valid secondary target (a `Dockerfile` in `backend/` is trivial once the Python package exists), but the primary path must be `git clone && make install && make run` on a developer machine, because that is the path the reviewer will actually take. Anchoring the deliverable to a Docker image would force the reviewer to have Docker running and would add a build step between their clone and their first output; that is friction with no corresponding benefit for a single-user local tool.

- **What this decision does not commit.** The exact set of API routes, request/response shapes, and status codes is a DR-DEP concern (§ 5.11) and will be filled alongside DR-UI (§ 5.6). The internal package layout of `backend/` (modules, dependency direction, import rules) is DR-ARC (§ 5.1). The Docker image, if we ship one, and the CI pipeline, if we ship one, are packaging refinements that do not change the core decision.

### 3.11 Orchestration layer

**Decision.** The deliverable embeds **no orchestration layer**. The default mode of the application is a single Python process (started by `make run` or `grading-rubric-api`) plus a static SPA, and one run of one assessment is driven by the in-process Orchestrator module from § 2.1. Nothing more is built, required, or shipped.

This satisfies the locked architectural commitment #4 from `CLAUDE.md` § 6 directly: *the deliverable runs standalone with no Validance dependency*.

The hermetic-task structure of § 2.2 nonetheless makes the same code **trivially wrappable** by any external orchestration engine. The conditions for the wrap to work are already locked by earlier decisions:

- Each pipeline stage has structured inputs and structured outputs (§ 2.2).
- The Settings class reads secrets from the environment and never from files committed to the repo (§ 3.7), so a registered workflow is secret-free by construction.
- The application has no on-disk cache (§ 3.8), so there is no hidden state competing with the orchestrator's task-level cache.
- Every LLM call is auditable and routed through one Gateway (§ 3.2), so a task restart produces a complete audit trail.

§ 5.11 *DR-DEP* will include a **single concrete reference example** of wrapping the deliverable as a Validance task (catalog entry, task parameters, declared environment variables, expected outputs), as documentation of the orchestrator-ready property — not as a shipping requirement.

**Rationale.**

- **Why no embedded orchestration layer.** Embedding a workflow engine in a single-user local tool adds a dependency that the reviewer has to install, configure, and understand, to solve a problem the reviewer does not have (scheduling, retries across task boundaries, multi-run coordination). The cost is real and the benefit is zero for the default use case. Anything more than *"start the server, open the browser, upload files"* would be a negative feature.
- **Why keep the architecture orchestrator-ready.** Orchestrator-readiness is free because we already paid for it — the hermetic-task philosophy was locked back in § 2.2, the configuration story in § 3.7, and the no-cache decision in § 3.8. The readiness is a consequence of choices that stand on their own merits.
- **Why show one concrete Validance wrap in DR-DEP.** A reviewer who reads the design document will see many claims about orchestrator-compatibility; one worked example is what turns those claims into something they can point at. It also makes the boundary between *deliverable* and *orchestration concern* explicit: everything in the main code path is in the deliverable; the Validance wrap is a reference artefact.

- **What this decision does not commit.** The Validance catalog entry itself, the exact task parameters, and the output file registration strategy are DR-DEP concerns (§ 5.11). This decision commits only that *there is no orchestration layer inside the deliverable*.

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
| 0.11.0 | 2026-04-11 | Wiktor Lisowski | Locked the final three technology decisions. **#9 Deterministic execution (§ 3.9)**: temperature 0 for single-sample extraction/classification, temperature > 0 for `samples > 1` reliability measurements (default `k = 5`, temperature `0.7`), model pinned to a snapshot version when the provider publishes one; bit-identical LLM reproducibility explicitly *not* claimed (GPU floating-point non-determinism, server-side batching, no `seed` parameter on the Anthropic Messages API) — the honest guarantee is measurement-level stability plus audit-level reconstructability via the audit bundle. **#10 Deployment topology and packaging (§ 3.10)**: two artefacts forming one deliverable — a Python package with `pyproject.toml` and two console-script entry points (`grading-rubric-api`, `grading-rubric-cli`) plus a Vite static build for the front-end; FastAPI as the HTTP server (Pydantic-native, no second mapping layer); a top-level `Makefile` (`install` / `dev` / `build` / `test` / `schemas` / `run`) as the single entry-point surface; `make run` serves the built SPA from the FastAPI process for the one-command demo path; repository layout is `backend/` + `frontend/` + `schemas/` + top-level meta files; Docker is a possible secondary target, not the primary path. **#11 Orchestration layer (§ 3.11)**: none embedded in the deliverable — default mode is a single Python process plus a static SPA; the hermetic-task structure of § 2.2 makes the same code trivially wrappable by any external engine (the conditions are already paid for by § 3.7 env-only secrets and § 3.8 no-cache); § 5.11 *DR-DEP* will include one concrete Validance wrap as a reference example, not as a shipping requirement. All 11 technology decisions now locked; § 4 *Data models* and § 5 *Design Requirements* are next. |
| 0.10.1 | 2026-04-11 | Wiktor Lisowski | § 3.8 wording fix: re-cast the *cost of repeated external calls* row to argue from engineering cost and scale rather than from API-key provenance. No change to the decision itself. |
| 0.10.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #8 (caching strategy) in § 3.8: the application has **no application-level cache**. Cost at this scale is not a decision driver; cross-run deduplication is the external orchestrator's job at task granularity; transient-error retries are the Anthropic SDK's job; reproducibility of tests is handled by mocking at the Gateway seam. Consequences: hermetic tasks stay hermetic (no hidden I/O to a cache directory), audit bundles describe *everything* a run did (no "we did not run this step because of a cache hit" complexity), and orchestrator cache behaviour is unopposed. Cleanups in the same change: removed the *Content cache* module from § 2.1; dropped the cache reference from § 2.3's *one door to the API* bullet; removed `cache_dir` from the illustrative `Settings` class in § 3.7 and dropped its forward reference. Decisions #9–#11 still pending. |
| 0.9.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #7 (configuration mechanism and secret handling) in § 3.7: single typed `Settings` class built on `pydantic-settings`; process environment variables as the only runtime source; gitignored `.env` for dev convenience loaded automatically when present; committed `.env.example` as the single source of truth for *which* variables exist; secrets held as `SecretStr` so they cannot land in logs, stack traces, or the audit bundle. The same code runs unchanged under an external orchestrator (e.g. Validance): the registered workflow declares the *names* of required secrets, not their values; the orchestrator's secret store injects them into the container's environment at task launch; the task boots the same `Settings` class. Committed artefacts — repo, image, workflow definition — are secret-free by construction. Decisions #8–#11 still pending. |
| 0.8.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #6 (schema language for the *Explained rubric file*) in § 3.6: the Pydantic class is the single source of truth; a `make schemas` build step emits a versioned `schemas/explained_rubric_file.vMAJOR.MINOR.schema.json` file that is checked into the repo as the language-agnostic inspection artefact for reviewers; the front-end derives TypeScript types (`json-schema-to-typescript`) and runtime zod validators (`json-schema-to-zod`) from the same JSON Schema file; the deliverable JSON carries its `schema_version` in a top-level field and the schema is versioned independently of the application. Decisions #7–#11 still pending. |
| 0.7.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #5 (OCR for handwritten student copies) in § 3.5: Claude Sonnet 4.6 multimodal input as the primary OCR backend, invoked through the same `gateway.measure()` entry point as every other model call (same caching, same audit logging, same retry-once validation). The `InputParser` delegates to a `StudentCopyReader` interface whose contract is specified in § 5.7 *DR-IO*; a dedicated-OCR backend (Azure Document Intelligence, Textract, Cloud Vision, TrOCR, etc.) can replace the primary implementation without touching any other module. Avoids adding a second cloud dependency beyond Anthropic. Decisions #6–#11 still pending. |
| 0.6.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #4 (file and document parsing libraries) in § 3.4: a single `InputParser` module with one entry point per format, returning a uniform `ParsedDocument` (text + metadata + provenance). Libraries: `pypdf` as the default PDF extractor with `pdfplumber` as a layout-aware fallback; stdlib + `charset-normalizer` for `.txt`; `markdown-it-py` for `.md`; `python-docx` for `.docx`. OCR for handwritten copies remains decision #5. Decisions #5–#11 still pending. |
| 0.5.0 | 2026-04-11 | Wiktor Lisowski | Locked decision #3 (UI framework) in § 3.3: single-page application built with Vite + React 18 + TypeScript, shadcn/ui (Radix + Tailwind), React Router, TanStack Query, react-hook-form + zod, Recharts, Sonner, Framer Motion, lucide-react; Vitest + Testing Library for unit/component tests, Playwright for E2E. The SPA is a separate deployable from the Python back-end and talks to it over HTTP/JSON with the base URL configurable via `VITE_API_BASE`. Choice of the specific Python HTTP server deferred to decision #10. Decisions #4–#11 still pending. |
| 0.4.0 | 2026-04-11 | Wiktor Lisowski | Added § 1.4 *Design glossary* anchoring the design-internal term *Sample (LLM)*. Locked decision #2 (prompting and structured-output approach) in § 3.2: single `gateway.measure(prompt_id, inputs, schema, samples, model)` entry point; Anthropic tool use for structured output (no `instructor` / `langchain` / `dspy`); prompts as markdown files with YAML front-matter; content-hashed prompt + schema identity recorded in the audit bundle; Pydantic validation with retry-once on failure; sampling as a parameter; aggregation left to callers. Decisions #3–#11 still pending. |
| 0.3.0 | 2026-04-11 | Wiktor Lisowski | Started filling § 3 *Technology stack and decision register*. Decision #1 (LLM provider, SDK, and default model) locked in § 3.1: Anthropic via the `anthropic` Python SDK (≥ 0.40), default model `claude-sonnet-4-6`, single default with per-call override supported by the LLM Gateway. Per-task model routing deferred as a future refinement. Decisions #2–#11 still pending. |
| 0.2.2 | 2026-04-11 | Wiktor Lisowski | § 2.2: dropped the *"cost of this discipline is real"* framing and the enumeration of forbidden shortcuts (shared state, singletons, implicit caches — implied by *hermetic*). Sentence now states only what the discipline yields. |
| 0.2.1 | 2026-04-11 | Wiktor Lisowski | § 2 trim pass: removed redundant repetitions of *"Validance is one possible execution layer"*, *"orchestration-agnostic"*, *"pluggable backend"*, and the mechanical *"design-layer realization of locked architectural commitment #X"* footers from § 2.3 / § 2.4 / § 2.5. Tightened § 2.3 opening paragraph. No content lost; the same points are now made once each. |
| 0.2.0 | 2026-04-11 | Wiktor Lisowski | Filled § 2 *Architectural overview*: § 2.1 system diagram (eight modules — UI, Orchestrator, Input Parser, Assessment Engine, Improvement Generator, Output Writer, plus the cross-cutting LLM Gateway / Audit Recorder / Scorer interface / Content cache / Data models), and § 2.2–2.5 stating the four guiding principles (hermetic tasks, LLMs as measurement instruments, data-aware system, human in the loop) as the design-layer realizations of locked architectural commitments #2, #4, #5, #6, and #7. No DRs added. No technology decisions made yet. |
| 0.1.0 | 2026-04-11 | Wiktor Lisowski | Initial skeleton. Section 1 (intro, scope, references) drafted. Sections 2 (architectural overview), 3 (technology stack and decision register — 11 pending decisions listed), 4 (data models), 5 (eleven DR groups DR-ARC through DR-DEP, each with an intent paragraph), 6 (traceability), and 7 (modlog) created as placeholders to be filled iteratively. No DRs and no technology decisions made yet. |
