# Grading Rubric Studio — Design

**Version**: 0.12.1
**Date**: 2026-04-11
**Status**: Architectural overview filled; all 11 technology-stack decisions locked; **§ 4 data models filled (review pass applied)**; DR groups still to be filled
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

This section defines the core data shapes that flow through the system. They are the contract between back-end stages, the front-end, the audit bundle, and the deliverable. **Pydantic is the single source of truth** (§ 3.6); JSON Schema and TypeScript types are generated from these classes.

The shapes are organized in three layers:

1. **Domain models** — `Rubric`, `EvidenceProfile`, `AssessmentFinding`, `ProposedChange`, `Explanation`, `ExplainedRubricFile`. Pipeline-agnostic. They describe *what* was found and *what* changed, not *how*.
2. **Provenance models** — `AuditBundle`, `StageRecord`, `OperationRecord`, `OperationDetails` union, `IterationSnapshot`. Implementation-aware but pipeline-agnostic via a discriminated union over operation kinds.
3. **Shared primitives** — `RubricTarget`, `ConfidenceIndicator`, `QualityCriterion`, `QualityMethod`, ID types.

The model code below is **canonical pseudo-Pydantic** — close to literal Pydantic v2 syntax, trimmed of imports and decorators that add no design content. Forward references within § 4 (e.g. `IterationSnapshot.quality_scores: list[CriterionScore]` referencing the type defined in § 4.9) are valid in actual Pydantic via `from __future__ import annotations`. The implementation lives in `backend/grading_rubric/models/` (§ 3.10).

### 4.1 Conventions

- All identifiers are UUIDs (`uuid.UUID`). Human-readable `slug` fields exist for display only and are never used as references.
- All timestamps are timezone-aware UTC (`datetime`).
- All hashes are lowercase hex SHA-256 of canonical UTF-8 JSON.
- `JsonValue` denotes any JSON-serializable value (`str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]`).
- Type aliases for clarity:

```python
RubricId    = UUID
CriterionId = UUID
LevelId     = UUID
FindingId   = UUID
ChangeId    = UUID
OperationId = UUID
RunId       = UUID
```

### 4.2 Rubric

The rubric is a tree of criteria. Each criterion may have sub-criteria (recursive) and/or levels. Leaves carry actual point allocations; parents aggregate their children. This satisfies SR-IM-02 (criteria, sub-criteria, point allocations, scoring guidance) in a single shape.

```python
class RubricLevel(BaseModel):
    id: LevelId
    slug: str | None = None              # display only
    label: str                           # e.g. "Excellent", "4/4"
    points: float                        # 0 ≤ points ≤ parent criterion points
    descriptor: str                      # qualitative description of this level


class RubricCriterion(BaseModel):
    id: CriterionId
    slug: str | None = None              # display only
    name: str
    description: str
    scoring_guidance: str | None = None
    points: float | None = None          # actual point allocation; required on every criterion that participates in a total (see invariants below)
    weight: float | None = None          # optional normalized display metadata, 0..1; never used in arithmetic
    additive: bool = True                # if False, parent points are not the sum of children (max/avg/etc.)
    levels: list[RubricLevel] = []       # may be empty for parent (grouping) nodes
    sub_criteria: list["RubricCriterion"] = []


class Rubric(BaseModel):
    id: RubricId
    schema_version: str
    title: str
    exam_question_ref: str | None = None
    total_points: float
    criteria: list[RubricCriterion]
    metadata: dict[str, JsonValue] = {}
```

**Invariants enforced by `Rubric.model_validator`:**

- Every criterion that participates in a total has `points` set. Concretely: every leaf criterion has `points` set, and every parent criterion has `points` set. `points` may be `None` only on a hypothetical purely-grouping node that no current rubric shape produces — the validator therefore requires `points` on every criterion in `criteria` and every node reached through `sub_criteria`.
- Additive parent (`additive=True`): `points == sum(child.points for child in sub_criteria)`. Non-additive parents (`additive=False`) are an explicit escape hatch for max / average / other aggregations and the validator does not enforce a sum on them; the parent's `points` is taken as authoritative.
- For each leaf criterion, every `level.points` satisfies `0 ≤ level.points ≤ criterion.points`.
- `rubric.total_points == sum(root_criterion.points for root_criterion in criteria)`.
- All UUIDs unique within the rubric.

