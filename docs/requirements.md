# Grading Rubric Studio — Requirements

**Version**: 0.3.2
**Date**: 2026-04-10
**Status**: Draft
**Author**: Wiktor Lisowski

---

## 1. Introduction

### 1.1 Purpose

This document defines the **user needs** and **user requirements** for *Grading Rubric Studio*, an application that helps teachers produce high-quality grading rubrics for large-class exams.

The document follows a layered specification approach:

- **User Needs (UN)** — the underlying problems and outcomes that matter to the teacher. Few in number, written in user language, not solution-specific.
- **User Requirements (UR)** — testable expressions of what the user must be able to do, derived from the user needs. Still user-centered.
- **System Requirements (SR)** — what the system must do to satisfy the user requirements. *To be added in a subsequent iteration of this document.*

### 1.2 Scope

**In scope**

- Producing a high-quality grading rubric from any combination of: an exam question, course teaching material, an existing rubric draft or grading intentions, and sample student copies.
- Assessing rubric quality against the three criteria of Ambiguity, Applicability, and Discrimination Power as defined in the challenge brief.
- Presenting proposed changes to the teacher with rationale, organized by criterion.
- Allowing the teacher to accept or reject individual proposed changes and to re-run the assessment.
- Producing a portable JSON output containing the final rubric and the explanation of changes.

**Out of scope**

- Grading of student copies. The application produces and improves rubrics; it does not grade.
- Multi-teacher collaboration, accounts, or persistent storage across sessions.
- Integration with external grading workflows or learning management systems.
- Calibration of the application against teacher-graded copies (future capability).
- Training of supervised models from accumulated usage data (future capability).
- Mobile UI.

### 1.3 Reference documents

| Document | Notes |
|---|---|
| EPFL Technical Coding Challenge brief | Source of the problem statement, the three quality criteria, and the mandatory output format. Confidential; not included in this repository. |
| Example exam question and rubric | Reference material; not included in this repository. |
| Bad Actors Strategy teaching resource | Reference material; not included in this repository. |
| Sample student copies (3) | Reference material; not included in this repository. |
| Job description — AI Engineer for Educational Assessment & Feedback (EPFL) | Context for the broader use case the application is intended to serve. |

---

## 2. Glossary

| Term | Definition |
|---|---|
| **Teacher** | The instructor responsible for designing the exam and the grading rubric. The primary user of this application. |
| **Grader** | A member of the grading team who applies the rubric to grade student copies. **Not a user of this application** — but the rubric the application produces must serve graders. |
| **Copy** | A student's answer to an exam question. May be handwritten or digital. |
| **Exam question** | The question, including any scenario and instructions, that students answer in the exam. |
| **Teaching material** | Course content (slides, notes, textbook excerpts) on which the exam is based. |
| **Rubric** | Any expression of how positive and negative points are distributed across exam questions and evaluation criteria, for the purpose of guiding graders. The form may range from an informal natural-language description (e.g. *"weight part 1 more, focus on reasoning depth in part 2"*) through a partial draft, up to a fully structured table with weights, sub-criteria, and penalties. All of these are valid rubrics under this definition. |
| **Grading** | The act of applying a rubric to a copy in order to produce a grade. Performed by graders. *Not* performed by this application. |
| **Assessment** *(of a rubric)* | The analysis of a rubric's quality against the three criteria (Ambiguity, Applicability, Discrimination Power). Performed by this application. |
| **Review** *(of an assessment)* | The teacher's examination of the application's proposed changes, including the acceptance or rejection of individual proposals. |
| **Quality** *(of a rubric)* | The combined measure of Ambiguity, Applicability, and Discrimination Power as defined in the challenge brief. |
| **Ambiguity** | Whether the rubric is formulated with objective, unambiguous criteria such that all graders reach the same interpretation independently. |
| **Applicability** | Whether the rubric covers the diversity of possible student responses, leaving no valid answer type unaddressed. |
| **Discrimination Power** | Whether the rubric clearly separates excellent work from poor work. |
| **Evidence profile** | A per-run record of which optional inputs were provided to the system and in what quantity: presence and approximate volume of teaching material, form of the starting rubric (none, informal, partial, full draft), and number of sample student copies. The evidence profile determines which assessment paths the system can take on a given run and is the basis on which the system calibrates its own confidence in its findings. |
| **Assessment finding** | An atomic output of the assessment stage: a single observation about the rubric, tagged with exactly one of the three criteria (Ambiguity, Applicability, Discrimination Power), supported by evidence drawn from the inputs, and carrying its own confidence indicator. One run typically produces several findings. Each finding is the seed from which the improvement stage may generate a proposed change to the rubric. |
| **Large-size class** | An exam cohort of approximately 100 or more student copies. The application is designed to support rubric design for such cohorts. |

