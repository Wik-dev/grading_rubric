# Grading Rubric Studio — Design

**Version**: 1.1.0
**Date**: 2026-04-15
**Status**: **Aligned with implemented codebase.** 116 Design Requirements across 12 groups, all traced to System Requirements (§ 6). Implementation complete; tests on the right arm of the V-shape.
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
- Deployment, packaging, orchestration — including how the four-layer split (L1 Python package + CLI / L2 Docker / L3 Validance integration / L4 SPA) lets the same hermetic L1 stages run as direct CLI invocations on Path A or as Validance workflow tasks on Path B.

**Out of scope**

- Anything that belongs at the SR layer (what the system *does*) or at the UR layer (what the *user* must be able to do).
- Multi-teacher collaboration, persistent storage across sessions, mobile UI (out of scope of the application itself per [`requirements.md`](requirements.md) § 1.2).

### 1.3 Reference documents

| Document | Notes |
|---|---|
| [`requirements.md`](requirements.md) | UN, UR, SR, glossary, and traceability. Every DR here traces to at least one SR there. |

### 1.4 Design glossary

This section anchors terms that appear in the design layer but not in [`requirements.md`](requirements.md) § 2. The user-facing glossary in `requirements.md` remains the canonical source for shared vocabulary; entries here are strictly design-internal.

| Term | Definition |
|---|---|
| **Sample (LLM)** | One independent draw from the LLM for a given call. The same prompt with the same inputs and the same model can be drawn multiple times; because the model is stochastic, the resulting outputs differ. The system uses multiple samples per call where the *spread across samples* is itself the measurement — for example, when measuring how reliably independent graders agree on the interpretation of a rubric phrase. Tasks that need only a single answer (extraction, classification) draw one sample; tasks that drive an *assessment finding* and a *confidence indicator* draw several. |

---

## 2. Architectural overview

This section frames the system at a level above any specific technology choice. It establishes the modules and how they interact, and it states the four guiding principles that shape every choice made later in the document.

### 2.1 System diagram

The system is **four layers**. L1 is a hermetic Python package with a CLI per pipeline stage and zero Validance imports. L2 is a small set of Docker images that bake L1 + the CLI as their entrypoint. L3 is a Validance integration directory that defines a workflow over the L2 images and provides a registration script — the only place where `validance-sdk` is imported. L4 is a custom SPA (Vite + React + shadcn + Tailwind, per § 3.3) whose backend is **Validance's REST API**, not a custom HTTP server in the deliverable.

The reviewer has **two demo paths**, both supported by the same code:

```
                                +---------------------------+
                                |          Teacher          |
                                +-------------+-------------+
                                              |
                  +---------------------------+---------------------------+
                  |                                                       |
                  v                                                       v
   +---------------------------+                       +----------------------------------+
   |  Path A: CLI direct       |                       |  Path B: Validance + SPA         |
   |  (single-stage inspection)|                       |  (full V-model experience)       |
   +-------------+-------------+                       +-----------------+----------------+
                 |                                                       |
                 |                                          +------------v-----------+
                 |                                          |   L4: custom SPA        |
                 |                                          |   (frontend/, separate  |
                 |                                          |   deployable, talks     |
                 |                                          |   only HTTPS to L3 host)|
                 |                                          +------------+------------+
                 |                                                       |
                 |                                                       v
                 |                                          +------------------------+
                 |                                          |  Validance REST API     |
                 |                                          |  (hosted on dev VM —    |
                 |                                          |  the canonical demo     |
                 |                                          |  target)                |
                 |                                          +------------+------------+
                 |                                                       |
                 |                                          +------------v------------+
                 |                                          |  L3: validance/         |
                 |                                          |  workflow definitions + |
                 |                                          |  registration script +  |
                 |                                          |  proposal-payload       |
                 |                                          |  mapping + harvester    |
                 |                                          |  (sole validance-sdk    |
                 |                                          |  import site)           |
                 |                                          +------------+------------+
                 |                                                       |
                 v                                                       v
       +---------------------+                              +---------------------+
       |  L2: Docker image   |                              |  L2: Docker image   |
       |  (`docker run ...`) |                              |  (run by Validance) |
       +----------+----------+                              +----------+----------+
                  |                                                    |
                  v                                                    v
       +-------------------------------------------------------------------+
       |   L1: grading_rubric Python package                                |
       |   sub-packages: models, parsers, assess, improve, output,          |
       |                 scorer, gateway, audit, orchestrator, cli, config  |
       |   one CLI subcommand per pipeline stage                            |
       |   ZERO Validance imports                                           |
       +------------------------+------------------------------------------+
                                |
                                v
                  Explained rubric file (JSON)
                  + (Path B only) audit chain
                  populated by Validance and
                  surfaced through the SPA
```

**Path A (CLI direct, single-stage inspection)** — `docker run <image> grading-rubric-cli <stage> --input ... --output ...`. One stage at a time, single-stage inspection. No audit chain, no approval gate, no SPA.

**Path B (Validance + SPA, full V-model experience)** — the SPA calls Validance's REST API; Validance runs the pre-registered workflow against L2 images; the teacher reviews proposed changes through the SPA via Validance's `ApprovalGate`; the audit chain is populated by Validance and harvested into the deliverable's provenance section.

**Pipeline data flow** (the six L1 stages, in order):

```
  exam.pdf + rubric.pdf + copies/ + teaching.pdf
                    │
              ┌─────▼─────┐
              │   ingest   │  hash inputs, build provenance
              └─────┬──────┘
              ┌─────▼──────────┐
              │  parse-inputs  │  extract text, structure rubric (LLM)
              └─────┬──────────┘
              ┌─────▼─────┐
              │   assess   │  synthesize → grade (4 personas × N responses)
              │            │  → measure ambiguity / applicability / discrimination
              └─────┬──────┘
              ┌─────▼──────┐
              │   propose  │  LLM planner → ground → apply REPLACE_FIELD
              └─────┬──────┘
            [approval gate]   (Path B only: teacher accept/reject)
              ┌─────▼─────┐
              │    score   │  re-grade improved rubric (same response set)
              └─────┬──────┘
              ┌─────▼─────┐
              │   render   │  assemble ExplainedRubricFile
              └─────┬──────┘
                    ▼
          final_explained_rubric.json
```

**Key cross-layer rules**:

- **L1 has zero Validance imports.** Verifiable by `grep`. The hermetic-task claim of § 2.2 holds literally.
- **L3 is the only place `validance-sdk` is imported.** Validance kernel source is **never** bundled (cross-repo IP boundary — public SDK only).
- **The deliverable does not contain a custom FastAPI server.** The SPA's backend is Validance's REST API.
- **Another orchestrator could wrap L1 by writing its own integration directory analogous to L3.** The cross-cutting concerns (audit chain, retries, approvals, UI backend) become that orchestrator's responsibility, not L1's.

The diagram is module-level. Concrete package layout and dependency rules are the subject of § 5.1 *DR-ARC*. The contract object schemas are § 4. The Validance integration content (workflow definitions, registration script, harvester adapter) is the subject of § 5.12 *DR-INT*.

### 2.2 Hermetic-task philosophy

Each pipeline stage in L1 (`grading_rubric/`) is a **hermetic task**: structured inputs, structured outputs, no global state, no hidden I/O. Three execution surfaces share one CLI definition:

1. **Direct CLI invocation** — `grading-rubric-cli <stage> --input ... --output ...`. Path A: single-stage inspection.
2. **In-process stage chain** — `grading-rubric-cli run-pipeline ...`. Used by tests and local iteration; **not** the production orchestrator.
3. **Validance workflow** — L3 defines a workflow invoking the same CLI commands inside L2 Docker images. Path B: canonical demo target.

Every stage is independently testable, every run replayable. Cross-cutting concerns (audit chain, approvals, retries, provenance, SPA backend) are delegated to the orchestrator — Validance on Path B.

### 2.3 LLMs as measurement instruments

Every LLM interaction is framed as a **measurement task**, not an oracle query:

- **Structured prompt with a defined purpose** — one task per prompt, identifiers logged in the audit bundle.
- **Structured output validated against a schema** — rejected and retried on validation failure (§ 5.2 *DR-LLM*).
- **Multiple samples where reliability matters** — the grader simulation draws samples across personas and reports both central tendency and spread.
- **Classical statistics where strictly better** — deterministic scoring formulas, statistical aggregation of simulation results. The LLM is used where its semantic flexibility is the right tool.

### 2.4 The system is data-aware

The application adapts to the evidence available. A teacher with only the exam question gets a result; a teacher with the full corpus, a polished rubric, and a hundred copies gets a much more confident one. The *evidence profile* (recorded per SR-IN-09) drives which assessment paths fire, which evidence is synthetic, the confidence indicator on every finding, and the warnings shown in the UI. Quantitative rules for confidence are specified in § 5.4 *DR-AS*.

### 2.5 Human in the loop

The application proposes; the teacher decides. Three design constraints follow:

- **Every proposed change carries a rationale** (SR-IM-03, SR-UI-08). No silent edits.
- **Per-change accept/reject via Validance's `ApprovalGate`** (UR-07 → SR-UI-09, SR-OUT-05). On Path B, `propose` emits `ProposedChange` instances; the L3 integration maps them to Validance approval payloads; the teacher accepts or rejects each through the SPA. Path A auto-applies all proposed changes.
- **Re-measurement is teacher-gated** (UR-08 → SR-AS-09, SR-UI-10). The system never auto-converges; `Settings.max_iterations` (default `3`) is a safety bound, not a counter the system runs to.

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
| 10 | Deployment topology, packaging | **decided** (revised v0.14.0) | Four-layer deliverable: **L1** Python package `grading_rubric` installable via `pyproject.toml` with one CLI subcommand per pipeline stage (`grading-rubric-cli <stage> ...`); **L2** Docker images baking L1 + the CLI as their entrypoint; **L3** `validance/` integration directory containing workflow definitions, registration script, proposal-payload mapping, and audit-chain harvester; **L4** `frontend/` custom SPA build (Vite + React + shadcn + Tailwind) talking to Validance's REST API. **No custom HTTP server in the deliverable.** Top-level `Makefile` is the entry-point surface (`install` / `images` / `register` / `dev` / `build` / `test` / `schemas`). | § 3.10 |
| 11 | Orchestration layer | **decided** (revised v0.14.0) | **Validance is the recommended runner and the path through which the deliverable's full V-model experience is delivered.** The hosted Validance instance on the dev VM is the canonical demo target. L1 tasks remain hermetic and CLI-callable directly via Path A (single-stage inspection). On Path B (full experience), Validance owns the audit chain, approval gate, retries, and the SPA backend. Another orchestrator could wrap L1 by writing its own integration directory analogous to L3; that orchestrator's primitives then become responsible for the cross-cutting concerns. | § 3.11 |

Locked architectural commitments: Anthropic as the default LLM provider; pluggable backend; **Validance as the recommended runner of the four-layer architecture** (revised v0.14.0 — see `notes/validance-pivot.md`); the hosted dev-VM Validance instance as the canonical demo target; tasks remain hermetic and CLI-callable directly.

### 3.1 LLM provider, SDK, and default model

**Decision.** Anthropic, accessed via the official `anthropic` Python SDK (≥ 0.40). Default model: **Claude Sonnet 4.6** (`claude-sonnet-4-20250514`). The LLM Gateway supports per-call model override; rubric decomposition uses Opus (`claude-opus-4-6`) for higher-quality structural parsing.

**Why.** Sonnet 4.6 is the workhorse (strong reasoning, moderate cost). The Gateway abstraction makes the provider swappable for EPFL's on-prem path (RCP / local LLMs).

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

**Key choices:** Structured output via Anthropic tool use (no `instructor` / `langchain` / `dspy`). Prompts as markdown files with `str.format` placeholders. Content-hashed prompt identity (SHA-256 over rendered prompt + schema). Pydantic schemas for validation. Retry-once on validation failure. `samples` parameter for reliability measurements. One door to the API — no module other than the Gateway holds an API client.

**Why.** Tool use directly is the shortest path between schema and validated object, with `anthropic` + `pydantic` as the only dependencies. Prompt files let `git diff` show evolution clearly and give the audit bundle stable identity. Retry-once handles transient slips without hiding systematic prompt-schema mismatches. Aggregation stays in the caller because different measurements aggregate differently.

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

The SPA is a **separate deployable** with **no custom Python HTTP server**. It talks directly to Validance's REST API; wire types are generated from L1's Pydantic models via `make schemas` (DR-DAT-03 / DR-DAT-04). The Validance base URL comes from `VITE_VALIDANCE_BASE_URL`.

**Why.** The three-screen UI (side-by-side diff, per-change accept/reject, progress feedback, re-assessment iteration) is a *"custom component with state"* problem, not a *"show a model on a page"* demo — Streamlit/Gradio are the wrong shape. Vite + React + TypeScript is the de-facto modern starter. shadcn/ui vendors accessible Radix primitives with Tailwind styling. TanStack Query handles polling and server-state caching. No custom Python HTTP server needed because Validance's REST API is the backend.

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

**Why.** Downstream stages consume *text plus provenance* and should not branch on file format. `pypdf` is pure-Python and handles most text-layer PDFs; `pdfplumber` is the fallback for layout-heavy PDFs. `markdown-it-py` preserves structural signals (headers, lists). `python-docx` exposes native structure without a PDF round-trip. OCR is decision #5 (§ 3.5).

### 3.5 OCR for handwritten student copies

**Decision.** Handwritten student copies are transcribed by sending each page as a multimodal image input to **Claude Sonnet 4.6** through the same `gateway.measure()` entry point locked in § 3.2. The OCR call is a normal structured-output measurement: the prompt is `prompts/ocr_student_copy.md`, the output schema is a `TranscribedPage` Pydantic model (per-page text, a confidence indicator, and any "unreadable region" markers), and the call is subject to the same prompt/schema hashing, structured audit-event emission, and retry-once validation as every other model call in the system.

The `InputParser` module delegates to a `StudentCopyReader` interface for every file it identifies as a handwritten student copy (either a scanned PDF with no text layer, or a raw image). The primary implementation of that interface is the Claude-backed reader; a dedicated-OCR backend (Azure Document Intelligence, AWS Textract, Google Cloud Vision, or a self-hosted TrOCR model) can replace it without touching any other module. The interface contract is specified in § 5.7 *DR-IO*.

**Why.** Reuses the single Anthropic dependency (no second cloud service, credentials, or rate-limit regime). Claude multimodal is competitive on bounded handwriting tasks, especially with exam-question context. Routing through `gateway.measure()` gives audit completeness and retry-once for free. The `StudentCopyReader` interface is a defensive seam for future on-prem OCR backends.

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

**Why.** Pydantic is already the validation layer (§ 3.2); reusing it for the deliverable's contract means one source of truth, zero drift. Generated JSON Schema lets reviewers inspect the output shape without running Python. Generated TypeScript types and zod validators catch contract drift at front-end build time. Independent schema versioning lets the contract evolve at its own pace.

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
    max_iterations: int = 3              # safety bound on the teacher-gated re-measurement loop (§ 2.5, DR-INT-06)
    prompts_dir: Path = Path("prompts")
    schemas_dir: Path = Path("schemas")
```

`Settings` is instantiated once at process start, immutable (`frozen=True`), and never mutated at runtime. It is strictly value-typed runtime configuration — no directory-layout conventions, no HTTP server settings.

**Why.** Pydantic is already in the stack; reusing it for config means one validation library. Environment variables are the 12-factor default that every orchestrator knows how to feed. `SecretStr` makes accidental leakage structurally difficult. Under an external orchestrator (Validance, Airflow, etc.) the orchestrator's secret store injects the same env vars — the `Settings` class is unaware which layer supplied them.

### 3.8 Caching strategy

**Decision.** **No application-level cache.** Every run performs every call from scratch.

**Why.** Cost is negligible at this scale. Cross-run deduplication is the orchestrator's job at task granularity. Transient-error retries are the SDK's job. Test reproducibility is handled by mocking at the Gateway seam. No cache means hermetic tasks stay hermetic and the audit bundle is the complete truth.

### 3.9 Deterministic execution policy

**Decision.** Bit-identical reproducibility of LLM outputs is explicitly **not claimed** — it is not achievable for hosted inference. What is claimed: (a) *measurement-level stability* and (b) *audit-level reconstructability* (every call's prompt hash, schema hash, model, temperature, and raw response are recorded).

| Call class | Temperature | Samples |
|---|---|---|
| Extraction, classification, single-answer | `0.0` | `1` |
| Grader simulation grading calls | `0.7` (default) | `1` per persona per response |
| Synthetic response generation | `0.4` | `1` |
| Pairwise comparison | `0.2` | `1` |

The model is pinned to a snapshot version (`claude-sonnet-4-20250514`) in `Settings.llm_model_pinned`.

**Why.** Temperature 0 collapses most surface variation for extraction tasks. Grading calls use `0.7` because persona variance is the measurement signal. Synthesis uses `0.4` for controlled diversity; pairwise uses `0.2` for tighter judgments. Audit-level reconstructability is the honest guarantee for an engineering-rigor deliverable.

### 3.10 Deployment topology, packaging

**Decision.** The deliverable is a single repository with **four artefact layers**, each living under a clearly-named top-level directory:

1. **L1 — `grading_rubric/` Python package.** Pure Python, packaged via `pyproject.toml` (PEP 621). Sub-packages: `models`, `parsers`, `assess`, `improve`, `output`, `scorer`, `gateway`, `audit`, `orchestrator`, `cli`, `config`. **Zero Validance imports.** A single console-script entry point is exposed: `grading-rubric-cli`. The CLI offers one subcommand per pipeline stage (`ingest`, `parse-inputs`, `assess`, `propose`, `score`, `render`) and a thin `run-pipeline` subcommand that walks all six stages sequentially in one process for tests and local development — **seven subcommands** total (see DR-ARC-08). Each stage subcommand reads its inputs from CLI-arg paths and writes its outputs to CLI-arg paths; no hidden I/O.
2. **L2 — `docker/` Docker images.** A small set of Docker images (one per execution profile, in the limit just one) that bake L1 + the CLI as their entrypoint. The image knows nothing about Validance — it knows about the CLI. The same image is invoked by `docker run` directly (Path A from § 2.1) and by Validance task definitions (Path B). Image sources live under `docker/<image_name>/`.
3. **L3 — `validance/` Validance integration directory.** The **only** place in the deliverable that imports `validance-sdk`. Contains: workflow definition files (one workflow with the six pipeline stages plus the approval gate, per § 5.12 *DR-INT*); a registration script that uses `validance-sdk` to upload the workflow to the hosted dev-VM Validance instance; the proposal-payload mapping that turns `ProposedChange` instances into Validance approval payloads; the audit-chain harvester adapter that turns Validance audit data into the deliverable's typed § 4.8 shapes. **No FastAPI server. No custom HTTP layer.** The SPA's backend is Validance's REST API directly.
4. **L4 — `frontend/` SPA build.** Custom Vite + React + shadcn + Tailwind SPA (per § 3.3), talking to **Validance's REST API** as its backend. Built with `npm install && npm run build`; the build artefact is a static `frontend/dist/` that any static host can serve (and that Validance itself can serve for the demo path).

A top-level `Makefile` is the entry-point surface a reviewer actually touches:

| Target | What it does |
|---|---|
| `make install` | Installs L1 in editable mode and runs `npm install` in `frontend/`. |
| `make images` | Builds the L2 Docker images via `docker build`. |
| `make register` | Runs the L3 registration script to upload the workflow to the hosted Validance instance (idempotent — re-running updates the workflow definition). |
| `make schemas` | Regenerates `schemas/explained_rubric_file.v*.schema.json` from the Pydantic source of truth (§ 3.6), plus the generated TypeScript types and zod validators consumed by L4. |
| `make build` | Runs the Vite production build; outputs the static SPA to `frontend/dist/`. |
| `make dev` | Starts the Vite dev server with HMR for L4 development. (No FastAPI dev server — there is no FastAPI.) |
| `make test` | Runs `pytest` for L1, the smoke tests for L3 (registration round-trip against a stub), and `vitest` + `playwright test` for L4. |

The repository layout: `grading_rubric/` (L1), `docker/` (L2), `validance/` (L3), `frontend/` (L4), `schemas/`, `Makefile`, `README.md`, `.env.example`, and `pyproject.toml`. DR-ARC (§ 5.1) specifies the internal layout of L1; DR-DEP (§ 5.11) specifies the artefact-by-artefact packaging contract; DR-INT (§ 5.12) specifies the L3 integration content.

**Why.** No custom HTTP server — Validance's REST API is the backend. Per-stage CLI subcommands give single-stage inspection (Path A) and are also what Validance's task definitions invoke (Path B) — one surface, two consumers. Docker images make the L2→L3 boundary clean. `validance/` as a separate top-level directory makes "L1 has zero Validance imports" verifiable by `grep`. Another orchestrator could wrap L1 by writing its own integration directory.

### 3.11 Orchestration layer

**Decision.** L1 embeds **no orchestration layer and no Validance imports**. **Validance is the recommended runner** delivering the full V-model experience (audit chain, ApprovalGate, retry orchestration, provenance, SPA backend). The hosted dev-VM instance is the canonical demo target.

**Why.** The deliverable needs an audit chain, approval flow, retry orchestration, and provenance — all Validance primitives. Re-implementing them inside L1 would inflate task code with infrastructure. Keeping L1 hermetic means the reviewer can inspect any stage without Validance, tests run with no SDK installed, and a different orchestrator could wrap L1 without touching task code.

---

## 4. Data models

This section defines the core data shapes that flow through the system. They are the contract between back-end stages, the front-end, the audit bundle, and the deliverable. **Pydantic is the single source of truth** (§ 3.6); JSON Schema and TypeScript types are generated from these classes.

The shapes are organized in three layers:

1. **Domain models** — `Rubric`, `EvidenceProfile`, `AssessmentFinding`, `ProposedChange`, `Explanation`, `ExplainedRubricFile`. Pipeline-agnostic. They describe *what* was found and *what* changed, not *how*.
2. **Provenance models** — `AuditBundle`, `StageRecord`, `OperationRecord`, `OperationDetails` union, `IterationSnapshot`. Implementation-aware but pipeline-agnostic via a discriminated union over operation kinds.
3. **Shared primitives** — `RubricTarget`, `ConfidenceIndicator`, `QualityCriterion`, `QualityMethod`, ID types.

The model code below is **canonical pseudo-Pydantic** — close to literal Pydantic v2 syntax, trimmed of imports and decorators that add no design content. Forward references within § 4 (e.g. `IterationSnapshot.quality_scores: list[CriterionScore]` referencing the type defined in § 4.9) are valid in actual Pydantic via `from __future__ import annotations`. The implementation lives in `grading_rubric/models/` (§ 3.10), the L1 Python package's `models` sub-package per DR-ARC-01.

### 4.1 Conventions

- All identifiers are UUIDs (`uuid.UUID`). Human-readable `slug` fields exist for display only and are never used as references.
- All timestamps are timezone-aware UTC (`datetime`).
- All hashes are lowercase hex SHA-256 strings, computed per the three-case rule of DR-DAT-06: **(a)** *file* hashes are SHA-256 of the raw file bytes; **(b)** *text content* hashes are SHA-256 of the UTF-8 encoding of the text; **(c)** *structured-object* digests are SHA-256 of the canonical-JSON UTF-8 encoding (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`, ISO-8601 datetime strings, UUIDs as their canonical hyphenated form). Each digest field's docstring states which of the three cases applies.
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

    synthetic_responses_used: bool = False  # set by `assess` per SR-AS-06 when no real student copies are available

    notes: list[str] = []                # e.g. "OCR confidence below threshold on copy 3"