**Rationale.** A single recursive `RubricCriterion` covers flat rubrics, two-level criterion / sub-criterion rubrics, and arbitrarily nested rubrics without a separate `RubricSubcriterion` class. The `additive` flag makes non-additive aggregation explicit, so the validator never silently ignores a sum mismatch. `weight` is preserved as display-only metadata because some real rubrics expose it, but it never participates in arithmetic — `points` is the only authoritative allocation.

### 4.3 RubricTarget

A `RubricTarget` addresses a node or field inside a rubric. It is used by `AssessmentFinding` (where the issue is) and by the `REPLACE_FIELD` and `UPDATE_POINTS` variants of `ProposedChange`. Structural changes (add / remove / reorder) do not use `RubricTarget`; they carry their own payloads (§ 4.6).

```python
class RubricFieldName(StrEnum):
    NAME             = "name"
    DESCRIPTION      = "description"
    SCORING_GUIDANCE = "scoring_guidance"
    POINTS           = "points"
    WEIGHT           = "weight"
    LEVEL_LABEL      = "level.label"
    LEVEL_DESCRIPTOR = "level.descriptor"
    LEVEL_POINTS     = "level.points"


class RubricTarget(BaseModel):
    criterion_path: list[CriterionId]    # root → leaf, never empty
    level_id: LevelId | None = None      # required when field starts with "level."
    field: RubricFieldName
```

**Invariants:**

- `criterion_path` is non-empty.
- `level_id` is set if and only if `field ∈ {LEVEL_LABEL, LEVEL_DESCRIPTOR, LEVEL_POINTS}`.
- All referenced IDs exist in the bound rubric.

**Rationale.** Path-by-UUID is rename-stable. `field` is a closed enum so the front-end can render targeted UI without string parsing. There is no `"structure"` field value: structural operations are different shapes (§ 4.6), not different targets.

### 4.4 EvidenceProfile

Captures, per input artefact, what was actually available to the run. Used to make limitations honest in the deliverable and to support SR-IN-09.

```python
class EvidenceProfile(BaseModel):
    starting_rubric_present: bool
    exam_question_present: bool
    teaching_material_present: bool
    teaching_material_count: int = 0     # number of teaching-material documents
    student_copies_present: bool
    student_copies_count: int = 0
    student_copies_pages_total: int = 0

    starting_rubric_hash: str | None = None
    exam_question_hash: str | None = None
    teaching_material_hashes: list[str] = []
    student_copies_hashes: list[str] = []

    notes: list[str] = []                # e.g. "OCR confidence below threshold on copy 3"
```

**Rationale.** Booleans are explicit so downstream consumers (Explanation narrative, scoring, audit) can branch without re-reading inputs. Hashes give per-input provenance without exposing content. The four input categories — starting rubric, exam question, teaching material, student copies — match the four UR-01..UR-04 inputs and the four SR-IN-01..SR-IN-04 ingestion requirements. There is no `answer_key` field because no requirement calls for one; the teaching material is the grounding source per UR-02 and SR-AS-04.

### 4.5 AssessmentFinding

A single observation about a rubric node, tagged with **exactly one** quality criterion (SR-AS-07). The `measured_against_rubric_id` and `iteration` fields make findings staleness-aware so the re-measurement loop (SR-AS-09) can invalidate findings whose rubric snapshot has changed underneath them.

```python
class QualityCriterion(StrEnum):
    AMBIGUITY            = "ambiguity"
    APPLICABILITY        = "applicability"
    DISCRIMINATION_POWER = "discrimination_power"


class Severity(StrEnum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class ConfidenceLevel(StrEnum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class ConfidenceIndicator(BaseModel):
    score: float                         # 0.0–1.0
    level: ConfidenceLevel               # derived from score by fixed thresholds (below)
    rationale: str                       # why this confidence, grounded in evidence
```

**Confidence-level thresholds (locked):**

- `score < 0.40` → `LOW`
- `0.40 ≤ score < 0.75` → `MEDIUM`
- `score ≥ 0.75` → `HIGH`

`level` is derived from `score` and validated for consistency on construction. It exists as a field rather than as a property so the JSON Schema (§ 3.6) exposes it explicitly to the front-end.