A note on the word "evaluation". The challenge brief refers to *Evaluation Criteria* — the three properties used to judge a rubric's quality. To avoid confusion between the multiple senses of the verb "evaluate" (graders evaluate students, the application evaluates rubrics, the teacher evaluates the application's output), this document uses **grading**, **assessment**, and **review** as defined above. The word *evaluation* is reserved for the brief's term *Evaluation Criteria*.

---

## 3. User Needs

User needs capture the underlying problems and outcomes that matter to the teacher. They are few, problem-oriented, and not solution-specific.

| ID | Need | Rationale |
|---|---|---|
| **UN-01** | The teacher needs a high-quality grading rubric to enable their grading team to grade student copies fairly and quickly across a large class. | Stated directly in the challenge brief: *"The quality of the grading rubric is essential to ensure a fair and fast grading process."* The brief decomposes quality into three criteria (Ambiguity, Applicability, Discrimination Power), each of which directly serves either fairness (consistent interpretation across graders, coverage of all valid responses) or speed (clear criteria reduce per-copy decision time). |
| **UN-02** | The teacher needs to trust and understand any changes proposed to their rubric before adopting them. | The teacher is the domain expert and is accountable for the rubric handed to graders. Adoption requires trust, and trust requires that each proposed change be transparent in its rationale and overridable by the teacher. |
| **UN-03** | The teacher needs the final rubric and the rationale behind it in a portable form that can be handed to graders or stored alongside other course materials. | The challenge brief mandates a JSON output containing the improved rubric and an explanation of the suggested improvements. The teacher needs this artifact to flow into the actual grading process. |

---

## 4. User Requirements

User requirements are derived from the user needs and express what the teacher must be able to do, perceive, or accomplish. They are organized below by the surface they touch: inputs, operation, review, and output.

**Criticality** is assigned per requirement using a MoSCoW scale:

- **Must** — required for the application to satisfy the challenge brief or to be usable at all. Failure to deliver a *Must* invalidates the deliverable.
- **Should** — strongly improves the quality or value of the result. The application is materially weaker without it but still functional.
- **Could** — refinement that improves the user experience or supports advanced workflows. The application is fully functional without it.

The current set is **5 Must / 2 Should / 2 Could**.

### 4.1 Inputs

| ID | Requirement | Criticality | Rationale | Traces to |
|---|---|---|---|---|
| **UR-01** | The teacher shall be able to provide an exam question to the application. | **Must** | Without an exam question there is nothing to grade and no anchor for any rubric. This is the only mandatory input. | UN-01 |
| **UR-02** | The teacher shall be able to provide teaching material (course content the exam is based on) to the application as an optional input. | **Should** | Teaching material defines what counts as correct in the domain and surfaces ambiguities present in the domain itself. A rubric criterion that contradicts the teaching material is unfair to students; the application needs the teaching material to detect this. | UN-01 |
| **UR-03** | The teacher shall be able to provide a starting rubric — ranging from no input at all, through informal grading intentions in natural language, to a complete draft rubric — as an optional input. | **Should** | The challenge brief implicitly assumes the teacher arrives with a rubric, but in practice the teacher may arrive with anything from nothing to a polished draft. The application accepts all of these as valid starting points for the same operation. | UN-01 |
| **UR-04** | The teacher shall be able to provide one or more sample student copies as an optional input. | **Could** | Real student copies allow the application to ground its assessment in actual student behavior, in particular for checking that the rubric covers the diversity of real responses and for proposing concrete anchor examples inside the improved rubric. The application is fully functional without copies. | UN-01 |

### 4.2 Operation

| ID | Requirement | Criticality | Rationale | Traces to |
|---|---|---|---|---|
| **UR-05** | The teacher shall be able to trigger an assessment of the rubric and a generation of an improved rubric from the application interface, with a single user action. | **Must** | A clear, single action — not a command-line invocation. The brief calls this an "AI application", which to the teacher means a user interface with controls. Whatever inputs are present on the input screen are used by the operation; missing optional inputs are simply not used. | UN-01 |

### 4.3 Review