```

**Rationale.** Booleans are explicit so downstream consumers (Explanation narrative, scoring, audit) can branch without re-reading inputs. Hashes give per-input provenance without exposing content. The four input categories — starting rubric, exam question, teaching material, student copies — match the four UR-01..UR-04 inputs and the four SR-IN-01..SR-IN-04 ingestion requirements. There is no `answer_key` field because no requirement calls for one; the teaching material is the grounding source per UR-02 and SR-AS-04. The `synthetic_responses_used` flag is the surface that records SR-AS-06 *fallback to synthetic candidate responses when real student copies are absent*: `ingest` initializes it to `False`; `assess` flips it to `True` if and only if it had to synthesize candidate responses to measure Discrimination Power. The flag is part of the evidence profile (and therefore also rendered in the deliverable's evidence summary) so a teacher reading the explanation can see at a glance whether the run leaned on synthetic evidence.

**InputProvenance shape — files vs inline text.** The earlier `*_path` / `*_hash` parallel-list shape could not represent the SR-IN-05 *pasted-text starting rubric* form: there is no path. The shape above replaces it with a discriminated `InputSource` record (`kind: FILE | INLINE_TEXT`) so that file-uploaded inputs (the path-bearing form) and pasted-text inputs (the inline form) are first-class on the audit-view bundle and on the deliverable's provenance summary. For `kind == FILE` the `path` is the source filename and `hash` is DR-DAT-06 case (a) (raw file bytes); for `kind == INLINE_TEXT` the `path` is `None`, `marker` is a stable human-readable label (e.g. `"<inline:starting_rubric>"`) chosen by `ingest`, and `hash` is DR-DAT-06 case (b) (UTF-8-encoded text content). The `marker` is never derived from the inline content; it identifies *which inline slot* the input filled, not what it said. The four role-tagged fields (`exam_question`, `teaching_material`, `starting_rubric`, `student_copies`) carry the role information that DR-IO-07's `IngestInputs` shape carries on the way in, so the harvested view never has to fall back on filename heuristics to know which input was which.

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
    LLM_PANEL_AGREEMENT           = "llm_panel_agreement"            # multi-rater agreement across grader personas
    PAIRWISE_CONSISTENCY          = "pairwise_consistency"           # head-to-head ranking vs absolute scores
    SYNTHETIC_COVERAGE            = "synthetic_coverage"             # coverage over candidate-response space
    SCORE_DISTRIBUTION_SEPARATION = "score_distribution_separation"  # separation across difficulty tiers
    GRADER_SIMULATION             = "grader_simulation"              # headline scores from grader simulation traces


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

A discriminated union over operation kinds. The discriminator is the `operation` literal field. The common envelope is shared via a base class. **In v1.0, `REPLACE_FIELD` and `ADD_NODE` are produced by the planner and applied by the propose stage.** `REPLACE_FIELD` is the primary operation for modifying existing criteria; `ADD_NODE` is used when discrimination findings call for splitting a criterion into finer sub-criteria. The other three operation types (`UPDATE_POINTS`, `REMOVE_NODE`, `REORDER_NODES`) are defined in the schema for extensibility but are not currently emitted.

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
    source_operations: list[OperationId] = []
    # the operation event ids whose `gateway.measure(...)` call generated, materially
    # transformed, or vetted this change — populated by the propose stage's wrap step
    # (DR-IM-07) only after grounding and application have run; never assigned by the
    # planner. Mirrors AssessmentFinding.source_operations from § 4.5 / DR-AS-10 so
    # the deliverable's join key into the audit chain has the same shape across both
    # stages. Empty list only when no gateway call contributed to the change (which
    # never occurs in the current cluster — every code path that produces a final
    # ProposedChange runs at least one gateway call); the default is `[]` to keep
    # the model additive under § 1 versioning.


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

**Rationale.** A discriminated union so each variant carries exactly the payload it needs. `primary_criterion` is the single display bucket. The split between `application_status` (system) and `teacher_decision` (human) keeps SR-OUT-05 and SR-IM-01 separable. `source_operations` is the audit-join key — populated only by the propose stage's wrap step, never by the planner.

**Invariant**: every `ProposedChange` with `application_status = APPLIED` is reflected in `improved_rubric`. The three-step application pipeline (§ 5.5 DR-IM-07) enforces this. In v1.0, `REPLACE_FIELD` and `ADD_NODE` operations are produced; step 1 (conflict resolution) is relevant when `ADD_NODE` and `REMOVE_NODE` interact but is a no-op for the current mix; step 3 applies field replacements and node insertions.

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

**Pivot framing.** Per the v0.14.0 pivot (§ 2.1, § 3.11), provenance is owned by Validance on the demo path (Path B) and not by L1. The shapes below define a **typed view** that the L3 integration directory's harvester (`validance/harvester.py`, locked by § 5.12 *DR-INT*) populates from Validance's audit chain after a workflow run completes; they are *not* shapes that L1 task code writes to disk. On the CLI direct path (Path A) no `AuditBundle` is produced — single-stage CLI invocations are stage-level inspection, not full-run reconstruction (§ 3.11). The shapes are kept here in § 4 because they are the contract between L3 (which produces them) and the SPA / `ExplainedRubricFile` consumers (which read them); the Pydantic model is the single source of truth (§ 3.6) and JSON Schema flows from it.

The provenance layer is generic over operation kinds. LLM calls are one variant among several; OCR, deterministic functions, ML inference, tool calls, human decisions, and agent steps are first-class citizens. This makes § 2.3's "LLMs as one possible measurement instrument" structurally true in § 4 rather than only rhetorical, and gives the L3 harvester a closed set of `OperationKind` values to map Validance's audit-chain rows into.

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

#### Operation kind — closed enum

```python
class OperationKind(StrEnum):
    LLM_CALL       = "llm_call"
    OCR_CALL       = "ocr_call"
    ML_INFERENCE   = "ml_inference"
    TOOL_CALL      = "tool_call"
    HUMAN_DECISION = "human_decision"
    AGENT_STEP     = "agent_step"
    DETERMINISTIC  = "deterministic"
```

`OperationKind` is the closed set of operation kinds the audit layer understands. It is the discriminator value used by `OperationDetails` (below) and the `details_kind` field of `OperationSummary` (the audit bundle's index entries — see *OperationSummary* below). Adding a new kind is a deliberate schema change, not a free-form string append.

#### Operation details — discriminated union

```python
class LlmCallDetails(BaseModel):
    kind: Literal[OperationKind.LLM_CALL] = OperationKind.LLM_CALL
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
    rate_limit_retries: int = 0          # transparent transport-level 429 retries (DR-LLM-07)
    raw_responses: list[JsonValue]       # may contain transcribed student text; see privacy note


class OcrCallDetails(BaseModel):
    kind: Literal[OperationKind.OCR_CALL] = OperationKind.OCR_CALL
    backend: str                         # "claude-multimodal","tesseract", ...
    pages: int
    underlying_operation_id: OperationId | None = None  # set when OCR runs through the LLM gateway


class MlInferenceDetails(BaseModel):
    kind: Literal[OperationKind.ML_INFERENCE] = OperationKind.ML_INFERENCE
    model_id: str
    model_version: str
    confidence: float | None = None


class ToolCallDetails(BaseModel):
    kind: Literal[OperationKind.TOOL_CALL] = OperationKind.TOOL_CALL
    tool_name: str
    arguments_digest: str


class HumanDecisionDetails(BaseModel):
    kind: Literal[OperationKind.HUMAN_DECISION] = OperationKind.HUMAN_DECISION
    actor: str                           # "teacher","reviewer"
    prompt_shown: str
    decision: str


class AgentStepDetails(BaseModel):
    kind: Literal[OperationKind.AGENT_STEP] = OperationKind.AGENT_STEP
    agent_id: str
    step_index: int
    action: str


class DeterministicDetails(BaseModel):
    kind: Literal[OperationKind.DETERMINISTIC] = OperationKind.DETERMINISTIC
    function: str                        # e.g. "parse_pdf","compute_evidence_profile"
    library_version: str | None = None


OperationDetails = Annotated[
    LlmCallDetails | OcrCallDetails | MlInferenceDetails |
    ToolCallDetails | HumanDecisionDetails | AgentStepDetails | DeterministicDetails,
    Field(discriminator="kind"),
]
```

#### OperationRecord, OperationSummary, IterationSnapshot, AuditBundle

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


class OperationSummary(BaseModel):
    """
    Index entry for an operation in the audit bundle. Carries the
    cheap, queryable fields needed by the UI and by audit-bundle
    consumers, plus a pointer to the per-operation detail file
    that holds the full OperationRecord.
    """
    id: OperationId
    stage_id: str
    started_at: datetime
    ended_at: datetime
    status: OperationStatus
    attempt: int = 1
    retry_of: OperationId | None = None
    inputs_digest: str
    outputs_digest: str | None
    details_kind: OperationKind          # closed enum, mirrors the embedded OperationRecord.details.kind
    details_path: str                    # relative POSIX path from the directory containing audit_bundle.json
    error: ErrorRecord | None = None


class IterationSnapshot(BaseModel):
    iteration: int                       # 0 = starting rubric measurement; 1+ = post-improvement re-measurements
    rubric_id: RubricId
    rubric_snapshot: Rubric              # full snapshot at this iteration
    quality_scores: list["CriterionScore"]    # measurements taken on this snapshot (defined § 4.9)
    finding_ids: list[FindingId]              # findings produced against this snapshot
    applied_change_ids: list[ChangeId] = []   # changes applied to produce the next iteration
    measured_at: datetime


class InputSourceKind(StrEnum):
    FILE        = "file"
    INLINE_TEXT = "inline_text"


class InputSource(BaseModel):
    """Role-agnostic provenance for one input artefact.

    Discriminated by `kind`:
    - `kind == FILE`        → `path` is the source file path; `hash` is DR-DAT-06 case (a) (file bytes).
    - `kind == INLINE_TEXT` → `path` is None; `marker` is a stable human-readable label
       (e.g. `"<inline:starting_rubric>"`); `hash` is DR-DAT-06 case (b) (text content).
    """

    kind: InputSourceKind
    path: str | None = None              # required iff kind == FILE; None otherwise
    marker: str | None = None            # required iff kind == INLINE_TEXT; None otherwise
    hash: str                            # never optional — every input has a content hash


class InputProvenance(BaseModel):
    exam_question: InputSource                  # always present (SR-IN-02)
    teaching_material: list[InputSource] = []
    starting_rubric: InputSource | None = None  # None when SR-IN-05 *absent* form is used
    student_copies: list[InputSource] = []


class AuditBundle(BaseModel):
    run_id: RunId
    schema_version: str
    started_at: datetime
    ended_at: datetime
    status: Literal["success","partial","failed"]
    input_provenance: InputProvenance
    evidence_profile: EvidenceProfile
    stages: list[StageRecord]
    operations: list[OperationSummary]   # index; full OperationRecord per entry lives at operations[i].details_path
    findings: list[AssessmentFinding]
    proposed_changes: list[ProposedChange]
    iteration_history: list[IterationSnapshot] = []   # empty for single-pass runs (SR-AS-09)
    output_file_path: str | None = None
    errors: list[ErrorRecord] = []
```

**Rationale.** `OperationRecord.details` is a discriminated union — future operation kinds slot in without schema migration. Each retry is its own `OperationRecord` linked via `retry_of`. `AuditBundle.operations` carries `OperationSummary` index entries (cheap, queryable) with `details_path` pointers to full `OperationRecord` blocks — keeping the index small for eager loading while large payloads (`raw_responses`) are lazy-loaded on drill-in. The deliverable (`ExplainedRubricFile`) **never contains raw student copy text**; the audit bundle is a separate reviewer-only artefact.

### 4.9 Deliverable: ExplainedRubricFile

The deliverable is a single JSON file. It is teacher-readable through its narrative fields and reviewer-inspectable through its references and quality scores. SR-OUT-01 mandates this artefact for every successful run; SR-OUT-02 mandates the two-field root structure (improved rubric + explanation); SR-OUT-03 mandates organization by the three quality criteria; SR-OUT-04 mandates schema validation; SR-OUT-05 mandates that teacher decisions are reflected.