```python
class QualityMethod(StrEnum):
    LLM_PANEL_AGREEMENT           = "llm_panel_agreement"            # multi-rater Krippendorff's α
    PAIRWISE_CONSISTENCY          = "pairwise_consistency"           # head-to-head ranking vs absolute scores
    SYNTHETIC_COVERAGE            = "synthetic_coverage"             # coverage over candidate-response space
    SCORE_DISTRIBUTION_SEPARATION = "score_distribution_separation"  # separation across difficulty tiers


class Measurement(BaseModel):
    method: QualityMethod
    samples: int                         # number of independent measurements aggregated
    agreement: float | None = None       # interpretation depends on method


class AssessmentFinding(BaseModel):
    id: FindingId
    criterion: QualityCriterion          # exactly one (SR-AS-07)
    severity: Severity
    target: RubricTarget | None          # None for rubric-wide findings and absence findings
    observation: str                     # short statement of the issue
    evidence: str                        # what in the inputs supports the observation
    measurement: Measurement
    confidence: ConfidenceIndicator
    measured_against_rubric_id: RubricId # which rubric snapshot was measured (SR-AS-09)
    iteration: int = 0                   # 0 for single-pass runs; 1+ for re-measurement iterations
    source_operations: list[OperationId] = []   # links to audit operations (§ 4.8)
    linked_finding_ids: list[FindingId] = []    # for the SR-AS-10 dual-signal pattern (see below)
```

**Optional `target`.** Not every finding addresses a specific node. Three concrete cases require `target = None`:

- **Absence findings** (SR-AS-02 *Applicability*): "no criterion covers a valid response type X" — there is no existing node to point at; the *missing* node is the finding.
- **Rubric-wide findings** (SR-AS-03 *Discrimination Power*): "the rubric's overall scoring distribution shows no separation across difficulty tiers" — the subject is the rubric as a whole.
- **Total-scale findings**: "the rubric's total points are inconsistent with its declared maximum" — again, the rubric as a whole.

When `target` is set, all `RubricTarget` invariants from § 4.3 apply unchanged. When `target` is `None`, the finding is interpreted as scoped to the rubric identified by `measured_against_rubric_id`.

**Linked findings.** SR-AS-10 calls for two findings when a pairwise inconsistency traces to ambiguous criterion wording: a discrimination-power finding and a separately-tagged ambiguity finding over the same evidence. **Each finding still carries exactly one `criterion`** (preserving SR-AS-07). The relationship between them is expressed by `linked_finding_ids` (symmetric: each links to the other), not by overloading `criterion`.

**Staleness.** A finding is stale when its `measured_against_rubric_id` no longer equals the rubric the teacher is currently looking at. The front-end can render staleness visually; the engine prunes stale findings before re-measurement. For non-loop runs, `iteration` is `0` and `measured_against_rubric_id` is the starting rubric's id (or the from-scratch placeholder).

### 4.6 ProposedChange

A discriminated union over operation kinds. The discriminator is the `operation` literal field. The common envelope is shared via a base class.

```python
class ApplicationStatus(StrEnum):
    APPLIED      = "applied"             # change is reflected in improved_rubric
    NOT_APPLIED  = "not_applied"         # change is proposed but not in improved_rubric


class TeacherDecision(StrEnum):
    PENDING  = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class _ProposedChangeBase(BaseModel):
    id: ChangeId
    primary_criterion: QualityCriterion           # display bucket
    source_findings: list[FindingId]              # may span criteria; primary_criterion is the bucket
    rationale: str
    confidence: ConfidenceIndicator
    application_status: ApplicationStatus
    teacher_decision: TeacherDecision | None = None   # None when no review yet


class ReplaceFieldChange(_ProposedChangeBase):
    operation: Literal["REPLACE_FIELD"] = "REPLACE_FIELD"
    target: RubricTarget
    before: JsonValue | None             # None when no starting rubric
    after:  JsonValue


class UpdatePointsChange(_ProposedChangeBase):
    operation: Literal["UPDATE_POINTS"] = "UPDATE_POINTS"
    target: RubricTarget                 # field must be POINTS or LEVEL_POINTS
    before: float | None
    after:  float


class NodeKind(StrEnum):
    CRITERION = "criterion"
    LEVEL     = "level"


class AddNodeChange(_ProposedChangeBase):
    operation: Literal["ADD_NODE"] = "ADD_NODE"
    parent_path: list[CriterionId]       # empty list = root
    insert_index: int                    # 0-based position among siblings
    node_kind: NodeKind
    node: RubricCriterion | RubricLevel  # full snapshot of the new node


class RemoveNodeChange(_ProposedChangeBase):
    operation: Literal["REMOVE_NODE"] = "REMOVE_NODE"
    criterion_path: list[CriterionId]    # root → criterion (the criterion itself, or the criterion that owns the level)
    level_id: LevelId | None = None      # required when node_kind == LEVEL; None when node_kind == CRITERION
    node_kind: NodeKind
    removed_snapshot: RubricCriterion | RubricLevel   # for reversibility and audit


class ReorderNodesChange(_ProposedChangeBase):
    operation: Literal["REORDER_NODES"] = "REORDER_NODES"
    parent_path: list[CriterionId]
    node_kind: NodeKind
    before_order: list[UUID]
    after_order:  list[UUID]             # permutation of before_order


ProposedChange = Annotated[
    ReplaceFieldChange | UpdatePointsChange |
    AddNodeChange | RemoveNodeChange | ReorderNodesChange,
    Field(discriminator="operation"),
]
```