| ID | Requirement | Criticality | Rationale | Traces to |
|---|---|---|---|---|
| **UR-06** | The teacher shall be able to view each proposed change to the rubric together with the criterion (Ambiguity, Applicability, or Discrimination Power) it addresses and a human-readable rationale for the change. | **Must** | The brief explicitly mandates that the output include an explanation of the suggested improvements organized by the three criteria. Beyond the brief, trust requires transparency: the teacher must see *why* each change was proposed and *which* of the three quality criteria it acts on. | UN-02 |
| **UR-07** | The teacher shall be able to accept or reject each proposed change individually before finalizing the rubric. | **Could** | A refinement on top of the canonical flow. The canonical flow is whole-accept or regenerate with different inputs; per-change cherry-picking is convenient but not essential. The teacher who disagrees with the result can always re-run with adjusted inputs. | UN-02 |
| **UR-08** | The teacher shall be able to re-run the assessment after accepting or rejecting changes, in order to see the effect of their decisions on the rubric. | **Could** | Dependent on UR-07. If per-change edits are a refinement, then re-running across them is also a refinement. Re-running the application from scratch with different inputs is always available via UR-05 and is a separate flow. | UN-02 |

### 4.4 Output

| ID | Requirement | Criticality | Rationale | Traces to |
|---|---|---|---|---|
| **UR-09** | The teacher shall be able to download the final rubric, together with the explanation of all accepted changes organized by criterion, as a single JSON file. | **Must** | The challenge brief mandates a JSON deliverable containing the improved rubric and the explanation of improvements. The downloaded file is what the teacher takes to their grading team. | UN-03 |

---

## 5. System Requirements

System requirements describe what the system must do in order to satisfy the user requirements. They are deliberately **technology-neutral** at this layer: choices of language, framework, model provider, file format, schema, library, deployment target, and algorithm are made one level down in the Design Requirements. A system requirement that mandates a specific library or vendor is in the wrong document.

System requirements are organized below into seven groups by the area of the system they constrain:

- **SR-IN** — Input handling
- **SR-AS** — Assessment
- **SR-IM** — Improvement generation
- **SR-UI** — User interface
- **SR-OUT** — Output
- **SR-OBS** — Observability
- **SR-PRF** — Performance and scale

The same MoSCoW criticality scale defined in § 4 applies. The current set is **44 system requirements: 21 Must / 14 Should / 9 Could**.

The following concerns are intentionally **deferred to the Design Requirements** layer and do not appear here: choice of LLM provider and prompting approach, choice of UI framework, choice of file/document parsing libraries, choice of schema language, configuration mechanism, secret handling, caching strategy, deterministic execution policy, deployment topology, packaging, and orchestration layer.

### 5.1 Input handling (SR-IN)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-IN-01** | The system shall accept an exam question provided as a text, markdown, or PDF document. | **Must** | UR-01 |
| **SR-IN-02** | The system shall refuse to start the assessment operation when no exam question has been provided. | **Must** | UR-01, UR-05 |
| **SR-IN-03** | The system shall extract structured text content from the provided exam question document for use by downstream stages. | **Must** | UR-01 |
| **SR-IN-04** | The system shall accept teaching material as one or more text, markdown, or PDF documents when provided. | **Should** | UR-02 |
| **SR-IN-05** | The system shall accept a starting rubric in any of the forms covered by the glossary definition of *Rubric*: file upload, pasted text, or no input at all. | **Should** | UR-03 |
| **SR-IN-06** | The system shall accept zero or more sample student copies as file uploads, including handwritten copies. | **Could** | UR-04 |
| **SR-IN-07** | The system shall extract text from handwritten student copies before they are used by the assessment stage. | **Could** | UR-04 |
| **SR-IN-08** | The system shall surface partial input parsing failures to the teacher without aborting the operation, provided that a usable subset of inputs remains. | **Should** | UR-01, UR-02, UR-03, UR-04 |
| **SR-IN-09** | The system shall determine and record, for each run, an *evidence profile* describing which optional inputs were provided and in what quantity. | **Must** | UR-05, UR-06 |

### 5.2 Assessment (SR-AS)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-AS-01** | The system shall produce an assessment of the rubric's **Ambiguity** for every successful run. | **Must** | UR-05, UR-06 |
| **SR-AS-02** | The system shall produce an assessment of the rubric's **Applicability** for every successful run. | **Must** | UR-05, UR-06 |
| **SR-AS-03** | The system shall produce an assessment of the rubric's **Discrimination Power** for every successful run. | **Must** | UR-05, UR-06 |
| **SR-AS-04** | The system shall ground its judgments of correctness in the provided teaching material whenever teaching material is available. | **Should** | UR-02, UR-06 |
| **SR-AS-05** | The system shall use the provided sample student copies to test rubric coverage and discrimination whenever at least one copy is available. | **Should** | UR-04, UR-06 |
| **SR-AS-06** | When no student copies are provided, the system shall fall back to synthetic candidate responses for coverage testing and shall mark any evidence so produced as synthetic. | **Could** | UR-06 |
| **SR-AS-07** | Each assessment finding shall be tagged with exactly one of the three criteria (Ambiguity, Applicability, Discrimination Power). | **Must** | UR-06 |
| **SR-AS-08** | The system shall attach a confidence indicator to each assessment finding, reflecting the strength and quantity of supporting evidence. | **Should** | UR-06 |