```python
class CriterionScore(BaseModel):
    criterion: QualityCriterion
    score: float                         # 0.0–1.0; the measurement against one rubric snapshot
    confidence: ConfidenceIndicator
    method: QualityMethod                # closed enum, shared with Measurement.method
    source_operation_id: OperationId | None = None
    # the operation event that produced this score; the unambiguous join key
    # back into the audit-event stream / harvested AuditBundle for the per-sample
    # distribution and the raw model responses (DR-SCR-02). None only on the
    # `previous_quality_scores` slot of an iteration-0 deserialised file where
    # the operation_id is not preserved across rounds.


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

**Rationale.** One file serves both audiences. `explanation` carries the teacher narrative; `findings`, `proposed_changes`, `quality_scores`, and `evidence_profile` make the file self-auditing. `CriterionScore` carries a single `score` — the measurement of *one* rubric snapshot — so there is exactly one place in the file where any given (criterion, snapshot) pair appears. The before/after comparison required by SR-AS-09 is expressed at the file level by the `quality_scores` / `previous_quality_scores` pair, not by per-score `before`/`delta` fields that would duplicate the same data. `delta` is then a presentation-layer computation (`quality_scores[i].score - previous_quality_scores[i].score`), not a stored field that can drift. **The deliverable is the same shape on both demo paths** (§ 3.11): on Path A the `render` CLI subcommand writes it from the in-process stage outputs of the previous CLI invocations; on Path B the L3 harvester reads the workflow's terminal-task output and the SPA downloads the same bytes. The full iteration trajectory lives in the audit-view bundle (`AuditBundle.iteration_history`) on Path B only — Path A is single-stage inspection and never produces a bundle (§ 4.8); the deliverable itself surfaces only the two endpoints needed by the front-end and is bundle-independent.

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

Design Requirements describe *how* the system is built in order to satisfy the System Requirements. They are the most numerous layer of the V-shape chain — wider than the SR layer above them. They use the same MoSCoW criticality scale as the layers above (`Must` / `Should` / `Could`).

DRs are organized below into twelve groups by area (eleven original groups plus the v0.14.0-added § 5.12 *DR-INT*, the Validance integration group introduced by the pivot). Each group has its own intent paragraph and table.

### 5.1 Architecture and module decomposition (DR-ARC)

Defines the package layout, the module boundaries, the dependency direction, and how the hermetic-task structure allows each pipeline stage to run standalone or via an orchestration layer. Establishes the interface contracts between modules. The shape below realizes § 2's *eight modules + cross-cutting* picture in concrete Python packages and locks the dependency direction in code so a reviewer can verify the V-shape claim by running `pydeps` or reading `__init__.py` files directly.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-ARC-01** | Must | L1 is a single Python package `grading_rubric` with the sub-packages `models`, `parsers`, `assess`, `improve`, `output`, `scorer`, `gateway`, `audit`, `orchestrator`, `cli`, `config`. Each sub-package is a proper Python package (has `__init__.py`) and is the *only* place where its concern lives. No other sub-package may import from a private module of another sub-package — only from its public surface (`__init__.py`). The L3 Validance integration directory (`validance/`, per § 3.10 / § 5.12) is **not** a sub-package of `grading_rubric` and lives at the top level of the repository; the L4 SPA (`frontend/`, per § 3.10) is a separate deployable. | § 2.1, § 3.10 |
| **DR-ARC-02** | Must | Dependency direction is one-way: `cli` depends on `orchestrator` and on the stage packages directly (one CLI subcommand per stage, plus the `run-pipeline` thin-orchestrator subcommand — see DR-ARC-08); `orchestrator` depends on the stage packages (`parsers`, `assess`, `improve`, `output`, `scorer`); stage packages depend on `models`, `gateway`, `audit`, and `config` but **never on each other and never on `orchestrator` or `cli`**; `models`, `gateway`, `audit`, and `config` are leaves and depend only on the standard library and pinned third-party libraries. A static check (`pydeps` or equivalent) enforces this graph. | § 2.1 |
| **DR-ARC-03** | Must | Every pipeline stage exposes a single callable entry point conforming to a `Stage` protocol: `(stage_inputs, settings, audit_emitter) -> stage_outputs`. Stage entry points are pure with respect to global state (no module-level mutable state, no implicit caches, no environment reads outside the injected `settings`), and any filesystem I/O is restricted to (a) reading paths declared on `stage_inputs`, including the `parsers` carve-out for reading the user-supplied input files at well-known locations, and (b) writing through the `audit_emitter`. This is the in-code realization of § 2.2 *hermetic-task philosophy*. | § 2.2 |
| **DR-ARC-04** | Must | The `orchestrator` sub-package owns a **thin in-process stage chain** used for tests, local development, and the `run-pipeline` CLI subcommand. It instantiates each stage with its dependencies, runs them in order, emits stage lifecycle events to `audit`, and enforces the *one run, one in-memory state, no cross-run state* contract. **The in-process orchestrator is not a production execution surface**: production runs use Validance via the L3 integration directory (§ 3.11), where each stage is a separate Validance task and the workflow engine — not L1's `orchestrator` — owns inter-stage flow. The thin in-process orchestrator exists so the V-model unit / integration test layer (and the `run-pipeline` CLI subcommand for stage-level inspection) can chain stages without spinning up Validance. | § 2.1, § 2.2, § 3.11 |
| **DR-ARC-05** | Must | The `gateway` sub-package is the **only** module that imports an LLM SDK client (Anthropic by default per § 3.1, others pluggable). All LLM calls in every stage go through `gateway.measure(...)`. OCR for handwritten student copies is *not* a separate "model gateway"; the `parsers` sub-package exposes a `StudentCopyReader` interface (per § 3.5) whose Claude-multimodal implementation calls `gateway.measure(...)` and whose dedicated-OCR implementations (Azure Document Intelligence, Textract, etc.) talk directly to their respective SDKs without crossing the gateway. This keeps "the gateway is the LLM seam" and "OCR backends are pluggable" as two distinct, non-conflicting statements. | § 3.1, § 3.5 |
| **DR-ARC-06** | Must | The `audit` sub-package is a passive in-memory subscriber and the **producer** of structured operation events; it is **not** the writer of any cross-run audit chain. Stages and the gateway emit lifecycle and operation events through the `audit_emitter` injected by their caller (the in-process `orchestrator` for tests / `run-pipeline`, or directly the CLI subcommand for single-stage invocation). The collected events are exposed in two ways: (a) on Path A — direct CLI invocation (§ 3.11) — emitted as structured-JSON lines to `stderr` for operator inspection and optionally written next to the stage output as a per-stage operations file when the CLI is invoked with `--emit-operations`; (b) on Path B — Validance — surfaced to the L3 harvester (§ 5.12 *DR-INT*), which folds them into the typed `AuditBundle` view of § 4.8 by joining them with the Validance audit chain. The `audit` sub-package never reaches into `runs/<run_id>/`, never coordinates across stages, and never holds state beyond the lifetime of one stage call. | § 4.8, § 5.8, § 5.12, SR-OBS-01, SR-OBS-02 |
| **DR-ARC-07** | Must | **L1 has zero Validance imports.** No file under `grading_rubric/` (the L1 package), nor any Docker image baked from it (L2), may `import validance`, `import validance_sdk`, `import validance_workflow`, or any module thereof; `grading-rubric-cli` and every stage callable run successfully without `validance-sdk` installed. The boundary is verifiable by a single grep over the L1 source tree (`grep -rn 'validance' grading_rubric/` returns zero matches) and by the L1 dependency declaration in `pyproject.toml` (no `validance-sdk`, no `validance-workflow`). The L3 integration directory (`validance/`, § 5.12 *DR-INT*) is the **sole** site in the repository that imports `validance-sdk`. | § 2.1, § 3.10, § 3.11, § 5.12 |
| **DR-ARC-08** | Must | The `cli` sub-package exposes a single console-script entry point `grading-rubric-cli` with **one subcommand per pipeline stage** and a thin orchestrator subcommand: `ingest`, `parse-inputs`, `assess`, `propose`, `score`, `render`, and `run-pipeline` — **seven subcommands**. The first six are the per-stage subcommands of the assessment pipeline; `run-pipeline` chains them in order via the in-process `orchestrator` (DR-ARC-04) and is the same code path the test suite exercises. Each per-stage subcommand reads its structured input from disk (a JSON / Pydantic-validated file or a directory of inputs declared by the stage's `stage_inputs` schema), invokes the stage callable through the `Stage` protocol, and writes the structured output to a path the user specifies; this is the unit of single-stage inspection on Path A. The CLI is a thin shell — every per-subcommand handler is at most input validation, calling the stage callable, and writing the result. | § 3.10, § 3.11 |
| **DR-ARC-09** | Must | A single `Settings` object (per § 3.7) is built once at process boot from the environment, validated, and injected into the orchestrator. Stages receive `settings` as an argument and **must not mutate it**. There is no global `settings` singleton readable from arbitrary code. | § 3.7 |
| **DR-ARC-10** | Must | The L4 front-end SPA (per § 3.3, § 3.10) is a separate deployable that talks to **Validance's REST API** as its backend; it does **not** depend on any L1 Python code, does not import from `grading_rubric`, does not share a process with any L1 task, and does not read local files outside its own build artefacts. The contract on the wire is the typed `AuditBundle` / `ExplainedRubricFile` / `ProposedChange` shapes of § 4 (JSON Schema generated from `models` per § 3.6 and DR-DAT-03), which the L3 harvester populates from Validance's audit chain. There is no custom HTTP server in the L1 deliverable; serving the SPA is Validance's job on Path B. | § 3.3, § 3.10, § 3.11, § 5.12 |
| **DR-ARC-11** | Should | Each stage sub-package is testable in isolation by passing a stub `audit_emitter` and a stub `gateway`, with no in-process orchestrator and no Validance instance required. This is a structural property (it follows from DR-ARC-03, DR-ARC-05, and DR-ARC-07) that the unit-test layer of the V-shape relies on. | § 2.2 |
| **DR-ARC-12** | Should | The public Python surface of the L1 package is exactly what `grading_rubric.__init__` re-exports — the in-process orchestrator entry point, the per-stage callables, the public `models`, and the `Settings` class. Anything else is internal and may change without a schema-version bump. The L3 integration directory imports only this public surface (and `validance-sdk`). | DR-DAT-05 |

### 5.2 LLM usage (DR-LLM)

Defines prompt design (one prompt per measurement task, structured outputs), sampling strategy (temperature, k samples for reliability estimates), structured-output validation and retry policy, deterministic execution policy, and the abstraction layer that makes the LLM backend pluggable. The `gateway` sub-package is the realization of § 2.3 *LLMs as measurement instruments* and the only seam in the codebase that imports an LLM SDK client. Everything every other module knows about an LLM call is mediated by `gateway.measure(...)`. The gateway holds no business logic and no cache (per § 3.8); it knows about prompts, schemas, samples, retries, timeouts, and how to emit a structured operation event to the `audit_emitter` (per DR-ARC-06). It does **not** know about rubrics, findings, criteria, or any other domain shape — those are passed in as the typed inputs/outputs of the call. The `audit_emitter` it calls is L1's stderr-event producer of § 5.8 *DR-OBS*; on Path B (§ 3.11), the L3 harvester (§ 5.12 *DR-INT*) folds the emitted events into the typed `AuditBundle` view (§ 4.8) by joining them with Validance's audit chain.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-LLM-01** | Must | The `gateway` sub-package exposes a single public callable: `gateway.measure(prompt_id: str, inputs: BaseModel, output_schema: type[BaseModel], samples: int = 1, model: str \| None = None, *, settings: Settings, audit_emitter: AuditEmitter) -> MeasurementResult[T]`. `MeasurementResult[T]` carries `samples: list[T]` (validated instances of `output_schema`), `operation_id: OperationId`, and `aggregate: T \| None` (set only when `samples == 1`). All other call sites in the codebase use this signature; alternative entry points are forbidden. | § 3.2, DR-ARC-05 |
| **DR-LLM-02** | Must | Prompts live in `grading_rubric/gateway/prompts/<prompt_id>.md` as markdown files with YAML front-matter (`prompt_version`, `description`, `expected_inputs`, `expected_output_schema_id`). The gateway loads them once at boot into a `PromptRegistry` keyed by `prompt_id`. `prompt_hash` is the SHA-256 of the file's UTF-8 bytes (text-content case of DR-DAT-06); `schema_hash` is the SHA-256 of the canonical-JSON encoding of `output_schema.model_json_schema()` (structured-object case of DR-DAT-06). Both hashes are recorded on every emitted `LlmCallDetails`. The `schema_id` field on `LlmCallDetails` is the string `f"{output_schema.__module__}.{output_schema.__name__}@{prompt_version}"` so the harvester can group operations by schema without loading any detail block. | § 3.2, DR-DAT-06 |
| **DR-LLM-03** | Must | Structured output is obtained via Anthropic tool use: the gateway derives a single tool definition from `output_schema.model_json_schema()`, calls `client.messages.create(..., tools=[...], tool_choice={"type": "tool", "name": ...})`, and extracts the tool-input block. No prose-mode parsing, no regex extraction, no `instructor` / `langchain` / `dspy`. The tool-input block is `json.loads`-parsed first and then strictly validated against `output_schema` per the LLM-tool-use carve-out in DR-DAT-02. | § 3.2, DR-DAT-02 |
| **DR-LLM-04** | Must | Validation retry policy: on Pydantic `ValidationError` against the tool-input block, the gateway makes **at most one** retry call with a system message appended that quotes the validation error verbatim and instructs the model to correct it. A second failure raises `GatewayValidationError` and is recorded as a separate operation event linked to the first via `retry_of` (per § 4.8). The `validation_retry_count` of § 3.2 is the count of `attempt > 1` operations in the harvested chain — a derived view, not a stored counter. The `retry_of` field is populated on the stderr event itself; the L3 harvester (DR-INT-05) reconstructs the chain by joining events on `retry_of`. | § 3.2, § 4.8, DR-INT-05 |
| **DR-LLM-05** | Must | Sampling: when `samples > 1`, the gateway makes `samples` independent `messages.create` calls (no `n` parameter shortcut, no batching) and returns `MeasurementResult.samples` as a list of `samples` validated instances. The gateway does **no aggregation** beyond returning the list — every aggregation policy (majority vote, mean, Krippendorff's α, …) lives in the calling stage so the harvested view records the raw sample distribution, not a collapsed verdict. `MeasurementResult.aggregate` is set only when `samples == 1` (the trivial aggregate). | § 3.9, § 5.4 |
| **DR-LLM-06** | Must | Deterministic execution policy realized in code: when `samples == 1` the gateway sets `temperature=0.0` unconditionally. When `samples > 1` the gateway uses `Settings.llm_sampling_temperature` (default `0.7`). The model identifier passed to the SDK is `Settings.llm_model_pinned` (default `claude-sonnet-4-6-<snapshot>`); a non-pinned model identifier is rejected at boot by `Settings` validation. No `seed` parameter is passed (the Anthropic Messages API does not accept one); the honest determinism guarantee is measurement-level stability + audit-level reconstructability via the harvested view, not bit-identical reproducibility. | § 3.9 |
| **DR-LLM-07** | Must | Per-call timeout is `Settings.llm_call_timeout_seconds` (default `60`). On timeout the gateway raises `GatewayTimeoutError` and emits a `FAILED` operation event whose `error.code` is `"TIMEOUT"`. **Rate-limit transparency rule:** rate-limit (HTTP 429) responses are retried with exponential backoff up to `Settings.llm_rate_limit_max_retries` (default `3`); **each rate-limit retry is *not* a separate operation event** — it is wire-level transport behavior, transparent to the harvested chain — but the final outcome's `LlmCallDetails` records `rate_limit_retries: int`. Validation retries (DR-LLM-04) cross the operation boundary and become linked events; transport retries do not. | § 3.9 |
| **DR-LLM-08** | Must | Every successful or failed gateway call calls `audit_emitter.record_operation(...)` exactly once with a fully-populated `LlmCallDetails`: `prompt_id`, `prompt_version`, `prompt_hash`, `schema_id`, `schema_hash`, `model`, `temperature`, `samples`, `tokens_in: int`, `tokens_out: int` (totals across samples — the SDK reports these per `messages.create` call and the gateway sums them), `rate_limit_retries`, `raw_responses` (the parsed tool-input blocks for every sample, including ones that failed validation in DR-LLM-04 — kept as `JsonValue` so the audit captures the actual model output that failed). `inputs_digest` is the structured-object digest of `inputs.model_dump(mode="json")`; `outputs_digest` is the structured-object digest of `MeasurementResult.samples` (or `None` on failure). The `audit_emitter` is the stderr-event producer of DR-OBS-01; the gateway never writes to a file directly and never reaches into any `runs/<run_id>/` directory. | SR-OBS-02, § 4.8, DR-ARC-06, DR-DAT-06, DR-OBS-01 |
| **DR-LLM-09** | Must | Backend pluggability: the gateway depends on a thin internal `LlmBackend` protocol (`create_message(...) -> RawMessageResponse`) with `AnthropicBackend` as the default implementation. Alternative backends (`OpenAIBackend`, `LocalBackend`, …) implement the same protocol; selection is via `Settings.llm_backend` (default `"anthropic"`). The protocol surface is intentionally minimal: backends do not know about prompts, schemas, retries, or audit — those concerns belong to the gateway, not the backend. | § 3.1 |
| **DR-LLM-10** | Must | Test seam: tests substitute the gateway by injecting a `StubGateway` that records the calls and returns canned `MeasurementResult` instances. Stages are unit-testable without an LLM SDK installed and without network access. The same test seam works whether the test is exercising one stage in isolation (DR-ARC-11) or the in-process stage chain through the thin orchestrator (DR-ARC-04). | DR-ARC-11 |
| **DR-LLM-11** | Must | The gateway emits each operation event as a structured-JSON line on `stderr` with the schema locked by DR-OBS-01. **This is the L1↔L3 audit contract** (DR-INT-03), not operational telemetry: the L3 harvester (DR-INT-05) reconstructs the typed `AuditBundle` view (§ 4.8) by parsing this stream and joining it with Validance's per-task audit chain. The line schema must be sufficient to reconstruct an `OperationRecord` end-to-end without any other input — every digest, every hash, every retry link, every detail block lives on the line. On Path A (direct CLI invocation, § 3.11) the same lines are emitted to `stderr` for operator inspection; the CLI's `--emit-operations` flag (DR-ARC-06 case (a)) additionally writes them to a sibling file. | SR-OBS-02, § 5.8, DR-ARC-06, DR-INT-03, DR-INT-05 |

### 5.3 Data models and persistence (DR-DAT)

Realizes the schemas defined in § 4 in code. Defines validation, serialization, schema versioning and codegen, the hashing rules used by every digest field, and the (intentionally minimal) on-disk persistence model. After the v0.14.0 pivot the persistence model is **strictly per-stage**: each L1 stage writes its single declared `--output` file (and only that file) — the deliverable `ExplainedRubricFile` (§ 4.9) is the `render` stage's output; the audit-view bundle (`AuditBundle`, § 4.8) is **not** an L1 artefact but a *typed view* the L3 harvester (DR-INT-05) constructs from Validance's audit chain on Path B; on Path A (single-stage CLI invocation) no bundle is produced and the question of where to write it does not arise. L1 has no cross-session storage (per [`requirements.md`](requirements.md) § 1.2 *out of scope*), no `runs/<run_id>/` directory layout, and no reach into any orchestrator-defined working directory beyond the `--output` paths the CLI caller declares.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-DAT-01** | Must | All shapes from § 4 are realized as Pydantic v2 models in the `grading_rubric.models` sub-package. The Pydantic class is the single source of truth — no parallel hand-written dataclasses, no parallel JSON Schema files. **`grading_rubric.models` is the home of the § 4 *contract* shapes only** — the cross-stage Domain models, Provenance models, and Shared primitives that travel along the L1↔L3 boundary, the audit-event stream, the deliverable, and the codegen surface (DR-DAT-04). **Stage-local input/output models** that exist only inside one stage's Python module surface (e.g. the `IngestInputs` / `ExamQuestionSource` / `StartingRubricSource` / `StudentCopySource` records of DR-IO-07 and the `ScoreInputs` / `ScoreOutputs` records of DR-SCR-01) live in the **stage sub-package** that owns them (`grading_rubric.parsers.models`, `grading_rubric.scorer.models`) — not in `grading_rubric.models`. The rule is: a shape lives in `grading_rubric.models` if **and only if** it appears in § 4; everything else is stage-local and lives next to its stage. The stage-local Pydantic classes are subject to the same strict-mode discipline of DR-DAT-02, but they are deliberately out of the codegen surface of DR-DAT-03 / DR-DAT-04 because the SPA never sees them. | § 3.6, § 4.1 |
| **DR-DAT-02** | Must | All contract models — `Rubric`, `AssessmentFinding`, `ProposedChange`, `Explanation`, `EvidenceProfile`, `AuditBundle`, `OperationSummary`, `OperationRecord`, `ExplainedRubricFile` and the discriminated unions they reach — are configured `model_config = ConfigDict(strict=True)`. Strict mode rejects type-coercion of inputs (no `"1"` → `1`, no `"true"` → `True`, no `"2025-01-01"` → `datetime` from a non-ISO string), so contract violations fail loudly at the boundary instead of silently degrading. Two carve-outs: (a) the `parsers` sub-package may apply controlled coercion when reading user-supplied files (text, PDF metadata, etc.) — its job is exactly to turn loose input into strict models — and (b) LLM tool-use responses arrive as JSON which is parsed by `json.loads` first and then validated against the strict model. The strictness is on the *Pydantic boundary*, not on the upstream byte-level format. | § 3.2, § 4.1 |
| **DR-DAT-03** | Must | A `make schemas` target regenerates JSON Schema files for every top-level shape (`Rubric`, `AuditBundle`, `OperationRecord`, `OperationSummary`, `ExplainedRubricFile`) plus the wire schema for L1's stderr audit-event stream (`audit_event.v1.schema.json`, locked by DR-OBS-01) into `schemas/`. The regenerated files are checked into the repository so a reviewer can inspect the wire format without running Python, and so the L3 harvester (DR-INT-05) can validate every line it reads against the same committed schema L1 emits to. CI fails if the generated files drift from the committed ones. | SR-OUT-04, § 3.6, DR-OBS-01 |
| **DR-DAT-04** | Should | The `make schemas` target also regenerates the front-end TypeScript types (via `json-schema-to-typescript`) and the runtime zod validators (via `json-schema-to-zod`) into `frontend/src/generated/`. The front-end never hand-writes types for any shape that crosses the API boundary. | § 3.3, § 3.6 |
| **DR-DAT-05** | Must | Every top-level shape carries a `schema_version` string and is versioned independently of the application version, following semver. An incompatible field change bumps the shape's MAJOR version; an additive field change bumps MINOR; a clarification or doc-only change bumps PATCH. The `make schemas` target writes versioned files (`explained_rubric_file.v<MAJOR>.<MINOR>.schema.json`) so older deliverables remain readable against the matching schema. | § 3.6, § 4.10 |
| **DR-DAT-06** | Must | All identifier fields typed as `RubricId`, `LevelId`, `RunId`, `OperationId`, `FindingId`, `ChangeId` are `uuid.UUID` instances at runtime (the type aliases of § 4.1 are real `uuid.UUID`, not `str`). All datetimes are timezone-aware UTC `datetime` instances; naive datetimes are rejected. All string-valued enums are realized as `StrEnum`. Hashing rule, applied uniformly to every digest field in § 4 (`prompt_hash`, `schema_hash`, `arguments_digest`, `inputs_digest`, `outputs_digest`, `*_hash` on `InputProvenance`, etc.): **(a)** *file* hashes are SHA-256 of the raw file bytes, **(b)** *text content* hashes are SHA-256 of the UTF-8 encoding of the text, **(c)** *structured-object* digests are SHA-256 of the canonical-JSON UTF-8 encoding (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`, ISO-8601 datetime strings, UUIDs as their canonical hyphenated string form). Each digest field's docstring states which of the three cases applies. | § 4.1, § 4.8 |
| **DR-DAT-07** | Must | L1 stages write **only structured stage outputs to user-specified paths**; L1 does not own a `runs/<run_id>/` directory layout, does not allocate run IDs, and does not assume any directory hierarchy beyond what the CLI caller declares on `--output`. Each per-stage `grading-rubric-cli` subcommand (DR-ARC-08) reads its `stage_inputs` from `--input` paths, runs the stage callable, and writes the structured `stage_outputs` to a `--output` path; the `render` subcommand writes the `ExplainedRubricFile` (§ 4.9) to the path the caller specifies and is the sole writer of that artefact. The on-disk shape of the audit-view bundle (`AuditBundle`, § 4.8) is **not** an L1 concern — it is owned by the L3 harvester (`validance/harvester.py`) and locked in § 5.12 *DR-INT*. The atomic-write temp files of DR-DAT-08 are an implementation-internal exception: they live next to the target file with a `.tmp-<uuid>` suffix and are renamed before any other process can observe them. | § 4.9, § 5.9, § 5.12, SR-OUT-01, SR-OUT-02 |
| **DR-DAT-07a** | Must | Index/detail invariant on the audit-view bundle (§ 4.8). Every entry in the `AuditBundle.operations` array references — via `details_path`, resolved relative to the directory containing the index — an existing per-operation detail block, and conversely every per-operation detail block is referenced by exactly one summary entry. The L3 harvester (§ 5.12 *DR-INT*) is the sole producer of the bundle and produces both sides as a single logical commit (all per-operation detail blocks first, then the index last) so a partial harvest on disk is still consistent. A self-check on load (`AuditBundle.model_validate` plus a path-resolution sweep) fails the load if the invariant is violated. On Path A (CLI direct invocation, § 3.11) no bundle is produced and the invariant has no subject; the invariant binds only the harvested view on Path B. | § 4.8, § 5.12, SR-OBS-01 |
| **DR-DAT-08** | Should | Any file an L1 stage writes through the CLI `--output` path is written atomically: write to a sibling temp file, `fsync`, then `os.rename` over the target. This protects a reviewer (or a Validance task's downstream consumer) who reads the file while a stage upstream is still running. The same discipline applies to the L3 harvester when it writes the audit-view bundle. | § 5.9, § 5.12 |
| **DR-DAT-09** | Must | L1 has no database, no ORM, and no cross-session state of any kind. Each per-stage CLI subcommand is a self-contained read-input-run-write-output process; no in-process state survives the call; no stage ever reads from any other stage's working directory. Multi-run coordination, run identity allocation, and cross-stage state propagation are the orchestrator's job (§ 3.11) — handled by Validance on Path B and explicitly absent on Path A. | requirements.md § 1.2, § 3.11 |
| **DR-DAT-10** | Should | `Settings` (per § 3.7) provides only environment-driven, value-typed configuration (model identifiers, timeouts, sampling parameters, secret references); it does **not** declare or assume any output directory layout. CLI `--input` / `--output` paths are the sole I/O surface for L1 stages, so the same code runs unchanged against a host bind-mount, a tmpfs in CI, a Validance task work directory, or any future orchestrator's task working set. Any orchestrator-specific directory convention (Validance's `/work` mount, etc.) is the L3 integration's concern, not L1's. | § 3.7, § 3.11, § 5.12 |

### 5.4 Assessment algorithms (DR-AS)

The assess stage is **simulation-backed**: it runs a shared grader simulation (4 personas × N responses), then three pure-Python engines extract ambiguity, applicability, and discrimination findings from the resulting grade matrix. **The engines do not call the LLM** — only the simulation does (grading calls + pairwise comparisons). The score stage re-runs the same simulation against the improved rubric using the same response set, producing before/after `CriterionScore` records with `QualityMethod.GRADER_SIMULATION`.

**Grader simulation** (`grading_rubric.assess.simulation`). The simulation assembles a response set (real student texts + synthetic responses to reach `Settings.assess_target_response_count`, default 10), then grades every response with 4 fixed personas. Only leaf criteria (criteria with no `sub_criteria`) are graded; parent criteria provide context but are not independently scored, avoiding double-counting.