**Rationale.** A discriminated union covers point edits, structural edits, and from-scratch generation (a sequence of `ADD_NODE` operations on an empty starting rubric). Each variant carries exactly the payload it needs, so validators are tight and the front-end can render operation-specific UI without ad-hoc casts. `primary_criterion` is the single display bucket; multi-criterion sourcing remains visible through `source_findings` (which carry their own per-finding `criterion`) and may be surfaced narratively via `CrossCuttingGroup` (§ 4.7). The split between `application_status` (system) and `teacher_decision` (human) keeps SR-OUT-05 and SR-IM-01 cleanly separable. `RemoveNodeChange` splits its address into `criterion_path` + `level_id` so that removing a level under a criterion is unambiguous; for a criterion-level removal, `level_id` is `None` and `criterion_path` ends at the criterion to remove.

### 4.7 Explanation

The teacher-facing structured rationale. Organized by quality criterion to satisfy SR-OUT-03 *structurally*, not just by convention. Scores live in `ExplainedRubricFile.quality_scores` (§ 4.9) and are referenced by criterion, never duplicated here.

```python
class CriterionSection(BaseModel):
    """
    A criterion-organized section of the explanation.

    Canonical representation of SR-IM-06 ("no improvement warranted") for a single
    criterion: a CriterionSection with empty finding_refs and empty change_refs and
    a narrative explaining why no issues were found is valid. The Explanation
    invariant requires one CriterionSection per QualityCriterion regardless of
    whether any findings were produced for that criterion.
    """
    criterion: QualityCriterion
    finding_refs: list[FindingId] = []
    change_refs: list[ChangeId] = []
    unaddressed_finding_refs: list[FindingId] = []
    narrative: str                       # required even when refs are empty


class CrossCuttingGroup(BaseModel):
    title: str
    narrative: str
    finding_refs: list[FindingId]        # findings already tagged in by_criterion
    change_refs: list[ChangeId]          # changes already listed in by_criterion


class Explanation(BaseModel):
    summary: str                         # 1–2 paragraphs, teacher-readable
    by_criterion: dict[QualityCriterion, CriterionSection]
    cross_cutting: list[CrossCuttingGroup] = []
```

**Invariants:**

- `by_criterion` has exactly one entry per `QualityCriterion` value (three sections, always).
- Every `finding_ref` and `change_ref` in any `CrossCuttingGroup` must also appear in exactly one `CriterionSection`. `cross_cutting` is a *grouping over already-tagged items*, never a fourth category and never a home for untagged findings.
- When all `by_criterion[*]` sections have empty `finding_refs` and empty `change_refs`, `Explanation.summary` MUST state explicitly that no improvements were warranted (SR-IM-06).

**Rationale.** `by_criterion` makes the three-criterion structure a hard contract instead of a convention. `cross_cutting` preserves SR-AS-07's single-criterion-per-finding rule because every referenced item is *already* tagged under exactly one criterion. Narrative fields are written for a teacher audience: no method jargon, no model names, no token counts.

### 4.8 Provenance: AuditBundle