### 5.3 Improvement generation (SR-IM)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-IM-01** | The system shall produce an improved rubric for every successful run. | **Must** | UR-05, UR-09 |
| **SR-IM-02** | The improved rubric shall be a structured object containing criteria, sub-criteria, point allocations, and scoring guidance. | **Must** | UR-09 |
| **SR-IM-03** | The system shall produce a list of proposed changes, where each change records the original passage, the modified passage, the criterion it addresses, and a human-readable rationale. | **Must** | UR-06 |
| **SR-IM-04** | The improved rubric shall not contradict the provided teaching material whenever teaching material is available. | **Should** | UR-02, UR-06 |
| **SR-IM-05** | Each proposed change shall trace back to the assessment finding that motivated it. | **Should** | UR-06 |
| **SR-IM-06** | The system shall return an empty list of proposed changes, together with an explanation, when the assessment finds no improvement warranted. | **Could** | UR-06, UR-09 |

### 5.4 User interface (SR-UI)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-UI-01** | The system shall present a graphical user interface accessible from a standard web browser running on the teacher's local machine. | **Must** | UR-01, UR-02, UR-03, UR-04, UR-05, UR-06, UR-09 |
| **SR-UI-02** | The user interface shall provide a single input screen exposing all four input fields (exam question, teaching material, starting rubric, sample copies). | **Must** | UR-01, UR-02, UR-03, UR-04 |
| **SR-UI-03** | The user interface shall visually mark each input field as either required or optional. | **Must** | UR-01, UR-02, UR-03, UR-04 |
| **SR-UI-04** | The user interface shall provide a single action control that triggers the full assessment and improvement operation. | **Must** | UR-05 |
| **SR-UI-05** | The user interface shall display progress feedback to the teacher while the operation is running. | **Should** | UR-05 |
| **SR-UI-06** | The user interface shall use teacher-facing language and shall not expose internal model, prompt, or pipeline terminology to the user. | **Should** | UR-05, UR-06 |
| **SR-UI-07** | The user interface shall display the original rubric and the improved rubric side by side after the operation completes. | **Must** | UR-06 |
| **SR-UI-08** | The user interface shall display each proposed change together with its criterion tag and its rationale. | **Must** | UR-06 |
| **SR-UI-09** | The user interface shall provide controls to accept or reject each proposed change individually. | **Could** | UR-07 |
| **SR-UI-10** | The user interface shall provide an action to re-run the assessment after the teacher has accepted or rejected changes. | **Could** | UR-08 |

### 5.5 Output (SR-OUT)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-OUT-01** | The system shall produce a single JSON file as the deliverable output of every successful run. | **Must** | UR-09 |
| **SR-OUT-02** | The JSON output shall contain one top-level field for the improved rubric and one top-level field for the explanation of changes. | **Must** | UR-09 |
| **SR-OUT-03** | The explanation of changes in the JSON output shall be organized by the three quality criteria (Ambiguity, Applicability, Discrimination Power). | **Must** | UR-06, UR-09 |
| **SR-OUT-04** | The JSON output shall validate against a documented schema. | **Should** | UR-09 |
| **SR-OUT-05** | The JSON output shall reflect the teacher's per-change accept and reject decisions when such decisions have been made. | **Could** | UR-07, UR-09 |

### 5.6 Observability (SR-OBS)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-OBS-01** | The system shall record an audit bundle for each run, capturing the inputs, the evidence profile, the intermediate assessment findings, and the final rubric. | **Should** | UR-05, UR-06 |
| **SR-OBS-02** | The system shall log every model invocation made during a run, recording its purpose, the prompt identifier used, and its outcome. | **Should** | UR-06 |
| **SR-OBS-03** | The audit bundle for the current run shall be retrievable from the user interface. | **Could** | UR-06 |

### 5.7 Performance and scale (SR-PRF)

| ID | Requirement | Criticality | Traces to |
|---|---|---|---|
| **SR-PRF-01** | The system shall accept and process up to 100 sample student copies in a single run without functional degradation. | **Should** | UR-04 |
| **SR-PRF-02** | The system shall provide visible progress feedback for any operation expected to take longer than five seconds. | **Must** | UR-05 |
| **SR-PRF-03** | The system shall remain responsive to user input (in particular, allowing the teacher to cancel the run) while the assessment operation is in progress. | **Could** | UR-05 |