| Persona | Strategy |
|---|---|
| Bottom-up strict | Starts at 0, adds credit only for verified elements |
| Top-down generous | Starts at full credit, subtracts for clear misses |
| Rubric-literal | Grades exactly what the rubric says |
| Student-intent | Tries to understand what the student meant |

Each persona grades each response against each leaf criterion via one `gateway.measure()` call (`prompt_id = "ambiguity_grade_with_rubric"`, `samples=1`, temperature `0.3`), producing a `(personas × responses × criteria)` grade matrix with values in `[0, 1]`. Temperature 0.3 balances persona diversity with grading consistency — high temperatures produce noisy grades that inflate agreement variance. Concurrency: `ThreadPoolExecutor` at `Settings.assess_llm_concurrency` (default 4) workers. Pairwise comparisons use stratified pair selection (borderline-adjacent → borderline-borderline → high-contrast → adjacent-tier → real-vs-synthetic), capped at `Settings.assess_pairwise_sample_size` (default 10), temperature `0.2`.

**Three engines, three criteria.** Each engine implements `MeasurementEngine` Protocol: `measure_from_simulation(sim, rubric, settings) -> list[AssessmentFinding]`.

- **AmbiguityEngine**: computes Krippendorff's α (ordinal) per criterion across all personas and responses. Finding emitted when `alpha < 0.80`. Confidence: `max(0.20, min(0.90, alpha))`. Five-band classification: α ≥ 0.90 excellent ("Graders consistently agree"), ≥ 0.80 good, ≥ 0.67 moderate, ≥ 0.50 weak, < 0.50 poor. Severity: HIGH when α < 0.67, MEDIUM otherwise. Method: `LLM_PANEL_AGREEMENT`.
- **ApplicabilityEngine**: bimodal edge polarization (floor ≤ 0.10 and ceiling ≥ 0.90 present), edge disagreement, and criterion-response orphan patterns are applicability-gap signals. Same threshold/severity logic. Method: `SYNTHETIC_COVERAGE`.
- **DiscriminationEngine**: two sub-methods. (a) **Score distribution separation**: when synthetic calibration data is available, a 4-component weighted average — calibration score (`1.0 - 2×mean_error`, weight 0.25), rank correlation (Spearman, rescaled to [0,1], weight 0.20), pairwise consistency (weight 0.15), ceiling-effect score (weight 0.40). Hard cap of 0.60 when >50% of non-excellent synthetics score ≥ 0.90. When no synthetic calibration exists, fallback: `0.5 × separation + 0.5 × pairwise_consistency`. (b) **Pairwise consistency**: near-equal absolute scores but clear pairwise winner → discrimination finding (with optional linked ambiguity finding per SR-AS-10 dual signal).

**Headline scores** (`scores_from_simulation`): per-criterion scores averaged across criteria, all using `QualityMethod.GRADER_SIMULATION`. Both assess and score stages compute scores from the simulation; assess stores them as `AssessOutputs.quality_scores` (used as `previous_quality_scores` in the deliverable), score computes them against the improved rubric. When a baseline simulation from the assess stage is available, the score stage computes paired deltas (same persona × same response) to cancel correlated noise, yielding more reliable before/after comparisons. The simulation evidence is preserved across stages for this purpose.

**Evidence preparation.** If `len(real_copies) ≥ Settings.assess_min_real_copies` (default 3), only real responses are used; otherwise synthetic responses are generated (temperature 0.4) to reach the target count, and `evidence_profile.synthetic_responses_used = True`.

**Empty rubric.** Returns a degenerate `AssessOutputs` with one HIGH APPLICABILITY finding, no engine invocations.

**Re-measurement.** A fresh `assess` call against the updated rubric; previous findings are not carried forward. `Settings.max_iterations` (default 3) is a caller-enforced safety bound.

**Simulation topology:**

```
  ┌─────────────────────────────────────────────────────────┐
  │  run_grader_simulation()                                │
  │                                                         │
  │  1. Assemble response set (real + synthetic)            │
  │  2. Grade: 4 personas × N responses × C criteria        │
  │     → (N × 4 × C) gateway.measure() calls, temp 0.3    │
  │     → ThreadPoolExecutor(assess_llm_concurrency)        │
  │  3. Pairwise: stratified sample of pairs                │
  │     → up to 10 gateway.measure() calls, temp 0.2       │
  │                                                         │
  │  Output: SimulationEvidence (grade_entries,              │
  │          pairwise_results, response_set, personas)       │
  └──────────────────────┬──────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   AmbiguityEngine  ApplicabilityEngine  DiscriminationEngine
   (grade stdev)    (edge polarization)  (calibration + pairwise)
          │              │              │
          └──────────────┼──────────────┘
                         ▼
   AssessOutputs: findings + quality_scores + evidence_profile
```

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-AS-01** | Must | The `assess` sub-package exposes a single `Stage`-protocol callable: `assess(stage_inputs: AssessInputs, settings, audit_emitter) -> AssessOutputs`. **`AssessInputs`** carries the parsed `Rubric` (possibly with `criteria == []` for the SR-IN-05 *no starting rubric* form, see DR-AS-15), the parsed `response_set: list[ParsedResponse]` from `parse_inputs`, the optional parsed `teaching_material`, and the upstream `EvidenceProfile`. **`AssessOutputs`** carries `findings: list[AssessmentFinding]` (§ 4.5), a refined `evidence_profile: EvidenceProfile` whose `synthetic_responses_used` flag is set per DR-AS-04, `quality_scores: list[CriterionScore]` computed by `scores_from_simulation()` from the same grade matrix the engines measured, the `simulation_evidence: SimulationEvidence` trace, and a human-readable `simulation_summary: str`. The `quality_scores` serve as **`previous_quality_scores`** in the score stage's output (DR-SCR-01) so the deliverable can show before/after; the headline scores on the *improved* rubric are produced by the score stage re-running the simulation (DR-SCR-02). Per-finding measurement and provenance live on each `AssessmentFinding`'s embedded `measurement` and `source_operations` fields. The stage is hermetic per DR-ARC-03: no module-level mutable state, every LLM call goes through `gateway.measure(...)` (DR-LLM-01). The stage-local input/output classes (`AssessInputs`, `AssessOutputs`, the per-engine intermediate shapes) live in `grading_rubric.assess.models` per the stage-local rule of DR-DAT-01; only the § 4.5 contract shapes (`AssessmentFinding`, `Measurement`, `EvidenceProfile`) live in `grading_rubric.models`. | SR-AS-01, SR-AS-02, SR-AS-03, SR-AS-07, § 2.2, DR-ARC-03, DR-DAT-01, DR-SCR-01 |
| **DR-AS-02** | Must | The assess stage internally composes **three measurement engines**, one per `QualityCriterion` value, each implementing a stage-local `MeasurementEngine` Protocol: `measure_from_simulation(self, sim: SimulationEvidence, *, rubric: Rubric, settings: Settings) -> list[AssessmentFinding]`. The three engines are `AmbiguityEngine`, `ApplicabilityEngine`, and `DiscriminationEngine`, all in `grading_rubric.assess.engines`. The engines are **pure-Python and synchronous** — they compute from the grade matrix in `SimulationEvidence`, they do **not** call the LLM. The assess stage's body is: (1) run `run_grader_simulation()` to produce `SimulationEvidence` (the LLM-intensive step), (2) call each engine's `measure_from_simulation()` and concatenate the returned finding lists, (3) call `scores_from_simulation()` on the same evidence to produce `quality_scores`, (4) refresh `evidence_profile` and return. | SR-AS-01, SR-AS-02, SR-AS-03, DR-PER-03, DR-PER-04 |
| **DR-AS-03** | Must | Evidence preparation happens inside `run_grader_simulation()`: if `len(real_responses) < Settings.assess_target_response_count` (default `10`), the simulation synthesises additional tiered responses (DR-AS-04) to reach the target count. The same prepared response set is used for all grading and pairwise comparisons so the three criterion measurements are made against the same evidence. The `evidence_profile.synthetic_responses_used` flag is set to `True` when any synthetic responses were added **or** when `len(student_copies) < Settings.assess_min_real_copies` (default `3`); the latter threshold is calibrated to the brief's three-handwritten-copy example. | SR-AS-05, SR-AS-06, § 4.4 |
| **DR-AS-04** | Must | Synthetic responses are generated by a single `gateway.measure(...)` call (`prompt_id = "assess_synthesize_responses"`, output schema = `SynthesizedResponseSet`, temperature `0.4`) that produces quality-tiered student answers. When teaching material is present (SR-AS-04), it is included verbatim in the prompt; without it the LLM draws on the exam question alone. **Real student responses are never fed into this prompt** — privacy invariant. Each generated response carries a `source = ResponseSource.SYNTHETIC` marker, a `quality_tier` string, and an `intended_score` float for calibration checking in the discrimination engine. | SR-AS-04, SR-AS-06, § 4.4, DR-LLM-02 |
| **DR-AS-05** | Must | Confidence per `AssessmentFinding` is computed inline by each engine. Ambiguity findings: `max(0.20, min(0.90, alpha))` where `alpha` is Krippendorff's α for the criterion. Applicability findings: `max(0.20, min(0.85, 1.0 - problem_rate))`. Discrimination spread findings: constant `0.65`. Discrimination pairwise findings: constant `0.60`. Ambiguity-attributed pairwise findings: constant `0.55`. The **floor of `0.20`** preserves LOW-confidence honesty without forcing decorative zeros. The `ConfidenceIndicator.rationale` string is **mandatory and human-readable**, naming the signal source (e.g. *"Krippendorff's α=0.62 (moderate)"*). Per-criterion `CriterionScore.confidence` on the deliverable is a separate concern owned by `scores_from_simulation()` and the score stage (DR-SCR-02). | SR-AS-08, § 4.5, DR-SCR-02 |
| **DR-AS-06** | Must | The **`AmbiguityEngine`** measures ambiguity from the shared grader-simulation grade matrix. For each `(response, criterion)` row, high persona disagreement in the middle of the 0..1 scale is an ambiguity signal; trivial ceiling/floor agreement is not counted as evidence of clarity. Rows with fewer than three midscale opportunities lower confidence rather than producing vacuous high scores. Findings use `Measurement.method = LLM_PANEL_AGREEMENT` because the signal comes from independent persona grades. | SR-AS-01, SR-AS-07, DR-LLM-01, DR-LLM-05 |
| **DR-AS-07** | Must | The **`ApplicabilityEngine`** measures applicability from the same grade matrix, without asking graders for self-reported applicability status. Edge polarization, bimodal floor/ceiling splits, and criterion-response orphan patterns become applicability-gap signals with `Measurement.method = SYNTHETIC_COVERAGE`. The grader prompt therefore remains focused on grading only: grade plus justification. | SR-AS-02, SR-AS-07, § 4.5 |
| **DR-AS-08** | Must | The **`DiscriminationEngine`** measures whether the rubric separates weak from strong work by combining score spread, synthetic calibration against intended tiers, rank correlation, ceiling-effect penalties, and pairwise consistency checks. Pairwise comparisons are sampled from informative pairs rather than only anchoring to response zero. Findings use `SCORE_DISTRIBUTION_SEPARATION` or `PAIRWISE_CONSISTENCY` depending on the contributing signal. | SR-AS-03, SR-AS-10, SR-AS-07 |
| **DR-AS-09** | Must | When the discrimination engine's pairwise sub-method (DR-AS-08-b) detects a pairwise inconsistency **and** the LLM's accompanying explanation attributes the inconsistency to *ambiguous criterion wording* rather than to a *coarse scoring scale*, the engine produces **two linked `AssessmentFinding` instances over the same evidence**: a discrimination-power finding (per DR-AS-08) **and** a separate ambiguity finding (per DR-AS-06). Each finding still carries exactly one `criterion` value (preserving SR-AS-07); the link between the two is expressed by `linked_finding_ids` (symmetric — each finding's `linked_finding_ids` contains the other's id). The pair is the in-engine realization of the SR-AS-10 dual-signal pattern documented in § 4.5; the discrimination engine writes both findings into its returned list and the assess stage merger preserves the link unchanged. | SR-AS-10, SR-AS-07, § 4.5 |
| **DR-AS-10** | Must | Every `AssessmentFinding` produced **by any of the three measurement engines** has its `source_operations: list[OperationId]` field populated with the IDs of every `operation` audit event whose `gateway.measure(...)` call contributed to the finding. The L3 harvester (DR-INT-05) dereferences this list against the harvested `AuditBundle.operations` index per the DR-DAT-07a invariant; a reviewer reading the deliverable can pull up the raw model responses that produced any finding. This is the engine-side counterpart of the index/detail discipline locked in § 4.8. **Explicit exception:** the degenerate from-scratch finding produced by DR-AS-15 has `source_operations = []` because no `gateway.measure(...)` call was issued — the finding announces the absence of a rubric to measure, not the result of a measurement. The empty list is the honest signal *"no operations to dereference"* and is the only place an `AssessmentFinding` is allowed to carry an empty `source_operations` list; downstream validators of `AssessmentFinding` must therefore accept `len(source_operations) >= 0` rather than `> 0`. | SR-AS-08, § 4.5, § 4.8, DR-AS-15, DR-DAT-07a, DR-INT-05 |
| **DR-AS-11** | Must | The assess stage is **idempotent in its declared inputs**: re-running the stage against the same `AssessInputs` + the same `Settings` + the same model pin + the same prompt content hashes produces a comparable `AssessOutputs` whose differences are auditable through the audit chain, modulo the LLM non-determinism explicitly disclaimed in § 3.9. *Comparable* means: the set of finding `id`s may differ between runs (different operation IDs, different timestamps), but the *kinds* of findings produced (criterion, severity bucket, target node, measurement method) are stable, and any difference is reconstructable by walking the per-call `operation` events. The honest claim is **rerun against the same declared inputs and audit any differences**, not "get the same answers" — the latter would overclaim relative to the existing § 3.9 determinism position. This is the engine-side guarantee that DR-AS-12's re-measurement loop relies on. | § 2.2, § 3.9, SR-AS-09 |
| **DR-AS-12** | Must | A **re-measurement run** (SR-AS-09) is a fresh `assess` invocation against an updated rubric. The engines do **not** carry findings forward across iterations — every finding from the previous iteration is stale by the § 4.5 staleness rule (its `measured_against_rubric_id` no longer matches). The `iteration` field on every produced `AssessmentFinding` records the iteration index (`0` for the first run, `n` for the `n`-th re-measurement). The previous iteration's findings are **not** consumed by `assess` itself; the `previous_quality_scores` field on the deliverable (§ 4.9) is written by the `render` stage from the score stage's outputs across iterations, not from the assess findings. **`Settings.max_iterations` (default `3`) is a caller-enforced safety bound** — the in-process orchestrator on Path A enforces it, the Validance workflow's `ApprovalGate` loop (DR-INT-06) on Path B enforces it; assess itself never iterates: one call equals one measurement pass. | SR-AS-09, UR-08, § 4.5, § 4.9, DR-INT-06 |
| **DR-AS-13** | Must | The assess stage emits exactly the structured audit events the gateway emits per `gateway.measure(...)` call (DR-LLM-08, DR-OBS-01) plus its own `stage.start` / `stage.end` envelope events (DR-OBS-03). It does **not** emit per-engine, per-response, or per-finding events of its own — the gateway operation events plus the per-finding `source_operations` link already carry the full re-measurement story for the L3 harvester to reconstruct. assess is a *coordinator* of measurements, not a producer of new event kinds, and the closed five-event-kind set of DR-OBS-01 stays closed. | DR-OBS-01, DR-OBS-03, DR-LLM-08 |
| **DR-AS-14** | Should | Each engine handles **per-call failure** (gateway timeout, validation error, transport error after DR-LLM-04 retries) by recording the failure in its per-response per-method bookkeeping and continuing with the remaining responses. A failure rate above `Settings.assess_max_failure_fraction` (default `0.25`) on any one engine causes the engine to emit a single high-severity *measurement-failure* `AssessmentFinding` (`severity = HIGH`, `criterion = <the engine's criterion>`, `target = None`, `observation` naming the failure rate and the method affected) instead of (or in addition to) its normal findings. **The assess stage as a whole always returns its `AssessOutputs`** — partial measurement is the contract, not all-or-nothing. The score stage (DR-SCR-01 / DR-SCR-02) is responsible for what to do with a measurement-failure finding when it produces `CriterionScore` records downstream. *v1.0 note: `Settings.assess_max_failure_fraction` is deferred to v2; the engine currently logs failures but does not enforce a threshold.* | SR-AS-08, § 4.4, DR-SCR-02 |
| **DR-AS-15** | Must | When the input rubric is the **from-scratch placeholder** (SR-IN-05 *no starting rubric* form, surfaced through `parse_inputs` as a `Rubric` instance with `criteria == []`), the assess stage runs to completion and returns a **degenerate `AssessOutputs`**: `findings` contains exactly one high-severity `AssessmentFinding` with `criterion = APPLICABILITY` (the criterion most directly motivated by *"the rubric does not yet describe what the response space looks like"*), `severity = HIGH`, `target = None`, `observation = "no rubric to measure — propose stage will generate from scratch"`, and an empty `source_operations` list (no gateway calls were issued); `evidence_profile` is the upstream profile passed through. The three engines are **not invoked** in the from-scratch case — there is nothing to measure. The hermetic stage chain of DR-ARC-03 is preserved (assess always returns its typed output, never raises on empty input), and the `propose` stage (§ 5.5 *DR-IM*, future round) consumes this degenerate output and runs the from-scratch generation path. The alternative — having assess refuse to run on an empty rubric — was rejected because it would force `propose` to read its inputs from somewhere other than the previous stage's typed output, breaking the stage-chain contract. | SR-IN-05, SR-AS-02, § 4.5, DR-ARC-03 |

**Counts**: 15 DRs (14 Must / 1 Should).

### 5.5 Improvement generation (DR-IM)

The `propose` stage takes assess's `findings` and the grader simulation summary, and produces an `improved_rubric` with a `proposed_changes` list. The score stage then re-runs the simulation against the improved rubric to produce headline scores (DR-SCR-01 / DR-SCR-02).

**v1.0 scope.** Only the **modify-existing** path is implemented: the LLM planner proposes `REPLACE_FIELD` and `ADD_NODE` edits grounded in assessment findings. `ADD_NODE` is used when discrimination findings call for splitting a criterion into finer sub-criteria. The generate-from-scratch path (DR-AS-15 sentinel) and the LLM-driven grounding-check / narrative-assembly calls described in the DR table below are **defined for extensibility but not implemented in v1.0** — the planner is the single LLM call. Other operation types (`UPDATE_POINTS`, `REMOVE_NODE`, `REORDER_NODES`) are schema-defined but the planner does not produce them.

**Drafts vs final changes.** The planner emits `ProposedChangeDraft` records carrying only **LLM-owned fields** (`operation`, payload, `primary_criterion`, `source_findings`, `rationale`, `confidence`). The **system-owned fields** (`id`, `application_status`, `teacher_decision`, `source_operations`) are assigned by the wrap step after application. `source_operations` is `[]` in the offline planner path. `ProposedChangeDraftBatch`, `ProposedChangeDraft`, and `PlannerDecision` live in `grading_rubric.improve.models` per DR-DAT-01.

**Local grounding.** The `_convert_and_ground()` function validates each LLM draft locally: (1) finding-ID validation — every `source_finding_ids` entry must exist in the assess findings; (2) criterion-path validation — the target path must exist in the rubric tree; (3) operation-type validation — must be one of the 5 canonical types. Drafts that fail any check are silently dropped.