The provenance layer is generic over operation kinds. LLM calls are one variant among several; OCR, deterministic functions, ML inference, tool calls, human decisions, and agent steps are first-class citizens. This makes § 2.3's "LLMs as one possible measurement instrument" structurally true in § 4 rather than only rhetorical.

```python
class StageStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED  = "failed"


class OperationStatus(StrEnum):
    SUCCESS = "success"
    FAILED  = "failed"
    SKIPPED = "skipped"


class StageRecord(BaseModel):
    stage_id: str                        # "ingest","ocr","assess","propose","score","render"
    started_at: datetime
    ended_at: datetime
    status: StageStatus
    operation_ids: list[OperationId] = []   # operations executed inside this stage
```

#### Operation details — discriminated union

```python
class LlmCallDetails(BaseModel):
    kind: Literal["llm_call"] = "llm_call"
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    schema_id: str
    schema_hash: str
    model: str
    temperature: float
    samples: int
    tokens_in: int
    tokens_out: int
    raw_responses: list[JsonValue]       # may contain transcribed student text; see privacy note


class OcrCallDetails(BaseModel):
    kind: Literal["ocr_call"] = "ocr_call"
    backend: str                         # "claude-multimodal","tesseract", ...
    pages: int
    underlying_operation_id: OperationId | None = None  # set when OCR runs through the LLM gateway


class MlInferenceDetails(BaseModel):
    kind: Literal["ml_inference"] = "ml_inference"
    model_id: str
    model_version: str
    confidence: float | None = None


class ToolCallDetails(BaseModel):
    kind: Literal["tool_call"] = "tool_call"
    tool_name: str
    arguments_digest: str


class HumanDecisionDetails(BaseModel):
    kind: Literal["human_decision"] = "human_decision"
    actor: str                           # "teacher","reviewer"
    prompt_shown: str
    decision: str


class AgentStepDetails(BaseModel):
    kind: Literal["agent_step"] = "agent_step"
    agent_id: str
    step_index: int
    action: str


class DeterministicDetails(BaseModel):
    kind: Literal["deterministic"] = "deterministic"
    function: str                        # e.g. "parse_pdf","compute_evidence_profile"
    library_version: str | None = None


OperationDetails = Annotated[
    LlmCallDetails | OcrCallDetails | MlInferenceDetails |
    ToolCallDetails | HumanDecisionDetails | AgentStepDetails | DeterministicDetails,
    Field(discriminator="kind"),
]
```

#### OperationRecord, IterationSnapshot, AuditBundle

```python
class ErrorRecord(BaseModel):
    code: str
    message: str
    stage_id: str | None = None
    operation_id: OperationId | None = None


class OperationRecord(BaseModel):
    id: OperationId
    stage_id: str
    started_at: datetime
    ended_at: datetime
    status: OperationStatus              # SUCCESS | FAILED | SKIPPED — no "RETRIED"
    attempt: int = 1                     # 1 for first try, 2+ for retries
    retry_of: OperationId | None = None  # previous OperationRecord this one retries
    inputs_digest: str
    outputs_digest: str | None           # None when status ∈ {FAILED, SKIPPED} or the operation produced no outputs
    details: OperationDetails
    error: ErrorRecord | None = None


class IterationSnapshot(BaseModel):
    iteration: int                       # 0 = starting rubric measurement; 1+ = post-improvement re-measurements
    rubric_id: RubricId
    rubric_snapshot: Rubric              # full snapshot at this iteration
    quality_scores: list["CriterionScore"]    # measurements taken on this snapshot (defined § 4.9)
    finding_ids: list[FindingId]              # findings produced against this snapshot
    applied_change_ids: list[ChangeId] = []   # changes applied to produce the next iteration
    measured_at: datetime


class InputProvenance(BaseModel):
    starting_rubric_path: str | None = None
    exam_question_path: str | None = None
    teaching_material_paths: list[str] = []
    student_copies_paths: list[str] = []
    starting_rubric_hash: str | None = None
    exam_question_hash: str | None = None
    teaching_material_hashes: list[str] = []
    student_copies_hashes: list[str] = []


class AuditBundle(BaseModel):
    run_id: RunId
    schema_version: str
    started_at: datetime
    ended_at: datetime
    status: Literal["success","partial","failed"]
    input_provenance: InputProvenance
    evidence_profile: EvidenceProfile
    stages: list[StageRecord]
    operations: list[OperationRecord]
    findings: list[AssessmentFinding]
    proposed_changes: list[ProposedChange]
    iteration_history: list[IterationSnapshot] = []   # empty for single-pass runs (SR-AS-09)
    output_file_path: str | None = None
    errors: list[ErrorRecord] = []
```