---

## 6. Traceability

Every requirement at each layer traces to at least one requirement on the layer above it, and every requirement on each layer is covered by at least one requirement on the layer below it.

### 6.1 User Needs → User Requirements

| User Need | Covered by |
|---|---|
| UN-01 — High-quality rubric for fair and fast grading | UR-01, UR-02, UR-03, UR-04, UR-05 |
| UN-02 — Trust and understand proposed changes | UR-06, UR-07, UR-08 |
| UN-03 — Portable handoff to graders | UR-09 |

### 6.2 User Requirements → System Requirements

| User Requirement | Covered by |
|---|---|
| UR-01 — Provide exam question | SR-IN-01, SR-IN-02, SR-IN-03, SR-IN-08, SR-UI-01, SR-UI-02, SR-UI-03 |
| UR-02 — Provide teaching material | SR-IN-04, SR-IN-08, SR-AS-04, SR-IM-04, SR-UI-01, SR-UI-02, SR-UI-03 |
| UR-03 — Provide starting rubric or grading intentions | SR-IN-05, SR-IN-08, SR-UI-01, SR-UI-02, SR-UI-03 |
| UR-04 — Provide sample student copies | SR-IN-06, SR-IN-07, SR-IN-08, SR-AS-05, SR-UI-01, SR-UI-02, SR-UI-03, SR-PRF-01 |
| UR-05 — Trigger the operation with a single action | SR-IN-02, SR-IN-09, SR-AS-01, SR-AS-02, SR-AS-03, SR-IM-01, SR-UI-04, SR-UI-05, SR-UI-06, SR-OBS-01, SR-OBS-02, SR-PRF-02, SR-PRF-03 |
| UR-06 — View each change with criterion and rationale | SR-IN-09, SR-AS-01, SR-AS-02, SR-AS-03, SR-AS-04, SR-AS-05, SR-AS-06, SR-AS-07, SR-AS-08, SR-IM-03, SR-IM-04, SR-IM-05, SR-IM-06, SR-UI-06, SR-UI-07, SR-UI-08, SR-OUT-03, SR-OBS-01, SR-OBS-02, SR-OBS-03 |
| UR-07 — Accept or reject changes individually | SR-UI-09, SR-OUT-05 |
| UR-08 — Re-run after edits | SR-UI-10 |
| UR-09 — Download the final rubric and explanation as JSON | SR-IM-01, SR-IM-02, SR-IM-06, SR-OUT-01, SR-OUT-02, SR-OUT-03, SR-OUT-04, SR-OUT-05, SR-UI-01 |

---

## Modification log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.3.2 | 2026-04-10 | Wiktor Lisowski | Glossary: added *Assessment finding* entry. The term was used in SR-AS-07, SR-AS-08, SR-IM-05, and SR-OBS-01 but had not been anchored in the glossary. Dropped the redundant qualifier "individual" from SR-AS-07. |
| 0.3.1 | 2026-04-10 | Wiktor Lisowski | Glossary: added *Evidence profile* entry. The term was already used in SR-IN-09 and underpins SR-AS-04, SR-AS-05, SR-AS-06, SR-AS-08, and SR-OBS-01 but had not been anchored in the glossary. |
| 0.3.0 | 2026-04-10 | Wiktor Lisowski | Added § 5 *System Requirements* with 44 SRs across seven groups (SR-IN, SR-AS, SR-IM, SR-UI, SR-OUT, SR-OBS, SR-PRF). Distribution: 21 Must / 14 Should / 9 Could. SRs are technology-neutral; choices of language, framework, model provider, file format, schema, library, configuration, secrets, caching, deterministic execution, and orchestration layer are deferred to the Design Requirements. Renumbered the existing single-table traceability section to § 6 *Traceability* and added § 6.2 *User Requirements → System Requirements*. |
| 0.2.0 | 2026-04-10 | Wiktor Lisowski | Added a *Criticality* column (MoSCoW) to all User Requirement tables. Result: 5 Must / 2 Should / 2 Could. Per-change accept/reject (UR-07) and its dependent re-run (UR-08) reclassified as *Could* — the canonical flow is whole-accept or regenerate with different inputs. |
| 0.1.1 | 2026-04-10 | Wiktor Lisowski | Glossary: dropped *Grading intentions* as a separate term (it was redundant with the broad definition of *Rubric*). Folded the natural-language example into the *Rubric* definition. |
| 0.1.0 | 2026-04-10 | Wiktor Lisowski | Initial draft. User Needs (3), User Requirements (9), glossary, scope. System requirements to be added in the next iteration. |