**Three-step application pipeline.** (1) **Conflict resolution** — defined for `REMOVE_NODE` supersession but is a **no-op in v1.0** because the planner never emits `REMOVE_NODE` drafts. (2) **Canonical-order sort** — `REPLACE_FIELD → UPDATE_POINTS → REORDER_NODES → ADD_NODE → REMOVE_NODE`; within the same operation type and target field, planner emission order is preserved (critical because the planner accumulates edits — each draft's `after` includes prior edits to the same field). (3) **Apply + wrap** — walks the sorted drafts, applies `REPLACE_FIELD` operations (walks the rubric tree to the target criterion and sets the field) and `ADD_NODE` operations (inserts a new criterion or level as a child of the specified parent path), wraps each into a final `ProposedChange` with `application_status = APPLIED` or `NOT_APPLIED`.

**Inside the modify-existing path — call shape.**

```
   Inputs: rubric, findings, teaching_material (optional),
           simulation_summary, settings

                              │
                              ▼
   ┌─────────────────────────────────────────────────────┐
   │  PLANNER call  (1 LLM call)                        │
   │     gateway.measure(                                │
   │       prompt_id = "propose_planner",                │
   │       schema    = LlmPlannerOutput,                 │
   │     )                                               │
   │  → LlmPlannerOutput → _convert_and_ground()        │
   │    → ProposedChangeDraftBatch                       │
   └─────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌─────────────────────────────────────────────────────┐
   │  APPLICATION  (three-step, fully deterministic)     │
   │  1. Conflict resolution  (no-op in v1.0)           │
   │  2. Canonical-order sort                            │
   │  3. Apply REPLACE_FIELD / ADD_NODE + wrap           │
   │     source_operations = []                          │
   └─────────────────────────────────────────────────────┘
                              │
                              ▼
   Outputs (ProposeOutputs):
     • improved_rubric:    Rubric
     • proposed_changes:   list[ProposedChange]
     • findings:           list[AssessmentFinding]  (pass-through)
     • assessed:           AssessOutputs  (full upstream context)
```

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-IM-01** | Must | The `propose` sub-package exposes a single `Stage`-protocol callable `propose(stage_inputs: ProposeInputs, settings, audit_emitter) -> ProposeOutputs`. `ProposeInputs` carries the original `Rubric` (which may have `criteria == []` for the SR-IN-05 from-scratch case), the `findings: list[AssessmentFinding]` produced by assess, the `evidence_profile: EvidenceProfile` propagated from assess, and the optional `teaching_material: ParsedTeachingMaterial`. `ProposeOutputs` carries the `improved_rubric: Rubric`, the `proposed_changes: list[ProposedChange]` (§ 4.6), the `explanation: Explanation` (§ 4.7), and the `evidence_profile: EvidenceProfile` propagated **strictly unchanged** from input — propose makes no refinements to it (whether the grounding pass ran is surfaced via `Explanation.summary` and `ConfidenceIndicator.rationale`, never on `EvidenceProfile`). The stage is hermetic (DR-ARC-03): no global state, every LLM call goes through `gateway.measure`. | SR-IM-01, SR-IM-02, § 2.2, DR-ARC-03 |
| **DR-IM-02** | Must | The propose stage **classifies** each invocation into one of three internal paths before doing any LLM work: (a) **generate-from-scratch** when `findings` matches the DR-AS-15 sentinel pattern (exactly one finding, `criterion = APPLICABILITY`, severity `HIGH`, `target = None`, `source_operations = []`, observation naming the empty-rubric reason); (b) **modify-existing** when `findings` is non-trivial and the rubric is non-empty; (c) **empty-improvement** when the planner emits zero changes from a non-trivial findings list, or when `findings` is structurally empty. Every invocation produces a valid `ProposeOutputs` regardless of which path runs — the three paths are output-shape-equivalent. | SR-IM-01, SR-IM-06, SR-IN-05, DR-AS-15 |
| **DR-IM-03** | Must | The **modify-existing path** is implemented by a single `gateway.measure` call (`prompt_id = "propose/plan_changes"`, schema = `ProposedChangeDraftBatch`) that takes the original rubric and the findings list and returns a `ProposedChangeDraftBatch`. The schema is a closed-enum decision discriminator `decision: PlannerDecision` (one of `CHANGES_PROPOSED` / `NO_CHANGES_NEEDED` / `PLANNER_FAILURE`) plus a list of `ProposedChangeDraft` records. A `ProposedChangeDraft` carries **only the LLM-owned fields**: `operation` (the § 4.6 discriminator), the operation-specific payload (`target` / `before` / `after` / `parent_path` / `node` / etc. per the § 4.6 variant), `primary_criterion`, `source_findings` (back-references to the finding ids the planner was shown), `rationale` (mandatory, human-readable), and a planner-side `confidence`. It deliberately does **not** carry `id`, `application_status`, `teacher_decision`, or `source_operations` — those are **system-owned** and assigned by the propose stage after grounding and application (DR-IM-07). The planner is shown the `ProposedChangeDraft` schema as a JSON schema and produces validated records directly. `ProposedChangeDraftBatch` lives in the propose stage's stage-local model module per the DR-DAT-01 stage-local-shape rule and is **not** exported through `grading_rubric.models`. The downstream wrap into final `ProposedChange` happens in DR-IM-07. | SR-IM-01, SR-IM-03, SR-IM-05, § 4.6, DR-DAT-01 |
| **DR-IM-04** | Must | The **generate-from-scratch path** is implemented by a single `gateway.measure` call (`prompt_id = "propose/generate_from_scratch"`, schema = `GeneratedRubricDraft`) that takes the exam question, the optional teaching material, and the optional grading-intentions text (the SR-IN-05 `INLINE_TEXT` source) and returns a structured rubric draft. `GeneratedRubricDraft` is shaped as a list of `GeneratedCriterionEntry` records, each carrying the `RubricCriterion` payload **and a per-criterion `rationale: str`** the LLM produces in the same call (one or two sentences, teacher-readable, justifying why this criterion belongs in the rubric). The propose stage then translates the draft into a sequence of `ProposedChangeDraft` records (DR-IM-03) of `operation = ADD_NODE` — one per top-level criterion entry, with each criterion's levels packed into the `node` payload per § 4.6 and the entry's `rationale` copied verbatim onto the draft's `rationale` field — against the empty starting rubric. Every translated draft carries a single sentinel `source_findings = [<from-scratch finding id>]` linking back to the DR-AS-15 finding that triggered the path. The downstream wrap step (DR-IM-07) assigns `source_operations` on each **final `ProposedChange`** (never on the draft itself; drafts are LLM-owned per DR-IM-03) with the **operation id of the generator gateway call** that produced the underlying `GeneratedRubricDraft` — even though the final changes are materialised by Python translation rather than directly by the LLM, the audit join is to the generator call, not to a non-existent per-change LLM call. The per-criterion `rationale` produced by the generator is what discharges DR-IM-09 on this path (where there is no planner): every final change still carries a teacher-readable rationale, but the rationale's LLM-side origin is the generator call rather than the planner call. `GeneratedRubricDraft` and `GeneratedCriterionEntry` live in the propose stage's stage-local model module per DR-DAT-01. | SR-IM-01, SR-IM-02, SR-IN-05, SR-AS-04, DR-IM-09, DR-DAT-01 |
| **DR-IM-05** | Must | The **empty-improvement path** is taken when the planner of DR-IM-03 returns `decision = NO_CHANGES_NEEDED`, or when the input `findings` list is structurally empty. On this path: `improved_rubric` is set to the original rubric unchanged; `proposed_changes` is the empty list `[]`. The explanation has two sub-cases — both honour the SR-IM-06 surface: **(a) trivially empty** (input `findings == []`): every `CriterionSection.finding_refs` is empty per the DR-IM-08 build rule; every `CriterionSection.unaddressed_finding_refs` is empty; `explanation.summary` is a teacher-readable sentence explicitly stating that no issues were found across the three quality criteria. **(b) non-actionable** (input `findings` non-empty but planner returned `NO_CHANGES_NEEDED`): every assess finding is bucketed into the matching `CriterionSection.finding_refs` per DR-IM-08 *and* mirrored into `CriterionSection.unaddressed_finding_refs` (every finding the planner could have acted on but did not); `explanation.summary` is a teacher-readable sentence explicitly stating that issues were noted but no changes were proposed (the planner judged none warranted), naming the three quality criteria. The two sub-cases are distinguished by the `summary` text and by whether `unaddressed_finding_refs` is populated. The narrative call (DR-IM-08) still runs on this path. The third planner outcome — `decision = PLANNER_FAILURE` — is **not** the empty-improvement path; see DR-IM-14. | SR-IM-06, § 4.7 |
| **DR-IM-06** | Should | The **grounding pass** runs after Step 1 (any of the three paths) whenever `teaching_material` is present in `ProposeInputs`. It takes the `ProposedChangeDraft` records produced by Step 1 and is implemented by a single `gateway.measure` call (`prompt_id = "propose/grounding_check"`, schema = `GroundingCheckBatch`) that returns one verdict per draft: `CONSISTENT` (the draft proceeds to the conflict-resolution + application pipeline of DR-IM-07 unchanged), `CONTRADICTS` (the draft is **dropped from the applied set** but is **still wrapped into a `NOT_APPLIED` final `ProposedChange`** by the wrap step of DR-IM-07 so the deliverable shows the teacher *what was proposed and why it did not land*; the contradiction quote is recorded both in the matching `CriterionSection.narrative` and on the dropped change's `confidence.rationale`), or `AMBIGUOUS` (the draft proceeds to application unchanged, but its planner-side `confidence` is downgraded and the grounding outcome is recorded verbatim in `confidence.rationale`). **The grounding pass does not directly populate `unaddressed_finding_refs`** — that field is computed entirely by DR-IM-08 after application has run, so a finding whose grounding-dropped draft was one of several drafts addressing it is not over-marked as unaddressed. When `teaching_material` is absent the grounding pass is skipped entirely. The fact that grounding was performed (or skipped) is **not** recorded on `EvidenceProfile` (which is propagated unchanged per DR-IM-01) — it surfaces in `Explanation.summary` (one teacher-readable sentence naming whether the rubric was cross-checked against teaching material) and, for the `AMBIGUOUS` case, on each affected change's `confidence.rationale`. | SR-IM-04, § 4.7 |
| **DR-IM-07** | Must | The **application step** is a **three-step pipeline** — conflict resolution → canonical-order application → wrap — that turns the post-grounding draft set into the `improved_rubric` and the final `list[ProposedChange]`. (1) **Conflict resolution pre-pass.** The propose stage walks the post-grounding draft set (CONSISTENT and AMBIGUOUS drafts; CONTRADICTS drafts have already been removed from the applied set by DR-IM-06 but are still tracked for wrapping in step 3) and computes a **supersession map** under a single rule: *a draft Y is **superseded** by a draft X iff X is a `REMOVE_NODE` whose removal target — the criterion or level identified by `criterion_path` plus optional `level_id` — is an ancestor of, or equal to, the rubric node Y operates on (Y's `target` for `REPLACE_FIELD` / `UPDATE_POINTS`, Y's `parent_path` for `ADD_NODE` / `REORDER_NODES`, or Y's removal path for another `REMOVE_NODE`)*. Superseded drafts are removed from the set that flows into `apply_changes` and wrapped in step 3 as `NOT_APPLIED` with a one-line rationale-suffix `"superseded by REMOVE_NODE on ancestor path <X.target>"`. The supersession rule is one-way: only `REMOVE_NODE` supersedes others; `REMOVE_NODE` itself is superseded only by another `REMOVE_NODE` on a strict ancestor path (in which case the deeper `REMOVE_NODE` is the redundant one and is itself superseded). The pre-pass is what guarantees the § 4.6 invariant *every change with `application_status = APPLIED` is reflected in `improved_rubric`*: under a naive framing where `[REMOVE_NODE(X), REPLACE_FIELD(X.description)]` would apply the `REPLACE_FIELD` in canonical order before the `REMOVE_NODE` and the `REPLACE_FIELD` would be nominally APPLIED even though its target was gone from the final rubric, the pre-pass instead marks the `REPLACE_FIELD` as `NOT_APPLIED` with the supersession reason and only the `REMOVE_NODE` claims to be reflected in the rubric — which it is. (2) **Canonical-order application.** `improved_rubric = apply_changes(rubric, non_superseded_drafts)` as a pure function — the original `Rubric` instance is never mutated and `apply_changes` returns a fresh `Rubric` value. Application proceeds in a **canonical operation order** the propose stage enforces regardless of the order the planner emitted: `REPLACE_FIELD → UPDATE_POINTS → REORDER_NODES → ADD_NODE → REMOVE_NODE`. Within each operation kind, ties are broken by a **deterministic content-based sort key** computed from each draft's payload: canonical-JSON of `(criterion_path, level_id_or_None, field_or_None)` for `REPLACE_FIELD` / `UPDATE_POINTS` / `REMOVE_NODE`; canonical-JSON of `(parent_path, insert_index, node_kind, node_id)` for `ADD_NODE`; canonical-JSON of `(parent_path, node_kind)` for `REORDER_NODES`. The sort key is a pure function of the draft's content — no planner emission index, no timestamp — so two runs against the same input set produce the same application order regardless of how the LLM happened to order its tool output. (3) **Wrap step.** Each post-grounding draft (whether it landed cleanly through `apply_changes`, was superseded by a `REMOVE_NODE` in step 1, was dropped by grounding as `CONTRADICTS` in DR-IM-06, or had its target vanish during canonical-order application in step 2) is wrapped into a final `ProposedChange` by the propose stage, which assigns the system-owned fields the planner is not allowed to touch: a fresh `id: ChangeId` (DR-IM-11); `application_status` (`APPLIED` for drafts that landed cleanly through step 2, `NOT_APPLIED` for the three other categories — superseded, grounding-dropped, target-gone — with a one-line reason suffix appended to `rationale`); `teacher_decision = None` (the approval gate fills it later); and `source_operations` (DR-IM-13). The system-owned fields are never assigned by the planner. The deliverable's `proposed_changes` list therefore preserves the full *what was proposed and why it did or did not land* trail, while the `improved_rubric` shape itself is determined entirely by the APPLIED subset. | SR-IM-01, § 4.6 |
| **DR-IM-08** | Must | The **explanation assembly step** builds the `Explanation` (§ 4.7) by: (1) creating one `CriterionSection` per `QualityCriterion`, populating `finding_refs` from the assess findings (bucketed by each finding's own `criterion`), `change_refs` from the **APPLIED** changes (bucketed by each change's `primary_criterion`; `NOT_APPLIED` changes still appear in `proposed_changes` for the audit trail but do not appear in `change_refs` because the section is the *what landed* view), and `unaddressed_finding_refs` from the **post-application** computation: a finding `f` is unaddressed iff **no `ProposedChange` with `application_status = APPLIED` references `f` via `source_findings`**; the test runs after the wrap step of DR-IM-07 has assigned `application_status` to every change, so a finding whose only proposed remediation was a draft dropped by grounding *and* whose other drafts all also failed becomes unaddressed, but a finding that has at least one APPLIED change addressing it does not. The grounding pass (DR-IM-06) does not directly populate `unaddressed_finding_refs` — it just decides which drafts proceed to application; the *unaddressed* status is decided here, after application has run, so the over-marking failure mode (a finding with multiple drafts where only one is grounding-dropped) is structurally impossible. (2) invoking a single `gateway.measure` call (`prompt_id = "propose/criterion_narratives"`, schema = `ExplanationDraft`) that returns the `narrative` for each section and the run-level `summary`; the prompt is fed the per-section `finding_refs`, `change_refs`, `unaddressed_finding_refs`, *and* the contradiction quotes from any grounding-dropped drafts in that section so the narrative can mention them in plain words. (3) optionally identifying `CrossCuttingGroup`s when several APPLIED changes from different `primary_criterion` buckets share a theme. The § 4.7 invariants must hold on the returned `Explanation`: three sections always present; every `CrossCuttingGroup` ref appears in exactly one `CriterionSection`; the empty case has the SR-IM-06 sentence in `summary`. | SR-IM-03, SR-OUT-03, § 4.7 |
| **DR-IM-09** | Must | Every final `ProposedChange` produced by the modify-existing or generate-from-scratch path has a non-empty `rationale: str` field (the § 4.6 `_ProposedChangeBase` already requires it; this DR locks the *content* rule). The rationale is **produced by an LLM call**, never synthesised after the fact: on the **modify-existing** path it comes from the planner — DR-IM-03's `ProposedChangeDraftBatch` schema marks `rationale` as required on every `ProposedChangeDraft` and the planner's `gateway.measure` call validates it before returning; on the **generate-from-scratch** path it comes from the generator — DR-IM-04's `GeneratedRubricDraft` schema marks `rationale` as required on every `GeneratedCriterionEntry` and the generator's `gateway.measure` call validates it before returning, and the translation step copies the entry's rationale verbatim onto the corresponding `ProposedChangeDraft.rationale`. In both cases the rationale survives the wrap step (DR-IM-07) onto the final `ProposedChange.rationale` unchanged, except for an optional one-line *NOT_APPLIED* reason suffix appended by the wrap step itself when the change ends up in one of the three NOT_APPLIED categories (superseded by `REMOVE_NODE`, dropped by grounding as `CONTRADICTS`, or target-gone after canonical-order application). The rationale must be teacher-readable (no method names, no model names, no token counts), at most ~3 sentences, and must paraphrase or quote the originating finding's `observation` field rather than referring to it by id (or, on the from-scratch path where there is no real originating finding, must justify why the criterion belongs in the rubric in plain words). The machine-readable trace lives separately in `source_findings: list[FindingId]` (also populated by the planner on modify-existing, set to a single sentinel reference per DR-IM-04 on generate-from-scratch). | SR-IM-03, SR-IM-05, § 4.6, DR-IM-03, DR-IM-04 |
| **DR-IM-10** | Must | The propose stage is **idempotent in its declared inputs**: same `ProposeInputs` + same `Settings` + same model pin + same prompt content hashes → same `ProposeOutputs`, modulo the LLM non-determinism explicitly disclaimed in § 3.9. *Same* for outputs means: the same multiset of `(operation, target, primary_criterion, application_status)` final-change tuples, the same `improved_rubric` structure (criterion ids and topology), and the same `explanation.by_criterion` keys, modulo cosmetic rephrasing in the `rationale` and `narrative` text fields. The honest claim rests on **two structural ingredients owned by DR-IM-07**: the **conflict resolution pre-pass**, which is a pure function of the draft set and yields the same supersession map regardless of LLM emission order; and the **deterministic content-based tie-break** within each canonical operation kind, which sorts drafts by canonical-JSON of their target/parent path (not by planner emission index). A naive framing where within-kind ordering followed planner emission order would be a hidden dependency on LLM emission stability and would make the determinism claim contingent on a property the LLM does not actually guarantee; the content-based sort removes that dependency. This DR is the propose-side counterpart to DR-AS-12 and is what makes the SR-AS-09 re-measurement loop reconstructable. | § 2.2, § 3.9, SR-AS-09, DR-IM-07 |
| **DR-IM-11** | Should | A **re-measurement run** (SR-AS-09 / UR-08) invokes a fresh `propose` call against an updated rubric and a fresh `findings` list from the new assess pass. The propose stage does **not** carry changes forward across iterations; each iteration's `proposed_changes` are computed against the current iteration's rubric and findings. Change ids (`ChangeId`) are **fresh per iteration** — the propose stage does not attempt to identify "the same change" across iterations. The `iteration` linkage between rounds is expressed at the assess level (DR-AS-13's `finding.iteration` field) and at the deliverable level (`ExplainedRubricFile.previous_quality_scores`, § 4.9) — the propose stage stays purely functional in (rubric_n, findings_n). `Settings.max_iterations` is enforced by the **caller** (the orchestrator on Path A; the Validance workflow gate on Path B), never by `propose` itself. | SR-AS-09, UR-08, § 4.9 |
| **DR-IM-12** | Must | The propose stage emits exactly the structured audit events the gateway emits per `gateway.measure` call (DR-LLM-08, DR-OBS-01) plus its own `stage.start` / `stage.end` envelope (DR-OBS-03). It does **not** emit per-change events of its own — the gateway operation events plus the `source_operations` link on each `ProposedChange` (DR-IM-13) carry the full provenance story. `propose` is a *coordinator* of LLM calls, not a producer of new event kinds. | DR-OBS-01, DR-OBS-03, DR-LLM-08 |
| **DR-IM-13** | Must | Every final `ProposedChange` produced by any path carries a `source_operations: list[OperationId]` field (added to `_ProposedChangeBase` in § 4.6 in this round, mirroring `AssessmentFinding.source_operations` from DR-AS-10), populated **only** with the ids of `operation` audit events whose `gateway.measure` call **generated, materially transformed, or vetted** the change: the planner call (modify-existing path) or the generator call (generate-from-scratch path) that produced the originating `ProposedChangeDraft`; and the grounding-check call (DR-IM-06) when grounding ran for this change. The narrative call (DR-IM-08) is **not** included — it does not produce or transform the change; its provenance belongs to `Explanation` and lives in the stage audit chain via the `stage.start` / `stage.end` envelope of DR-IM-12. The reviewer can dereference `source_operations` against the audit chain to retrieve the raw LLM responses that produced and vetted each change. | SR-IM-05, § 4.6, § 4.8, DR-DAT-07a |
| **DR-IM-14** | Should | Each `gateway.measure` call inside propose handles **per-call failure** by degrading rather than aborting, **without** introducing fabricated findings (the `Explanation` schema only references finding ids that exist in the assess output — a propose-stage failure cannot synthesise new finding ids on the fly). The four failure modes: **(1) Planner failure** (the planner's gateway call raised, validation rejected the response, or the planner returned `decision = PLANNER_FAILURE`) on the modify-existing path → fall through to a **degraded empty-improvement variant**: `improved_rubric = original_unchanged`, `proposed_changes = []`; assess findings are bucketed into `CriterionSection.finding_refs` and mirrored into `unaddressed_finding_refs` exactly as in the DR-IM-05 (b) sub-case; `Explanation.summary` is a teacher-readable sentence explicitly stating that the change planner could not produce changes for this run and recommending re-running, distinct from the SR-IM-06 *no improvements warranted* sentence. The structured failure record is the failed gateway call's `operation` event (DR-LLM-08), accessible via the audit chain. **(2) Generator failure** on the generate-from-scratch path → returns `improved_rubric = original_empty_rubric`, `proposed_changes = []`, and an `Explanation` whose three `CriterionSection`s carry the DR-AS-15 sentinel finding in both `finding_refs` and `unaddressed_finding_refs`; `summary` states the generator failure in plain language. **(3) Grounding-check failure** → all drafts from the batch are marked `AMBIGUOUS` (kept, but `confidence` downgraded) with a *grounding-skipped due to grounding-call failure* note in each affected change's `confidence.rationale`; the wrap and application step run normally on the `AMBIGUOUS` drafts. **(4) Narrative failure** is the only fatal mode — the explanation is mandatory and there is no degraded shape; the propose stage propagates the `LlmCallFailure` to its caller. None of the four modes ever appends a synthesised finding to `Explanation` — the only finding ids that ever appear in `Explanation` are the ones the assess stage produced. | SR-IM-01, § 4.7 |

**Counts**: 14 DRs (10 Must / 4 Should). No Could in this round — every DR is either fundamental to the stage's contract (Must) or to its operational robustness (Should). The cluster locks the propose stage's three-path classification, the LLM-owned-vs-system-owned ownership boundary between drafts and final changes, the three-step deterministic application pipeline (conflict resolution + canonical order + content-based tie-break + wrap), and the post-application unaddressed-finding rule that makes `Explanation` immune to grounding-pass over-marking.

### 5.6 User interface (DR-UI)

This group is the **thin DR layer** that locks the L4 SPA against the rest of the design. The three screens — *Input*, *Running*, *Review* — are defined by the contracts the SPA must satisfy: the technology stack and isolation invariants, the screen scope and one-way navigation, the state-management discipline (no SPA-side persistence, hermetic per session), the wiring from the *Input* screen to the registered Validance workflow, the *Running* screen polling cadence and label-mapping table, the side-by-side diff component contract against the `ProposedChange` discriminated union of § 4.6, the per-change accept/reject controls and re-run loop wired through Validance's `ApprovalGate`, and the teacher-native language discipline that governs every label, status, and *Why?* affordance content shape. The present group is the deliverable's full UI specification, locking what each screen must satisfy.

The SPA is L4 of the four-layer architecture (§ 2.1, DR-ARC-10) and lives in a separate top-level `frontend/` directory of the deliverable repo. It is a separate deployable, has no L1 Python in its build, no `validance-sdk` dependency (the SDK is Python-only and lives in L3), and no custom HTTP server of its own — its only backend is Validance's REST API, accessed over `fetch`. Every wire shape it consumes is generated from L1's Pydantic models via the `make schemas` codegen path (DR-DAT-03 / DR-DAT-04); the SPA never reaches into L1 internals and never reads raw Validance audit-chain rows (DR-INT-05 owns the boundary). The SPA's role in the V-shape is to give the EPFL reviewer the **full V-model demo experience** end-to-end; the per-stage CLI subcommands (DR-ARC-08) remain the alternative single-stage inspection path for reviewers who prefer to bypass the SPA.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-UI-01** | Must | The L4 SPA lives in a top-level `frontend/` directory (sibling to `grading_rubric/` and `validance/`, **not** a sub-package of either). The technology stack is **Vite + React + TypeScript + shadcn/ui + Tailwind**, locked at decision § 3.3. The SPA has **no** Python in its build, **no** dependency on `validance-sdk` (which is Python and is the L3 boundary per DR-INT-01), and **no** custom HTTP server in the deliverable (the v0.14.0 pivot per § 3.10 / § 3.11 / DR-ARC-10). Its only backend is Validance's REST API, which it reaches via `fetch` to a base URL injected at build time as `VITE_VALIDANCE_BASE_URL`. The SPA does **not** import from `grading_rubric`, does **not** read local files outside its own build artefacts, and shares no process with any L1 task. The wire shapes it consumes (`ExplainedRubricFile`, `ProposedChange`, `Rubric`, `CriterionScore`, `ConfidenceIndicator`) are generated as TypeScript types from L1's Pydantic models via the `make schemas` + TS-codegen path of DR-DAT-03 / DR-DAT-04 and committed under `frontend/src/types/`; the SPA never hand-writes these shapes. | § 2.1, § 3.3, § 3.10, SR-UI-01, DR-ARC-10, DR-INT-01, DR-DAT-03, DR-DAT-04 |
| **DR-UI-02** | Must | Screen scope: the SPA exposes **exactly three screens** — *Input*, *Running*, *Review* — and the navigation between them is **one-way**: Input → Running → Review, with the *× (close)* affordance on the Review screen returning to a fresh empty Input screen and discarding the current `runId`. There is no router with deep links, no nested routes, no modal stack beyond the *Why?* expand-in-place panel of DR-UI-08, and no additional screens. The three screens are realized as three React components in `frontend/src/screens/{Input,Running,Review}/` and the top-level `App.tsx` holds the screen-state machine (a closed enum `"input" \| "running" \| "review"`). | SR-UI-01, SR-UI-02, SR-UI-07 |
| **DR-UI-03** | Must | State management discipline: **TanStack Query** is the only data-fetching layer in the SPA. The SPA holds **no persistent state** of its own — no `localStorage`, no `sessionStorage`, no `IndexedDB`, no service worker, no application-level cache directory. The only in-memory state is (a) the current screen enum, (b) the current Validance `runId`, (c) the in-flight TanStack Query cache (which is cleared by closing the run and which TanStack Query bounds with its standard LRU). One run is one session is one `runId`; closing the browser tab discards everything. This is the SPA-side restatement of the *Hermetic per session* design principle and of the no-application-cache rule of DR-PER-01: just as L1 has no application-level cache, L4 has no session persistence. The single source of truth on the wire is Validance's REST API; the SPA is a thin renderer over polled state. | § 3.8, SR-UI-01, DR-PER-01 |
| **DR-UI-04** | Must | Input → workflow trigger: the *Input* screen exposes exactly **four input fields** matching the four `InputSource` roles of `InputProvenance` (§ 4.4) — `EXAM_QUESTION`, `TEACHING_MATERIAL`, `RUBRIC_INPUT`, `STUDENT_COPY`. Each field is visually marked **required** or **optional** in its label: only `EXAM_QUESTION` is required (matching SR-IN-02), the other three are optional. The `RUBRIC_INPUT` field accepts both **file upload** and **inline pasted text** as a single dual-mode dropzone, mapping to the `INLINE_TEXT` source format of the `InputSource` discriminated union (DR-IO-01) and realizing SR-IN-05's *paste a sentence of intent* path. The single action control is the **[ Build my rubric ]** button (SR-UI-04); it is disabled until `EXAM_QUESTION` is provided and is the only submission affordance on the screen. On submit, the SPA uploads the inputs to Validance and triggers the registered `grading_rubric.assess_and_improve` workflow (DR-INT-02) via Validance's standard run-creation REST endpoint; the returned `runId` is held in `App.tsx` state for the lifetime of the session and the screen transitions to *Running*. The SPA does **not** call any L1 CLI directly and does **not** invoke any pipeline stage by name — the only thing it knows is the registered workflow id. | SR-UI-02, SR-UI-03, SR-UI-04, SR-IN-01, SR-IN-02, SR-IN-04, SR-IN-05, SR-IN-06, § 4.4, DR-IO-07, DR-INT-02 |
| **DR-UI-05** | Must | Running screen progress signal: the *Running* screen polls Validance's REST API for the workflow run state with **TanStack Query** at a `refetchInterval` of **2000 ms** (`GET /api/runs/{runId}/state`). This is the same polling cadence locked by DR-PER-07 and DR-INT-06; DR-UI-05 is the SPA-side realization of the SR-PRF-02 *visible progress signal* (Must) and of SR-UI-05 (Should). Polling **stops** as soon as the workflow advances to a terminal state (`completed` / `failed` / `cancelled`) or to the `approval_pending` state of the `ApprovalGate` (DR-INT-06), at which point the SPA fetches the proposal payload via `GET /api/runs/{runId}/proposal` and transitions to *Review*. The mapping from Validance task names to teacher-facing step labels is a **single mapping table** (six entries — `ingest`, `parse_inputs`, `assess`, `propose`, `score`, `render`) co-located in `frontend/src/screens/Running/labels.ts`, and is the **only** place internal stage names appear in the SPA — the discipline of DR-UI-08 (teacher-native language) is enforced by funnelling every status string through this table. The SPA does **not** receive webhooks (a browser tab cannot host inbound webhooks); polling owns the cadence and Validance's REST API owns the truth. | SR-UI-05, SR-PRF-02, DR-PER-07, DR-INT-06 |
| **DR-UI-06** | Must | Side-by-side rubric diff and suggested changes list: the *Review* screen renders the original and improved rubric **side by side** from `ExplainedRubricFile.original_rubric` and `ExplainedRubricFile.improved_rubric` (§ 4.9). The diff highlighting is **driven by the `ProposedChange` discriminated union** of § 4.6 — `REPLACE_FIELD` highlights the changed field span on both columns, `UPDATE_POINTS` highlights the points value, `ADD_NODE` paints the new node green on the right column with no counterpart on the left, `REMOVE_NODE` strikes through the removed node on the left column with no counterpart on the right, and `REORDER_NODES` paints reorder arrows on both columns. The diff renderer is a **pure React component** with no internal state — it reads `ExplainedRubricFile` once on mount and renders. Below the side-by-side view, the **Suggested changes** list surfaces the `proposed_changes: list[ProposedChange]` field; each card shows the `primary_criterion` as a coloured tag, the `rationale` text as the headline, and the per-change `confidence` indicator as filled dots. Each card is keyed by `ProposedChange.id` (the system-owned id assigned by the wrap step of DR-IM-07) and renders without any L1 vocabulary — the criterion tag is rendered through the same teacher-native label table as DR-UI-05. Above the side-by-side view, the **Quality scores** strip surfaces the three headline `CriterionScore` values produced by the score stage (DR-SCR-01 / DR-SCR-02), with confidence indicators rendered as filled dots and *was: …* annotations from `ExplainedRubricFile.previous_quality_scores` shown only when a previous iteration exists. | SR-UI-07, SR-UI-08, SR-IM-03, SR-OUT-01, SR-OUT-02, SR-OUT-03, § 4.6, § 4.9, DR-IM-09, DR-SCR-02 |
| **DR-UI-07** | Should | Per-change accept/reject and re-run loop: each card in the *Suggested changes* list of DR-UI-06 exposes individual **Accept** and **Reject** controls. Each click POSTs the decision to Validance's `ApprovalGate` resolver via the proposal-payload mapping of DR-INT-04 (one POST per decision, no batching), which sets `ProposedChange.teacher_decision` on the canonical L1 record and is the sole channel for that field. **Accept-all is the default**: closing the gate (clicking *Download JSON* without explicit decisions) resolves every change as accepted, matching the SR-UI-09 *Could* reading where individual decisions are an enhancement on top of the default-accept path. The **[ Re-assess after my edits ]** button starts a **fresh** `assess_and_improve` workflow run using the current improved rubric as the new starting rubric input (a new `runId`, a new pass through the full `ingest → parse_inputs → assess → propose → approve → score → render` pipeline) and is the SPA-side realization of SR-UI-10 and the SR-AS-09 re-measurement loop. The button is **disabled** once `Settings.max_iterations` (default `3`, the safety bound of DR-AS-12 / DR-IM-11 / DR-INT-06) has been reached, with a tooltip naming the bound; the teacher never sees iteration counters in the screen chrome, only the disabled state. The **[ Download JSON ]** button realizes UR-09 / SR-OUT-05: the downloaded file is the `ExplainedRubricFile` reflecting the teacher's current acceptance state, served by Validance's REST API as a standard browser blob — there is no SPA-side regeneration of the deliverable. | SR-UI-09, SR-UI-10, SR-OUT-05, SR-AS-09, UR-07, UR-08, UR-09, DR-INT-04, DR-INT-06, DR-AS-12, DR-IM-11 |
| **DR-UI-08** | Should | Teacher-native language and *Why?* affordance content shape: every label, control, status message, error message, and confidence rendering surfaced in the SPA uses **teacher-native language** as defined in `requirements.md` § 2 *Glossary* and **never** exposes pipeline, model, prompt, operation-id, or hash vocabulary (SR-UI-06). The label-mapping table of DR-UI-05 is the **only** allowed translation surface — internal stage names, model identifiers, and operation kinds are funnelled through it before they reach the DOM. The **[ Why? ▾ ]** affordance on each suggested change expands an in-place panel containing **exactly three pieces of information** (no more, no less): (a) the originating finding(s) **paraphrased** — taken from `Explanation.by_criterion[*].findings[*].rationale`, **never** the finding `id`; (b) the evidence type — *real student copies* or *synthetic responses*, with the synthetic flag taken from `EvidenceProfile.synthetic_responses_used` (§ 4.4) and rendered prominently when set; (c) the per-finding confidence rationale text from the `ConfidenceIndicator` envelope (§ 4.5). The *Why?* panel is the SPA's only drilldown surface; there is no operation-detail browser, no audit-chain viewer in the SPA proper, and no debug pane. SR-OBS-03 (*audit bundle retrievable from the user interface*) is realized by a single quiet **View audit bundle** link on the Review screen that opens the harvested `AuditBundle` JSON in a new browser tab via `GET /api/runs/{runId}/audit_bundle` (DR-INT-05); this is the only place a reviewer can drill below the *Why?* surface, and it is intentionally outside the teacher's primary path. | SR-UI-06, SR-UI-08, SR-AS-08, SR-OBS-03, § 4.4, § 4.5, DR-INT-05 |

**Rationale.** This group is intentionally **thin** because the cross-cutting machinery (polling, approval gate, audit-bundle endpoint, schema codegen) already lives in DR-INT and DR-DAT. What DR-UI adds is the **boundary-locking layer**: the technology stack and isolation invariants of DR-UI-01, the screen scope and one-way navigation of DR-UI-02, the no-persistence discipline of DR-UI-03, the four-field-to-`InputSource`-role mapping of DR-UI-04, the polling cadence and label-mapping-table of DR-UI-05, the diff-driven-by-`ProposedChange`-union contract of DR-UI-06, the accept/reject + re-run wiring of DR-UI-07, and the teacher-native + *Why?* content shape of DR-UI-08. Together they make the SPA a **renderer over the L1 model surface** rather than a parallel implementation: every wire shape comes from § 4 via codegen, every backend call goes through Validance, and every internal name is funnelled through one mapping table before it reaches the teacher. A reviewer auditing the L4 surface can read this group end-to-end and know exactly what the SPA is allowed to do, what it is forbidden from doing, and where every screen element lands in the L1 / L3 contract.

**Counts: 8 DRs (5 Must / 3 Should). Coverage: SR-UI-01 through SR-UI-10 all covered; SR-PRF-02 / SR-OBS-03 picked up at the SPA-side realization layer.**

### 5.7 Input parsing and OCR (DR-IO)

Defines how exam questions, teaching material, starting rubrics, and student copies are loaded — whether they arrive as files or as inline text — and turned into the structured text the assessment stage expects. Includes OCR for handwritten student copies (decision § 3.5), inline-text handling for the SR-IN-05 *pasted-text starting rubric* case, partial-failure handling per SR-IN-08, and a **role-aware** no-text-PDF policy that does **not** assume every textless PDF is a handwritten student copy. Two L1 stages live here: `ingest` (input collection, role tagging, existence checks, content hashing, initial `EvidenceProfile` and `InputProvenance` construction) and `parse_inputs` (per-input format detection, structured-text extraction, OCR delegation for handwritten student copies, partial-failure aggregation). Both stages are realized inside the `parsers` sub-package (DR-ARC-01) and are exposed as the `ingest` and `parse-inputs` CLI subcommands (DR-ARC-08).

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-IO-01** | Must | The `parsers` sub-package exposes one parser entry point per supported format, each returning the same `ParsedDocument` Pydantic model: `text: str` (the extracted plain text), `sections: list[DocumentSection]` (preserved structural tags — markdown headings, PDF page numbers, docx style runs — as a flat list, never a free-form blob), `source_format: SourceFormat` (closed `StrEnum`: `TXT`, `MD`, `PDF`, `DOCX`, `IMAGE`, `INLINE_TEXT`), `provenance: ParsedDocumentProvenance` (source filename **or inline-text marker**, source content hash per DR-DAT-06 — file-bytes case (a) for files, text-content case (b) for inline text — parser name, parser version, OCR backend identifier when applicable). The Assessment Engine, the Improvement Generator, and the audit producer all consume `ParsedDocument` and **never branch on file format**; format-aware behavior lives only inside `parsers`. | § 3.4, SR-IN-01, SR-IN-03, SR-IN-04, SR-IN-05 |
| **DR-IO-02** | Must | PDF extraction strategy: the parser tries `pypdf` first; if the extracted text fails a defensive degeneracy check (length below `Settings.pdf_min_text_chars` default `40`, or zero sentence-terminating punctuation across the whole document, or a layout-flag set on the page-metadata), it falls back to `pdfplumber` and re-extracts. Both attempts and the reason for the fallback are recorded on `ParsedDocumentProvenance.parser_chain: list[str]` (e.g. `["pypdf:degenerate_text", "pdfplumber:ok"]`) so a reviewer can see which library produced the final text without re-running. **Role-aware no-text-layer policy:** a scanned PDF with no text layer at all (both libraries return empty text) is dispatched on the input's declared role from `ingest` (DR-IO-07): a **student-copy** PDF is routed through the `StudentCopyReader` interface (DR-IO-04) on the assumption it is a handwritten answer; an **exam question** or **teaching material** or **starting rubric** PDF with no text layer is a hard parse failure surfaced as a `ParseError` (DR-IO-06) — for the exam question this aborts the run per SR-IN-02, for teaching material / starting rubric it is a per-file failure that does not abort the run. The role tag, not a filename heuristic, decides routing; this is the only branch in `parsers` that consults the role. | § 3.4, SR-IN-01, SR-IN-02, SR-IN-03 |
| **DR-IO-03** | Must | Per-format parser implementations: `.txt` is read via the standard library with encoding detection through `charset-normalizer` (a hard failure on undetected encoding, not a silent fallback); `.md` is parsed via `markdown-it-py` with the AST collapsed to plain text plus a `sections` list capturing heading levels, list items, and emphasis runs; `.docx` is parsed via `python-docx` exposing styles, headings, and numbered lists as `DocumentSection` entries. **Image-format routing is role-aware** (consistent with DR-IO-02): image inputs (`.png`, `.jpg`, `.tiff`) and scanned PDFs reaching DR-IO-02's no-text-layer branch are routed to the `StudentCopyReader` interface (DR-IO-04) **only when the input's declared role from `ingest` is `student_copy`**. The same image-format inputs in the `exam_question`, `teaching_material`, or `starting_rubric` role are a hard `ParseError` (DR-IO-06) — those inputs are typed-text artefacts the teacher always has in machine-readable form, and silently OCR-ing them would be an inverse-confusion failure mode. The role tag, never a filename or magic-byte heuristic, decides routing. Library versions are pinned in `pyproject.toml` and recorded as `ParsedDocumentProvenance.parser_version`. | § 3.4, SR-IN-01, SR-IN-03, SR-IN-04 |
| **DR-IO-04** | Must | The `parsers` sub-package exposes a `StudentCopyReader` Protocol with one method: `read_pages(file_path: Path, exam_question_text: str \| None) -> list[TranscribedPage]`. The default implementation `ClaudeStudentCopyReader` calls `gateway.measure(prompt_id="ocr_student_copy", inputs=OcrInputs(image_b64=..., exam_question=exam_question_text), output_schema=TranscribedPage, samples=1)` once per page and returns the validated list. Alternative implementations (`AzureDocumentIntelligenceReader`, `TextractReader`, `TrOCRReader`, …) implement the same Protocol and are selected via `Settings.student_copy_ocr_backend` (default `"claude"`). The Protocol is the *sole* surface the rest of the code knows about for handwritten transcription; concrete implementations are private to the `parsers` sub-package. Per DR-ARC-05, only the Claude implementation crosses the gateway; dedicated-OCR backends talk directly to their SDKs. | § 3.5, DR-ARC-05, SR-IN-06, SR-IN-07 |
| **DR-IO-05** | Must | `TranscribedPage` is a Pydantic model: `page_index: int`, `text: str`, `confidence: float` (in `[0.0, 1.0]`), `unreadable_regions: list[UnreadableRegion]` (a closed list of bounding-box markers for regions the backend could not transcribe). When the OCR call returns or the dedicated-OCR backend completes, the `parse_inputs` stage assembles the per-page `TranscribedPage` instances into a single `ParsedDocument` whose `text` is the joined per-page text (with explicit `\n\n--- page N ---\n\n` separators preserved in `sections`) and whose `provenance` records the OCR backend identifier in `ocr_backend: str \| None`. The `confidence` floor for accepting a transcription unconditionally is `Settings.ocr_confidence_floor` (default `0.5`); pages below the floor still produce text but flag the page in `sections` so the Assessment Engine can downweight them via the confidence-indicator chain of § 4.4. | § 3.5, SR-IN-07, SR-AS-08 |
| **DR-IO-06** | Must | Partial-failure handling (SR-IN-08) is realized as **per-input `Result[ParsedDocument, ParseError]`**, not as run-aborting exceptions. The `parse_inputs` stage iterates the **input records** from `ingest` (each one carrying either a file path or an inline-text body, per the role-tagged shape of DR-IO-07), attempts each in turn, and produces a `ParseInputsOutput` with `parsed: list[ParsedDocument]` and `failures: list[ParseError]` (each carrying the source identifier — file path for the file branch, the inline marker for the inline-text branch — the failure stage — encoding, library, OCR — and a human-readable message). The stage **never raises** on a per-input failure; it raises only if **the exam question itself failed to parse** (which collapses SR-IN-02 to a hard precondition: no exam question, no run). The downstream `assess` stage is given both `parsed` and `failures` so the explanation produced by `render` can surface "we could not read these inputs" without inventing assessment findings about missing evidence. | § 3.4, SR-IN-02, SR-IN-08 |
| **DR-IO-07** | Must | The `ingest` stage builds the `InputProvenance` and `EvidenceProfile` of § 4.4 from the input set it receives — whether file paths or inline text — via `--input` (or its `IngestInputs` Pydantic model on Path B). `IngestInputs` carries an explicit `role`-tagged shape: `exam_question: ExamQuestionSource` (`{path: Path}` or `{inline_text: str}`), `teaching_material: list[TeachingMaterialSource]`, `starting_rubric: StartingRubricSource | None` (`{path}` or `{inline_text}` or absent — covering the three SR-IN-05 forms), `student_copies: list[StudentCopySource]`. For each file source `ingest` computes the file-bytes SHA-256 (DR-DAT-06 case (a)); for each inline-text source it computes the text-content SHA-256 of the UTF-8-encoded text (DR-DAT-06 case (b)). Role grouping never relies on filename heuristics — it is always the declared role on the input model. The resulting `EvidenceProfile` carries `exam_question_present=True` (always), `teaching_material_present`, `teaching_material_count`, `teaching_material_hashes`, `starting_rubric_present`, `student_copies_present`, `student_copies_count`, `student_copies_hashes`, with `synthetic_responses_used=False` always at this stage — the field is filled later by `assess` per SR-AS-06, never by `ingest`. `ingest` is **the sole producer** of `InputProvenance` and the sole producer of the initial `EvidenceProfile` shape. | § 4.4, SR-IN-01, SR-IN-04, SR-IN-05, SR-IN-06, SR-IN-09, UR-01, UR-02, UR-03, UR-04 |
| **DR-IO-08** | Should | Library version pinning: `pypdf >= 4.0`, `pdfplumber >= 0.11`, `markdown-it-py >= 3.0`, `python-docx >= 1.1`, `charset-normalizer >= 3.3`. Pins live in `pyproject.toml` and are also recorded on every `ParsedDocumentProvenance.parser_version` field so the audit-view bundle records the exact library version used to extract each input. Bumping any of these is a `pyproject.toml` change reviewed against the same parsing test corpus the unit-test layer uses to lock DR-IO-02 / DR-IO-03 behaviour. | § 3.4 |

### 5.8 Observability (DR-OBS)

The `audit` sub-package is L1's structured-event producer. After the v0.14.0 pivot it is **not** the writer of any cross-run audit chain (DR-ARC-06): it has no in-memory `AuditBundle` accumulation, no on-disk write at end-of-run, no read API, no streaming mode. Its sole job is to expose an `AuditEmitter` interface to stages and the gateway, validate every event against a closed schema, and emit each event as a structured-JSON line to `stderr` (Path A operator inspection + Path B L3 harvester input). The typed `AuditBundle` view of § 4.8 is produced by the L3 harvester (DR-INT-05), not by the `audit` sub-package. The `AuditEmitter` interface itself is locked by DR-ARC-06; this group locks the **wire format** of the events, the **closed event-kind set** they cover, the privacy invariant on `raw_responses`, and a small in-process snapshot helper used by tests.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-OBS-01** | Must | Each event emitted by `audit_emitter` is a single-line structured-JSON record on `stderr` matching the schema committed at `schemas/audit_event.v1.schema.json` (regenerated by `make schemas` per DR-DAT-03): `{ts: ISO-8601 UTC, event: EventKind, run_id: str \| null, stage_id: str \| null, operation_id: str \| null, attempt: int \| null, retry_of: str \| null, status: "success" \| "failed" \| "skipped" \| null, inputs_digest: str \| null, outputs_digest: str \| null, details_kind: OperationKind \| null, details: JsonValue \| null, error: ErrorRecord \| null}`. The closed `EventKind` set is exactly `{"run.start", "stage.start", "operation", "stage.end", "run.end"}` — five kinds, no others. The `OperationKind` set is the closed enum from § 4.8 (`llm_call`, `ocr_call`, `ml_inference`, `tool_call`, `human_decision`, `agent_step`, `deterministic`). For events with `event == "operation"`, the `details` field carries the variant of `OperationDetails` matching `details_kind`, populated per DR-LLM-08 (for `llm_call`) or by the corresponding stage callable (for the other kinds). **Producer rule:** `run.start` and `run.end` events are emitted **only** by the in-process orchestrator of DR-ARC-04 (which always knows the full pipeline context); per-stage CLI invocations (`grading-rubric-cli <stage>`) and Validance task wrappers emit only `stage.start`, `operation`, and `stage.end` events for the stage they run, never the surrounding `run.*` envelope. The harvester (DR-INT-05) joins the per-task streams under Validance's workflow `run_id` and synthesizes the `run.*` envelope itself when materializing the `AuditBundle` view; it does not require an L1 task to have emitted them. This schema is the **L1↔L3 audit contract** (DR-INT-03): the L3 harvester reconstructs the typed `AuditBundle` view by parsing this stream and is the sole consumer that needs to know it exists in production. The same stream is human-readable on `stderr` for operator inspection on Path A. | SR-OBS-01, SR-OBS-02, § 4.8, DR-ARC-06, DR-DAT-03, DR-INT-03, DR-INT-05 |
| **DR-OBS-02** | Must | Privacy boundary: `LlmCallDetails.raw_responses` and any other privacy-sensitive payload (transcribed student text, OCR output of a handwritten copy) **only** appear inside the `details` field of an `event == "operation"` line. They never appear in `event == "stage.start" / "stage.end" / "run.start" / "run.end"` lines, never in any error message bubbled up through `error.message`, and never in any other surface the application exposes (the deliverable `ExplainedRubricFile` of § 4.9, the L4 SPA's index views, etc.). The L3 harvester (DR-INT-05) preserves the same boundary into the harvested `AuditBundle`: detail blocks are loaded only when a reviewer drills into a specific operation (the index/detail split locked by DR-DAT-07a). The `audit` sub-package is the boundary's gatekeeper at the producer side; any code path that could leak transcribed text outside an operation event is a defect. | § 4.8, § 4.9, DR-DAT-07a |
| **DR-OBS-03** | Must | The `audit` sub-package exposes the `AuditEmitter` interface from DR-ARC-06 with these methods: `start_run(run_id, started_at, input_provenance, evidence_profile)` → emits `run.start` (orchestrator-only per DR-OBS-01); `start_stage(stage_id)` → emits `stage.start`; `record_operation(record: OperationRecord)` → emits `operation`; `end_stage(stage_id, status)` → emits `stage.end`; `end_run(status, errors)` → emits `run.end` (orchestrator-only per DR-OBS-01). Every method validates its arguments against the DR-OBS-01 schema before emission and raises `AuditEmitterError` on validation failure (a defect, never a runtime branch). Stages and the gateway depend only on this interface, never on the concrete writer. The thin in-process orchestrator (DR-ARC-04) instantiates one `AuditEmitter` per CLI invocation and injects it into stages, calling `start_run` / `end_run` itself. Per-stage CLI invocations and Validance tasks instantiate an `AuditEmitter` whose `start_run` / `end_run` are no-ops (or raise if called) so the producer-rule of DR-OBS-01 cannot be violated by accident. | DR-ARC-06, DR-INT-05 |
| **DR-OBS-04** | Should | A `audit.snapshot()` debug helper returns the in-memory list of operation events emitted during the current process invocation, used by tests (to assert that a stage emitted the expected events without parsing `stderr`) and by the `--emit-operations` flag of DR-ARC-06 case (a) to write the per-stage operations file on Path A. Not part of the public package surface (DR-ARC-12). | DR-ARC-06, DR-ARC-12 |

### 5.9 Performance, caching, and concurrency (DR-PER)

The caching question is already settled by decision § 3.8: **the application has no application-level cache**. DR-PER therefore does not introduce one. What this group does specify is (a) how concurrent processing of multiple student copies and multi-sample LLM calls is handled while keeping each pipeline stage hermetic, (b) which work units are parallelized and which run sequentially, and (c) the back-pressure and timeout policy that protects the run from a single slow upstream call. Cross-stage scheduling and run cancellation are **not** L1 concerns post-pivot — they are owned by the workflow engine on Path B (Validance terminates a workflow by terminating its tasks) and by the operating system on Path A (a `Ctrl-C` against a single CLI subcommand is the only cancellation surface there).

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-PER-01** | Must | The application has **no application-level cache**: no on-disk cache directory, no in-memory content-hash map, no request deduplication inside the gateway, the parsers, the assess stage, or the orchestrator. Each call to `gateway.measure(...)` issues a fresh model call; each call to a parser entry point opens the file from disk and re-extracts. This is the in-code restatement of § 3.8 and exists here so a reviewer reading `DR-PER` does not have to reach back to § 3.8 to confirm the constraint binds the implementation. Any future cache would be an external orchestrator concern (Validance task content-addressed cache, etc.) and would never be introduced inside the L1 boundary. | § 3.8 |
| **DR-PER-02** | Must | Concurrency primitive: **`concurrent.futures.ThreadPoolExecutor`** for parallel LLM calls in the grader simulation. The gateway uses the synchronous Anthropic SDK client. `run_grader_simulation()` fans out grading and pairwise comparison calls across a thread pool with `max_workers = Settings.assess_llm_concurrency` (default `4`); each worker instantiates its own `Gateway()` to avoid shared mutable state. Stage callables are plain synchronous functions (not `async def`); the CLI invokes them directly. The `_simulation_settings()` override mechanism allows the assess stage to use a different LLM backend or model pin than the rest of the pipeline via `Settings.assess_llm_backend` and `Settings.assess_llm_model_pinned`. | § 2.2, § 3.9, DR-PER-05 |
| **DR-PER-03** | Must | Parallelism boundaries: within `run_grader_simulation()`, two work-units run concurrently via `ThreadPoolExecutor` — (a) **per-response × per-persona grading calls** (4 personas × N responses = 4N calls fanned out in parallel) and (b) **pairwise comparison calls** (one per sampled pair, fanned out after all grading completes). When `assess_llm_concurrency == 1` or a single job exists, the calls run sequentially without a thread pool. Stages themselves run **sequentially** — `assess` waits for `parse_inputs` to finish before it starts — because each stage's outputs feed the next. | § 3.9, SR-PRF-01 |
| **DR-PER-04** | Must | Gateway call-rate bound: a **single semaphore inside the gateway** bounds the number of in-flight LLM calls per process to `Settings.llm_max_concurrency` (default `8`). Every `gateway.measure(...)` call acquires the semaphore for the duration of one underlying SDK call (per sample, per validation-retry attempt). This semaphore is the **only place in L1 that bounds the LLM call rate** — stages do not maintain their own LLM-rate semaphores, the parsers do not bound OCR fan-out separately at the call-rate axis, and the orchestrator does not bound stage parallelism (because stages do not run in parallel — DR-PER-03). The stage-local fan-out semaphores of DR-PER-06 are a *different* axis (in-memory batch-size bound, not call-rate bound) and do not contradict this rule. A reviewer auditing the call-rate surface looks at exactly one place. *v1.0 note: `Settings.llm_max_concurrency` is not yet implemented as a separate setting; v1.0 uses `assess_llm_concurrency` (default 4) as the sole concurrency bound via `ThreadPoolExecutor`.* | § 3.9, SR-PRF-01 |
| **DR-PER-05** | Must | Per-call timeout reuse: every LLM call is bounded by `Settings.llm_call_timeout_seconds` (default `60`) per DR-LLM-07. Per-OCR-page calls are LLM calls and inherit the same bound. Per-file parser calls (`pypdf` extraction, `pdfplumber` extraction, `python-docx` parsing) are bounded by `Settings.parser_call_timeout_seconds` (default `30`); the parser timeout is enforced via `asyncio.wait_for` around the synchronous library call run in a thread via `asyncio.to_thread` (the **single** carve-out to DR-PER-02's "no thread pool" rule, justified because the third-party libraries are synchronous and refusing to use a worker thread there would block the event loop). Timeouts are recorded as `FAILED` operation events with `error.code == "TIMEOUT"` per DR-LLM-07's analogue. *v1.0 note: `Settings.parser_call_timeout_seconds` is deferred to v2; parsers currently run without an explicit timeout.* | § 3.9, DR-LLM-07 |
| **DR-PER-06** | Must | Stage-local memory fan-out bound: `parse_inputs` and `assess` process student copies in chunks of `Settings.student_copy_chunk_size` (default `16`) using a stage-local bounded `asyncio.Semaphore`, so a run with 100 student copies (SR-PRF-01) holds at most 16 `TranscribedPage` lists in memory at any moment. Each chunk's results are folded into the stage's output incrementally, then the chunk is released for garbage collection. **This is a different axis from DR-PER-04** and the two coexist by design: the gateway semaphore is the **call-rate bound** (a process-wide cap on in-flight LLM calls), and the chunk semaphore is the **memory fan-out bound** (a stage-local cap on the number of in-flight per-copy coroutines). The stage-local semaphore never bounds LLM call concurrency — that is exclusively DR-PER-04's job — and the gateway semaphore never bounds in-memory batch size. The two limits compose: the chunk size bounds how many copies are *in flight* in the stage at once, the gateway concurrency bounds how many of their underlying LLM calls run *simultaneously*. *v1.0 note: `Settings.student_copy_chunk_size` is deferred to v2; all copies are processed in a single batch.* | SR-PRF-01 |
| **DR-PER-07** | Must | Progress signal (SR-PRF-02): SR-PRF-02 mandates visible progress for any operation taking more than five seconds; it is *Must* in [`requirements.md`](requirements.md) § 5 and is realized as *Must* here. The L1 surface that satisfies it is the structured-event stream of DR-OBS-01 — `stage.start` and `stage.end` events are emitted at stage boundaries, and `operation` events are emitted as each LLM call, OCR call, or other measurement completes — combined with a **path-specific outer signal** that closes the gap between the maximum per-call duration (`Settings.llm_call_timeout_seconds` default `60`, per DR-LLM-07 / DR-PER-05) and the SR-PRF-02 five-second threshold. **On Path B (Validance + L4 SPA),** the SPA polls Validance's REST API for workflow run state with TanStack Query at a `staleTime` no longer than two seconds; Validance's per-task lifecycle (`pending` → `running` → `completed`) advances independently of L1 event emission, so the SPA renders "stage X — running, 12s elapsed" on every poll regardless of whether L1 has produced an `operation` event yet. This is the polling cadence already locked in DR-INT-06 for the approval-gate path; DR-PER-07 reuses it for the running-task path. **On Path A (direct CLI invocation),** the unit of execution is one stage and the operator runs the CLI in a foreground shell — the `stage.start` event lands on `stderr` immediately on entry, the running process is itself the visible progress signal until the stage completes, and any individual stage that exceeds five seconds without intermediate output is by construction running a single LLM/OCR call whose timeout is bounded by `Settings.llm_call_timeout_seconds`; CLI single-stage inspection is Path A's purpose, and a stalled foreground process is acceptable progress feedback for the operator class on Path A (a developer or reviewer at a terminal, not an end teacher). **SR-PRF-02 is teacher-facing by construction** — it speaks to "the teacher running the application" — and is therefore satisfied by the Path B contract above; Path A is **explicitly out of the SR-PRF-02 teacher-facing interpretation** because no teacher runs single-stage CLI inspection commands. A developer/reviewer at a terminal who needs finer-grained progress on Path A can pipe `stderr` through `jq` and watch the structured-event stream live (the `--emit-operations` flag of DR-OBS-04 makes this trivial); there is no separate L1 progress surface for them. **L1 does not introduce a progress thread, does not emit per-percent progress, and does not register any callback API for progress.** The contract above is the ceiling of L1's progress surface; any finer-grained heartbeat would have to come from a future per-call streaming change to DR-OBS-01 (the closed event-kind set would have to be reopened) and is explicitly out of scope for the v1 deliverable. | SR-PRF-02, DR-OBS-01, DR-INT-06, DR-PER-05 |
| **DR-PER-08** | Should | Cancellation (SR-PRF-03): cross-run cancellation is **not** an L1 concern. On Path A, the unit of execution is one CLI subcommand and the cancellation surface is the OS — `Ctrl-C` raises `KeyboardInterrupt`, which `asyncio.run(...)` translates to `CancelledError` propagated through every awaited stage; on receipt the gateway closes its in-flight HTTP connections via the SDK's async-context-manager semantics and the stage exits non-zero. On Path B, Validance owns workflow termination and per-task termination via its standard task lifecycle; L1 task code receives the orchestrator-signalled termination (typically `SIGTERM`) from the worker and **the process terminates non-zero**. **No custom signal handler is registered**, so default Python `SIGTERM` semantics apply (process termination, *not* automatic translation into `CancelledError`); cleanup is best-effort, in-flight HTTP connections are closed by the OS on process exit, and any partial outputs the stage may have written remain on disk for the orchestrator to garbage-collect. L1 does not implement a "cancel button" of its own and does not need to: both execution surfaces already provide one, and the deliverable's correctness does not depend on graceful cleanup at process termination because every stage's output is written atomically (DR-DAT-08) and either landed in full or did not land at all. | SR-PRF-03, § 3.11 |

### 5.10 Scorer interface (DR-SCR)

The `score` stage re-runs `run_grader_simulation()` against the improved rubric (reusing the response set from assess when available) and calls `scores_from_simulation()` to produce headline `CriterionScore` records — both functions live in `grading_rubric.assess` and are shared with the assess stage. The score stage is the sole producer of the three headline quality scores that the deliverable surfaces.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-SCR-01** | Must | The `score_stage` entry point calls `run_grader_simulation()` + `scores_from_simulation()` (shared with assess), producing `ScoreOutputs` with `quality_scores: list[CriterionScore]` on the improved rubric plus `previous_quality_scores` carried from `AssessOutputs.quality_scores` for before/after comparison. | § 2.4, § 4.5, SR-AS-09 |
| **DR-SCR-02** | Must | The score stage re-runs the shared grader simulation against the improved rubric, reusing the same response set when available, and converts the resulting grade matrix into one `CriterionScore` per quality criterion. Each score uses `QualityMethod.GRADER_SIMULATION` and links back to the simulation operation evidence through `source_operation_id` when available. | § 4.5, § 4.9, DR-LLM-01, DR-LLM-08, SR-AS-01, SR-AS-02, SR-AS-03, SR-OUT-03 |

### 5.11 Deployment, packaging, orchestration (DR-DEP)

Locks the four-layer artefact set the deliverable ships (L1 Python package + CLI, L2 Docker images, L3 Validance integration directory, L4 SPA build) and the make target surface a reviewer uses to install, build, register, and exercise the deliverable. The L3 *content* — directory layout, harvester contract, workflow registration, proposal-payload mapping — is locked separately in § 5.12 *DR-INT*; this group locks only the *packaging and orchestration* concerns. Technology decisions #10 and #11 (§ 3.10 and § 3.11) supply the rationale; this group commits the artefacts.

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-DEP-01** | Must | The deliverable repository ships **four** top-level artefact roots: (a) `grading_rubric/` — L1, the pure Python package with the `Stage`-protocol stages, the `gateway`, the `audit` event producer, and the `cli` console-script entry point (DR-ARC-01, DR-ARC-07, DR-ARC-08); (b) `docker/` — L2, one Dockerfile per L1-derived image, baking the L1 package + the CLI as the entrypoint, with no Validance imports and no host bind-mounts in the production image; (c) `validance/` — L3, the integration directory whose layout is locked by § 5.12 *DR-INT*, the **sole** site that imports `validance-sdk`; (d) `frontend/` — L4, the custom SPA (Vite + React + shadcn + Tailwind, per § 3.3) that talks to Validance's REST API. No other top-level artefact roots are part of the deliverable. | § 3.10, § 3.11, § 5.12 |
| **DR-DEP-02** | Must | L1 is packaged as a standard Python distribution (`pyproject.toml`) with one console-script entry point: `grading-rubric-cli = grading_rubric.cli:main`. The `pyproject.toml` declares **only** the L1 runtime dependencies (`anthropic`, `pydantic`, `pydantic-settings`, file-parsing libraries, etc.) and **does not** depend on `validance-sdk`, `validance-workflow`, or any other orchestration package. A `pip install .` from the repository root produces a working `grading-rubric-cli` that runs every per-stage subcommand without Validance installed. The `pyproject.toml` is the boundary condition that DR-ARC-07 verifies by grep. | § 3.10, DR-ARC-07 |
| **DR-DEP-03** | Must | L2 ships at least one Docker image per stage-image grouping declared by L3 (the L3 directory's image registry decides whether stages share an image or each gets its own). Each image is built from `docker/<image>/Dockerfile`, copies in only the L1 source tree (and its dependencies), installs L1 via `pip install .`, and sets `ENTRYPOINT ["grading-rubric-cli"]` so `docker run <image> <stage> --input … --output …` is the unit of single-stage invocation on Path A (§ 3.11). Images **must** be self-contained — no host bind-mount of L1 source, no `/project` mount, no scripts copied at runtime — which is the pattern locked across the user's other repos for production task images. | § 3.10, § 3.11 |
| **DR-DEP-04** | Must | L4 is a separate buildable: `cd frontend && npm install && npm run build` produces a static SPA bundle that talks to Validance's REST API at the URL specified in `frontend/.env.production` (default: the hosted dev-VM Validance instance). The L4 build does not import any L1 Python code, does not read L1 source files, and never runs in the same process as any L1 task. The wire types the SPA consumes are generated from L1's Pydantic models via the JSON-Schema codegen path of DR-DAT-03 / DR-DAT-04, packaged into `frontend/src/generated/`. | § 3.3, § 3.10, DR-ARC-10 |
| **DR-DEP-05** | Must | A top-level `Makefile` is the single entry-point surface for installing, building, registering, and exercising the deliverable. It exposes exactly the targets: `install` (pip-install L1 in editable mode), `images` (build all L2 Dockerfiles), `register` (run the L3 registration script — `python validance/register.py` — against the Validance instance specified by `VALIDANCE_BASE_URL`), `schemas` (regenerate JSON Schema files plus the front-end TypeScript / zod codegen, per DR-DAT-03 / DR-DAT-04), `build` (build the L4 SPA), `dev` (run the L4 SPA dev server pointing at the hosted Validance instance), and `test` (run the unit / integration test suites that exercise the L1 stages with stub gateway and stub audit emitter). There is **no `make run` target** — there is no custom HTTP server in the deliverable to start (DR-ARC-10); the demo runs through Validance, started once per environment via `make register`. | § 3.10 |
| **DR-DEP-06** | Must | The deliverable supports two demo paths from the same L1 task code: **Path A** — `docker run <image> grading-rubric-cli <stage> --input … --output …` runs one pipeline stage in isolation, against any image built by `make images`, with no Validance involvement; **Path B** — after `make register` against the hosted Validance instance, the L4 SPA (started via `make dev` for local iteration or served from any static host for the demo) calls Validance's REST API to start the `grading_rubric.assess_and_improve` workflow and renders the run, the ApprovalGate-mediated review, and the harvested `AuditBundle` view. The README documents both demo paths and shows the exact commands; the reviewer is expected to know which path they want, not to discover it. | § 3.11, DR-ARC-08, § 5.12 |
| **DR-DEP-07** | Should | A reviewer can clone the repository and reach a runnable Path-A invocation (one CLI subcommand against one Docker image) in under three commands beyond `git clone`: `make install` (or `make images` for the container path), set `ANTHROPIC_API_KEY` in `.env`, and run `grading-rubric-cli <stage> --input … --output …` (or `docker run …` with the same arguments). Path B requires one extra step (`make register` against the hosted Validance instance, with `VALIDANCE_BASE_URL` set in the environment). The README opens with these two snippets verbatim. | § 3.10 |
| **DR-DEP-08** | Should | The repository ships an `.env.example` listing every environment variable the L1 package, the L3 integration script, and the L4 SPA build read — at minimum `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (optional, for the pluggable backend of DR-LLM-09), `LLM_BACKEND` (default `anthropic`), `LLM_MODEL_PINNED`, `VALIDANCE_BASE_URL` (default the hosted dev-VM URL), and the L4 SPA's `VITE_VALIDANCE_BASE_URL`. The committed `.env.example` is the single source of truth for *which* variables exist; the gitignored `.env` is the dev-time convenience, never committed. This is the on-disk realization of the env-only secret discipline locked in § 3.7. | § 3.7 |
| **DR-DEP-09** | Should | The repository's CI runs `make test` (the L1 unit / integration suite — no LLM API calls, no Validance instance), `make schemas` (with the drift check from DR-DAT-03), and a static check enforcing the DR-ARC-07 zero-Validance-imports invariant on the L1 tree. CI does **not** run Path A or Path B end-to-end; the end-to-end demo paths are exercised manually against the hosted dev-VM instance during reviewer assessment. | DR-ARC-07, DR-DAT-03 |

**Rationale.** The four-layer split is the decision; this group ships the artefacts that realize it without smuggling cross-cutting concerns into L1. The Makefile target list is deliberately small — six action targets and one reviewer-facing test target — because every additional target would need to be either an L1 concern (handled by `cli`), an L3 concern (handled by `register.py`), or an L4 concern (handled by the SPA build). The absence of `make run` is the visible consequence of "no custom HTTP server in the deliverable" and is the first thing a reviewer notices that signals where the orchestration layer actually lives.

### 5.12 Validance integration (DR-INT)

Locks the contract that the L3 integration directory (`validance/`) must satisfy: the directory layout, the `validance-sdk`-import boundary, the workflow shape, the proposal-payload mapping for `ProposedChange`, the harvester contract that turns Validance's audit chain into the typed `AuditBundle` view of § 4.8, and the human-in-the-loop binding to `ApprovalGate`. This group is the **sole** place in the design where Validance vocabulary appears in normative DR-table form; everywhere else in § 5 the design is orchestration-agnostic by construction (DR-ARC-07).

| ID | Criticality | Statement | Trace |
|---|---|---|---|
| **DR-INT-01** | Must | The L3 integration lives in a top-level `validance/` directory (sibling to `grading_rubric/`, not a Python sub-package of it) with the layout: `validance/workflow.py` (the `Workflow` and `Task` definitions, one task per pipeline stage), `validance/register.py` (the registration script invoked by `make register`, idempotent against the Validance instance specified by `VALIDANCE_BASE_URL`), `validance/proposals.py` (the proposal-payload mapping for `ProposedChange` — see DR-INT-04), `validance/harvester.py` (the audit-chain harvester — see DR-INT-05), and `validance/__init__.py` (re-exports nothing public; the directory is invoked from CLI scripts, not imported by other code). The `validance/` directory is the **sole** site in the repository that imports `validance-sdk`; this is the boundary DR-ARC-07 verifies by grep. | § 3.11, DR-ARC-07 |
| **DR-INT-02** | Must | `register.py` registers **one** Validance workflow: `grading_rubric.assess_and_improve` — the assessment pipeline, with **one Validance task per L1 pipeline stage**: `ingest` → `parse_inputs` → `assess` → `propose` → `approve` (an `ApprovalGate`, see DR-INT-06) → `score` → `render`. Each L1 stage is wrapped as a Validance task whose execution is `docker run <image> grading-rubric-cli <subcommand> --input … --output …` with the `<image>` from L2 (DR-DEP-03) and the input/output paths declared on the task's `inputs` / `outputs` schema. The Validance workflow definitions do **not** call any L1 Python function in-process; the only L1↔Validance contact surface is the CLI subcommand exit code, the structured `--output` file, and the structured stderr operation events that the harvester consumes. | § 3.11, DR-ARC-08, DR-DEP-06 |
| **DR-INT-03** | Must | Every L1 stage that calls the LLM (per DR-LLM-01) emits its operation events via the `audit_emitter` to `stderr` as structured-JSON lines matching the wire schema locked by DR-OBS-01 (and committed at `schemas/audit_event.v1.schema.json` per DR-DAT-03) when invoked through Validance. The L3 task wrapper captures this stderr stream as part of Validance's standard task-output capture; the harvester (DR-INT-05) joins it with Validance's per-task audit-chain rows to build the typed `AuditBundle` view. No private file format crosses the L1↔L3 boundary; the contract is *structured stderr lines (validated against `audit_event.v1.schema.json`) + Validance's own audit chain*. | SR-OBS-01, § 4.8, DR-ARC-06, DR-OBS-01, DR-DAT-03 |
| **DR-INT-04** | Must | The proposal-payload mapping in `validance/proposals.py` translates the L1 `ProposedChange` discriminated union (§ 4.6) to Validance's `proposal_payload` shape required by `POST /api/proposals`, and the inverse direction translates Validance's approval-event payloads back into the `ProposedChange.teacher_decision` field that the L1 `render` stage reads on its next invocation. The mapping is a pure function (no I/O, no SDK calls) and is unit-tested without a Validance instance. The `proposal_payload` carries enough context (`primary_criterion`, `target` path, the human-readable rationale, and the change kind) for Validance's reviewer UI to render the same view the L4 SPA renders. | § 4.6, § 2.5, SR-OUT-05 |
| **DR-INT-05** | Must | The harvester `validance/harvester.py` exposes a single function `harvest_audit_bundle(run_id: str, validance_client) -> AuditBundle` that reads (a) the per-task captured stderr operation events for every task in the workflow run, (b) the Validance audit-chain rows for the same run via the SDK, (c) the workflow-level start/end timestamps and status, and produces an `AuditBundle` (§ 4.8) whose `operations: list[OperationSummary]` index references per-operation detail blocks loaded from the captured stderr lines, whose `stages: list[StageRecord]` mirrors the workflow's task list, whose `iteration_history` reflects the loop iterations driven by the `ApprovalGate` of DR-INT-06, and whose `input_provenance` is populated from the `ingest` task's input declarations. The harvester is the sole producer of the audit-view bundle on Path B (DR-DAT-07a); it is invoked by Validance's REST API on demand (`GET /api/runs/{run_id}/audit_bundle`) so the L4 SPA never sees raw Validance audit-chain rows. | SR-OBS-01, SR-OBS-03, § 4.8, DR-DAT-07a, DR-ARC-10 |
| **DR-INT-06** | Must | Human-in-the-loop is realized by a Validance `ApprovalGate` task placed between `propose` and `score` in the workflow definition of DR-INT-02. The gate's `proposal_payload` is the list of `ProposedChange` items produced by `propose`, mapped via DR-INT-04. The teacher reviews the changes in the L4 SPA, which **polls** Validance's REST API for the workflow run state (TanStack Query against `GET /api/runs/{run_id}/state`, every ~2s while a gate is open) and renders the proposal payload as soon as the gate becomes pending. The teacher accepts or rejects each change individually, and the SPA `POST`s the decision back through Validance's standard approval-resolution endpoint; either (a) closing the gate lets `score` and `render` run on the accepted set (single-pass run, SR-AS-09 not exercised) or (b) requesting a re-measurement iteration causes Validance to re-enter the `assess` → `propose` → `approve` segment with the updated rubric — capped by `Settings.max_iterations` (default `3`) as a **safety bound**, never as an autonomous convergence loop (§ 2.5). Every iteration of the loop is gated by an explicit teacher decision; the system does not iterate on its own. The polling-not-webhook framing is deliberate: a browser SPA cannot receive inbound webhooks, so the SPA owns the polling cadence and Validance's REST API owns the truth. | § 2.5, UR-07, UR-08, SR-AS-09, SR-UI-09, SR-UI-10, SR-OUT-05 |
| **DR-INT-07** | Must | `register.py` is idempotent: running `make register` twice against the same Validance instance produces no duplicate workflow registrations. The script reads the workflow definition from `validance/workflow.py`, computes the workflow's content hash, and either creates a new registration (first run) or updates the existing one in place (subsequent runs) using Validance SDK's standard registration semantics. The script reads `VALIDANCE_BASE_URL` from the environment and exits non-zero with a clear error message if the variable is unset or the instance is unreachable. | DR-DEP-05 |
| **DR-INT-08** | Should | A different orchestrator (Snakemake, Airflow, Argo, Prefect, plain bash) could wrap L1 by writing its own integration directory analogous to `validance/` — with its own `register` script, its own approval-gate primitive (or a polling loop), its own harvester translating the engine's audit format into the same `AuditBundle` view. The contract that another integration must satisfy is exactly DR-INT-02 (one task per stage, CLI subcommand invocation), DR-INT-03 (structured stderr operation events as the L1↔orchestrator audit contract), DR-INT-04 / DR-INT-06 (HITL via the orchestrator's approval primitive, mapping `ProposedChange` both ways), and DR-INT-05 (a harvester producing the same `AuditBundle` shape). L1 itself remains unchanged. | § 3.11 |
| **DR-INT-09** | Should | The `validance/` directory is exempt from the front-end TypeScript codegen path of DR-DAT-04 — the SPA consumes the audit-view bundle through Validance's REST API, not through any L3 type the harvester defines. The codegen surface is exactly the L1 `models` sub-package; the L3 harvester is an internal producer of that surface, not an extension of it. | § 3.6, DR-DAT-04 |

**Rationale.** This group is what makes the pivot real: every cross-cutting concern that L1 deliberately does not own (audit chain, approvals, retries, backend↔frontend, provenance) is named here as a Validance primitive that L3 wires up. The harvester is the load-bearing piece — it is the sole place where Validance vocabulary meets L1 vocabulary, and it is the contract that any future alternative integration must reproduce. Keeping the contract small (CLI subcommand invocation + structured stderr + a harvester producing one well-known shape) is what keeps the door open for that alternative integration while still letting Validance carry the full demo experience today.

---

## 6. Traceability — System Requirements to Design Requirements

This is the closing trace matrix produced at R7. Every System Requirement of [`requirements.md`](requirements.md) § 5 (46 SRs total) is covered by at least one Design Requirement here, and every Design Requirement traces back to at least one System Requirement — with the single carve-out for the DR-SCR train-button capability documented immediately below the table. The matrix is reverse-derived from the per-DR `Trace` columns of § 5.1 through § 5.12: a DR appears in a row's `Covered by` cell iff its `Trace` column names that SR (directly, or transitively through a § 4 model field that the SR depends on, in which case the relevant § 4 anchor is documented in the DR's own statement). The matrix is intentionally **dense** — most SRs are covered by multiple DRs because the V-shape pyramid widens at the design layer.

| System Requirement | Covered by |
|---|---|
| **SR-IN-01** — exam question accept (text/md/PDF) | DR-IO-01, DR-IO-02, DR-IO-03, DR-IO-07, DR-UI-04 |
| **SR-IN-02** — refuse on missing exam question | DR-IO-02, DR-IO-06, DR-UI-04 |
| **SR-IN-03** — extract structured text from exam question | DR-IO-01, DR-IO-02, DR-IO-03 |
| **SR-IN-04** — teaching material accept | DR-IO-01, DR-IO-03, DR-IO-07, DR-UI-04 |
| **SR-IN-05** — starting rubric: file / paste / none | DR-IO-01, DR-IO-07, DR-AS-15, DR-IM-02, DR-IM-04, DR-UI-04 |
| **SR-IN-06** — sample student copies | DR-IO-04, DR-IO-07, DR-UI-04 |
| **SR-IN-07** — extract text from handwritten copies | DR-IO-04, DR-IO-05 |
| **SR-IN-08** — partial parsing failures surfaced | DR-IO-06 |
| **SR-IN-09** — record evidence profile per run | DR-IO-07 |
| **SR-AS-01** — Ambiguity assessment | DR-AS-01, DR-AS-02, DR-AS-06, DR-SCR-02 |
| **SR-AS-02** — Applicability assessment | DR-AS-01, DR-AS-02, DR-AS-07, DR-AS-15, DR-SCR-02 |
| **SR-AS-03** — Discrimination Power assessment | DR-AS-01, DR-AS-02, DR-AS-08, DR-SCR-02 |
| **SR-AS-04** — ground in teaching material | DR-AS-04, DR-IM-04 |
| **SR-AS-05** — use student copies for coverage / discrimination | DR-AS-03 |
| **SR-AS-06** — synthetic candidate fallback (mark as synthetic) | DR-AS-03, DR-AS-04 |
| **SR-AS-07** — each finding tagged with one of the three criteria | DR-AS-01, DR-AS-06, DR-AS-07, DR-AS-08, DR-AS-09 |
| **SR-AS-08** — confidence indicator on each finding | DR-AS-05, DR-AS-10, DR-AS-14, DR-IO-05, DR-UI-08 |
| **SR-AS-09** — re-measurement against improved / edited rubric | DR-AS-11, DR-AS-12, DR-IM-10, DR-IM-11, DR-INT-06, DR-SCR-01, DR-UI-07 |
| **SR-AS-10** — pairwise consistency check (with linked ambiguity finding) | DR-AS-08, DR-AS-09 |
| **SR-IM-01** — improved rubric per run | DR-IM-01, DR-IM-02, DR-IM-03, DR-IM-04, DR-IM-07, DR-IM-14 |
| **SR-IM-02** — improved rubric is structured (criteria, sub-criteria, points, guidance) | DR-IM-01, DR-IM-04 |
| **SR-IM-03** — proposed changes list with criterion + rationale | DR-IM-03, DR-IM-08, DR-IM-09, DR-UI-06 |
| **SR-IM-04** — improved rubric does not contradict teaching material | DR-IM-06 |
| **SR-IM-05** — each change traces back to its motivating finding | DR-IM-03, DR-IM-09, DR-IM-13 |
| **SR-IM-06** — empty list when no improvement warranted | DR-IM-02, DR-IM-05 |
| **SR-UI-01** — browser GUI on the teacher's machine | DR-UI-01, DR-UI-02, DR-UI-03 |
| **SR-UI-02** — single input screen with all four fields | DR-UI-02, DR-UI-04 |
| **SR-UI-03** — mark each input field required / optional | DR-UI-04 |
| **SR-UI-04** — single action control to trigger the operation | DR-UI-04 |
| **SR-UI-05** — progress feedback while running | DR-UI-05 |
| **SR-UI-06** — teacher-native language (no internal vocabulary) | DR-UI-08 |
| **SR-UI-07** — original and improved rubric side by side | DR-UI-02, DR-UI-06 |
| **SR-UI-08** — each change with criterion tag and rationale | DR-UI-06, DR-UI-08 |
| **SR-UI-09** — accept / reject controls per change | DR-INT-06, DR-UI-07 |
| **SR-UI-10** — re-run after teacher edits | DR-INT-06, DR-UI-07 |
| **SR-OUT-01** — explained rubric file as deliverable | DR-DAT-07, DR-UI-06 |
| **SR-OUT-02** — root JSON with improved rubric + explanation | DR-DAT-07, DR-UI-06 |
| **SR-OUT-03** — explanation organized by the three criteria | DR-IM-08, DR-SCR-02, DR-UI-06 |
| **SR-OUT-04** — explained rubric file validates against schema | DR-DAT-03 |
| **SR-OUT-05** — reflect teacher accept / reject decisions | DR-INT-04, DR-INT-06, DR-UI-07 |
| **SR-OBS-01** — record audit bundle per run | DR-ARC-06, DR-DAT-07a, DR-OBS-01, DR-INT-03, DR-INT-05 |
| **SR-OBS-02** — log every model invocation | DR-ARC-06, DR-OBS-01, DR-LLM-08, DR-LLM-11 |
| **SR-OBS-03** — audit bundle retrievable from the user interface | DR-INT-05, DR-UI-08 |
| **SR-PRF-01** — accept up to 100 student copies in a single run | DR-PER-03, DR-PER-04, DR-PER-06 |
| **SR-PRF-02** — visible progress feedback for operations longer than 5 s | DR-PER-07, DR-UI-05 |
| **SR-PRF-03** — remain responsive (cancellation) while running | DR-PER-08 |

Every DR shall trace back to at least one SR. Every SR shall be covered by at least one DR. The matrix above closes both directions of the chain; future DR additions update both the per-DR `Trace` column and this matrix in lockstep.

---


## Modification log

| Version | Date | Change |
|---|---|---|
| 1.2.0 | 2026-04-15 | Removed train-button capability (DR-SCR-03/04/05/06/07) and all references. § 5.10 reduced from 7 DRs to 2. DR-ARC-08 updated (8→7 subcommands). DR-INT-02 updated (two→one workflow). DR-DEP-06 simplified. § 6 carve-out paragraph removed. Removed all internal working-notes references from the document. |
| 1.1.0 | 2026-04-15 | Post-implementation alignment pass. Temperature 0.7→0.3 for grading calls (matching `simulation.py`). ADD_NODE documented as implemented alongside REPLACE_FIELD. Ambiguity engine documented with α-based thresholds and five-band classification (matching `engines.py`). Discrimination formula fallback path and ceiling cap documented. Paired scoring documented. Leaf-only grading policy noted. Four Should-level Settings marked v2-deferred: `assess_max_failure_fraction`, `llm_max_concurrency`, `student_copy_chunk_size`, `parser_call_timeout_seconds`. |
| 1.0.0 | 2026-04-14 | Aligned with implemented codebase. Simulation-backed engines, actual formulas, v1.0 scope notes on REPLACE_FIELD-only propose, ThreadPoolExecutor concurrency, scores_from_simulation scoring. Condensed rationale blocks and trimmed verbose sections. Version bump to 1.0.0. |
| 0.19.0 | 2026-04-12 | R7 closeout: § 5.6 DR-UI (8 DRs) + § 6 traceability matrix populated. Design layer closed at 116 DRs. |
| 0.18.0 | 2026-04-11 | R6: § 5.5 DR-IM (14 DRs). Drafts-vs-final ownership boundary, three-step application pipeline. |
| 0.17.0 | 2026-04-11 | R5: § 5.4 DR-AS (15 DRs). Three measurement engines, assess/score ownership boundary. |
| 0.16.1 | 2026-04-11 | Documentation hygiene: removed development-tool names from body text. |
| 0.16.0 | 2026-04-11 | R4: DR-IO (8), DR-PER (8), DR-SCR (7) = 23 DRs. Three Codex review passes absorbed. |
| 0.15.0 | 2026-04-11 | R3: DR-LLM (11) + DR-OBS (4) = 15 DRs, reconciled post-pivot. |
| 0.14.0 | 2026-04-11 | Validance pivot: four-layer architecture (L1–L4). DR-DEP (9) + DR-INT (9) = 18 DRs. |
| 0.13.0 | 2026-04-11 | R1 + R2: DR-ARC (12) + DR-DAT (11) = 23 DRs. § 4.8 audit-bundle index/detail split. |
| 0.12.0–0.12.1 | 2026-04-11 | § 4 data models: all model shapes pseudocoded with type signatures and invariants. |
| 0.10.0–0.11.0 | 2026-04-11 | § 3 technology stack: all 11 decisions locked with rationale. |
| 0.1.0–0.9.0 | 2026-04-11 | Initial skeleton through § 2 architectural overview. |