**Rationale.** `OperationRecord.details` is a discriminated union, so a future ML classifier path or a human-only path slots into the same audit shape without schema migration. Each retry is its own `OperationRecord` linked via `retry_of`, so the audit trail shows the full chain instead of collapsing it into a single ambiguous status. `validation_retry_count` from § 3.2 is therefore a *derived view* (count of retried operations following the chain), not a stored counter on `LlmCallDetails`. `iteration_history` is the complete trajectory of the SR-AS-09 re-measurement loop and is empty for single-pass runs.

**Privacy note.** The deliverable (`ExplainedRubricFile`, § 4.9) **never contains raw student copy text**. The audit bundle may contain transcribed student text inside `LlmCallDetails.raw_responses` and inside operations linked from `OcrCallDetails.underlying_operation_id`, because faithful reconstruction of a measurement requires the exact input and output. The audit bundle is a local artefact under `runs/<run_id>/`; sharing it is the teacher's decision. The deliverable and the audit bundle are separate files for exactly this reason.

### 4.9 Deliverable: ExplainedRubricFile

The deliverable is a single JSON file. It is teacher-readable through its narrative fields and reviewer-inspectable through its references and quality scores. SR-OUT-01 mandates this artefact for every successful run; SR-OUT-02 mandates the two-field root structure (improved rubric + explanation); SR-OUT-03 mandates organization by the three quality criteria; SR-OUT-04 mandates schema validation; SR-OUT-05 mandates that teacher decisions are reflected.

```python
class CriterionScore(BaseModel):
    criterion: QualityCriterion
    score: float                         # 0.0–1.0; the measurement against one rubric snapshot
    confidence: ConfidenceIndicator
    method: QualityMethod                # closed enum, shared with Measurement.method


class ExplainedRubricFile(BaseModel):
    schema_version: str
    generated_at: datetime
    run_id: RunId

    starting_rubric: Rubric | None       # None for from-scratch generation
    improved_rubric: Rubric

    findings: list[AssessmentFinding]
    proposed_changes: list[ProposedChange]
    explanation: Explanation
    quality_scores: list[CriterionScore]                          # canonical, one per QualityCriterion (improved rubric)
    previous_quality_scores: list[CriterionScore] | None = None   # one per QualityCriterion against starting rubric (SR-AS-09)
    evidence_profile: EvidenceProfile
```

**Invariants:**

- `quality_scores` has exactly one entry per `QualityCriterion` value.
- `previous_quality_scores`, when present, has the same shape (one per `QualityCriterion`).
- `previous_quality_scores` is set whenever `starting_rubric is not None` and at least one re-measurement iteration ran; it is `None` for from-scratch generation and for single-pass runs that never re-measured.
- Every finding referenced from `explanation` exists in `findings`.
- Every change referenced from `explanation` exists in `proposed_changes`.
- Every change with `application_status=APPLIED` is reflected in `improved_rubric`.

**Rationale.** One file serves both audiences. `explanation` carries the teacher narrative; `findings`, `proposed_changes`, `quality_scores`, and `evidence_profile` make the file self-auditing. `CriterionScore` carries a single `score` — the measurement of *one* rubric snapshot — so there is exactly one place in the file where any given (criterion, snapshot) pair appears. The before/after comparison required by SR-AS-09 is expressed at the file level by the `quality_scores` / `previous_quality_scores` pair, not by per-score `before`/`delta` fields that would duplicate the same data. `delta` is then a presentation-layer computation (`quality_scores[i].score - previous_quality_scores[i].score`), not a stored field that can drift. The full iteration trajectory still lives in the audit bundle (`AuditBundle.iteration_history`); the deliverable surfaces only the two endpoints needed by the front-end.

### 4.10 Schema versioning

Each top-level shape (`Rubric`, `AuditBundle`, `ExplainedRubricFile`) carries a `schema_version` string. Schema versions follow semver and evolve **independently of the application version** (§ 3.6). The `make schemas` target writes versioned JSON Schema files to `schemas/` for the front-end codegen step. A change to any field shape bumps the schema's MINOR version; an incompatible change bumps MAJOR.

### 4.11 Trace summary — data models to System Requirements

| Data model | Backs SRs |
|---|---|
| `Rubric` (recursive criteria + levels + points + scoring guidance) | SR-IM-01, SR-IM-02 |
| `RubricTarget` (path-by-UUID + closed field enum) | SR-IM-03, SR-IM-05 |
| `EvidenceProfile` | SR-IN-09, SR-AS-04, SR-AS-05, SR-AS-06, SR-AS-08 |
| `AssessmentFinding` (single criterion + linked findings + staleness fields) | SR-AS-01, SR-AS-02, SR-AS-03, SR-AS-07, SR-AS-08, SR-AS-09, SR-AS-10 |
| `Measurement` + `QualityMethod` enum | SR-AS-08, SR-AS-09, SR-AS-10 |
| `ProposedChange` (discriminated union, application_status + teacher_decision split) | SR-IM-01, SR-IM-03, SR-IM-04, SR-IM-05, SR-IM-06, SR-OUT-05 |
| `Explanation` (by_criterion + cross_cutting + SR-IM-06 empty case) | SR-OUT-03, SR-IM-06 |
| `AuditBundle` (generic operations + iteration_history) | SR-OBS-01, SR-OBS-02, SR-AS-09 |
| `ExplainedRubricFile` (with previous_quality_scores) | SR-OUT-01, SR-OUT-02, SR-OUT-03, SR-OUT-04, SR-OUT-05, SR-AS-09 |

The full SR → DR traceability table will be populated in § 6 as the DR groups in § 5 are filled.

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

The caching question is already settled by decision § 3.8: **the application has no application-level cache**. DR-PER therefore does not introduce one. What this group does specify is (a) how concurrent processing of multiple student copies and multi-sample LLM calls is handled while keeping each pipeline stage hermetic, (b) which work units are parallelized and which run sequentially, and (c) the back-pressure and timeout policy that protects the run from a single slow upstream call.

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
| 0.12.1 | 2026-04-11 | Wiktor Lisowski | § 4 review pass after a second-round review of the v0.12.0 fill. Seven fixes, no new shapes introduced. **(1) EvidenceProfile + InputProvenance — teaching material instead of answer key.** The v0.12.0 fill carried `answer_key_present` / `answer_key_hash` as a slip; no SR calls for an answer key. Replaced with `teaching_material_present` / `teaching_material_count` / `teaching_material_hashes` (and the matching `teaching_material_paths` / `teaching_material_hashes` on `InputProvenance`), so the four EvidenceProfile categories now match UR-01..UR-04 and SR-IN-01..SR-IN-04 one-for-one. **(2) AssessmentFinding.target is now `RubricTarget \| None`.** SR-AS-02 *Applicability* findings of the form "no criterion covers a valid response type X" are absence findings — the missing node is the finding — and have no existing target to point at. SR-AS-03 *Discrimination Power* findings about overall scoring distribution are rubric-wide. The previous required `target` could not represent either; the new field is `None` for these cases and behaves exactly as before when set. Added an explicit *Optional `target`* paragraph. **(3) `RemoveNodeChange` now addresses levels unambiguously.** The previous `node_path: list[CriterionId]` could not identify *which* level under a criterion to remove. Split into `criterion_path: list[CriterionId]` plus `level_id: LevelId \| None` (required when `node_kind == LEVEL`, `None` otherwise). Rationale paragraph updated. **(4) Removed before/after duplication on `CriterionScore`.** v0.12.0 carried `score_after`, `score_before`, and `delta` on `CriterionScore` *and* `previous_quality_scores: list[CriterionScore]` on `ExplainedRubricFile` — two encodings of the same data, a drift surface. Collapsed to a single `score: float` per `CriterionScore`; the before/after pair is expressed at the file level by `quality_scores` + `previous_quality_scores`; `delta` is computed by the front-end at presentation time. Invariants updated to require `previous_quality_scores` whenever a starting rubric existed and re-measurement ran. **(5) Tightened `Rubric.points` invariants for parents.** v0.12.0 said "leaf has `points` set" but left parents underspecified, conflicting with `total_points == sum(root.points)`. The validator now requires `points` on every criterion that participates in a total (which is every criterion in current rubric shapes); the additive sum invariant is unchanged; non-additive parents take their declared `points` as authoritative. **(6) DR-PER placeholder no longer contradicts § 3.8.** § 5.9 used to say "likely a content-hashed cache borrowed from patterns proven in adjacent repositories", which directly contradicts the locked § 3.8 *no application-level cache* decision. Rewritten to say DR-PER does not introduce a cache and instead specifies concurrency, parallelism boundaries, and back-pressure / timeout policy. **(7) `OperationRecord.outputs_digest` is now `str \| None`.** Failed and skipped operations may produce no outputs; the previous required `str` would have forced sentinel values. Comment notes the `None` is permitted for `FAILED` / `SKIPPED` status or for operations that produced no outputs. No traceability impact — § 4.11 trace summary is unchanged. |
| 0.12.0 | 2026-04-11 | Wiktor Lisowski | Filled § 4 *Data models* end-to-end. Three layers documented: domain models (`Rubric`, `EvidenceProfile`, `AssessmentFinding`, `ProposedChange`, `Explanation`, `ExplainedRubricFile`), provenance models (`AuditBundle`, `StageRecord`, `OperationRecord`, `OperationDetails` discriminated union, `IterationSnapshot`), and shared primitives (`RubricTarget`, `ConfidenceIndicator`, `QualityCriterion`, `QualityMethod`, ID type aliases). Key design choices. **Rubric**: recursive `RubricCriterion` with `sub_criteria` covers SR-IM-02 in a single shape; locked `points` / `weight` invariants (`points` is the only authoritative allocation, `weight` is display-only metadata) and an explicit `additive` flag for non-additive parent aggregation. **RubricTarget**: path-of-UUIDs with a closed `RubricFieldName` enum — rename-stable, no string parsing, no overloaded `"structure"` value. **AssessmentFinding**: single `criterion` (preserving SR-AS-07), staleness-aware via `measured_against_rubric_id` + `iteration` (SR-AS-09), SR-AS-10 dual signal expressed by `linked_finding_ids` between two single-criterion findings. **ConfidenceIndicator**: structured as `score` + `level` + `rationale` with locked thresholds; replaces the bare-float regression flagged in review. **Measurement** + **`QualityMethod`** closed enum (`LLM_PANEL_AGREEMENT`, `PAIRWISE_CONSISTENCY`, `SYNTHETIC_COVERAGE`, `SCORE_DISTRIBUTION_SEPARATION`) shared with `CriterionScore.method` to prevent drift between assessment engine and explanation generator. **ProposedChange**: discriminated union over `REPLACE_FIELD` / `UPDATE_POINTS` / `ADD_NODE` / `REMOVE_NODE` / `REORDER_NODES` covering both improvement and from-scratch generation; `primary_criterion` as the display bucket; `application_status` (system) and `teacher_decision` (human) split. **Explanation**: `by_criterion` mandatory three-section structure makes SR-OUT-03 a hard contract; `CrossCuttingGroup` is a grouping over already-tagged items, never a fourth category; SR-IM-06 empty case is the canonical shape of an empty `CriterionSection` with a narrative. **AuditBundle**: provenance generic over `OperationDetails` (`llm_call` / `ocr_call` / `ml_inference` / `tool_call` / `human_decision` / `agent_step` / `deterministic`) so the audit shape supports any pipeline kind; retries are separate `OperationRecord`s linked by `retry_of` (no `RETRIED` final status); `iteration_history: list[IterationSnapshot]` carries the full SR-AS-09 re-measurement trajectory and is empty for single-pass runs. **ExplainedRubricFile**: deliverable stays single-file and self-contained; gains `previous_quality_scores` so the front-end can render before/after evidence without needing the audit bundle. **Privacy claim recast**: deliverable never contains raw student text; audit bundle may contain transcribed text in `LlmCallDetails.raw_responses` because faithful reconstruction requires it; deliverable and audit bundle are separate files for exactly this reason. § 4.11 *Trace summary* maps each data model to the SRs it backs (cross-checked against `requirements.md` v0.5.0). § 5 DR groups are next; § 6 traceability will be regenerated as DRs are added. |
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
