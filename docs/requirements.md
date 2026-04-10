# Grading Rubric Studio — Requirements

**Version**: 0.1.1
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

### 4.1 Inputs

| ID | Requirement | Rationale | Traces to |
|---|---|---|---|
| **UR-01** | The teacher shall be able to provide an exam question to the application. | Without an exam question there is nothing to grade and no anchor for any rubric. This is the only mandatory input. | UN-01 |
| **UR-02** | The teacher shall be able to provide teaching material (course content the exam is based on) to the application as an optional input. | Teaching material defines what counts as correct in the domain and surfaces ambiguities present in the domain itself. A rubric criterion that contradicts the teaching material is unfair to students; the application needs the teaching material to detect this. | UN-01 |
| **UR-03** | The teacher shall be able to provide a starting rubric — ranging from no input at all, through informal grading intentions in natural language, to a complete draft rubric — as an optional input. | The challenge brief implicitly assumes the teacher arrives with a rubric, but in practice the teacher may arrive with anything from nothing to a polished draft. The application accepts all of these as valid starting points for the same operation. | UN-01 |
| **UR-04** | The teacher shall be able to provide one or more sample student copies as an optional input. | Real student copies allow the application to ground its assessment in actual student behavior, in particular for checking that the rubric covers the diversity of real responses and for proposing concrete anchor examples inside the improved rubric. | UN-01 |

### 4.2 Operation

| ID | Requirement | Rationale | Traces to |
|---|---|---|---|
| **UR-05** | The teacher shall be able to trigger an assessment of the rubric and a generation of an improved rubric from the application interface, with a single user action. | A clear, single action — not a command-line invocation. The brief calls this an "AI application", which to the teacher means a user interface with controls. Whatever inputs are present on the input screen are used by the operation; missing optional inputs are simply not used. | UN-01 |

### 4.3 Review

| ID | Requirement | Rationale | Traces to |
|---|---|---|---|
| **UR-06** | The teacher shall be able to view each proposed change to the rubric together with the criterion (Ambiguity, Applicability, or Discrimination Power) it addresses and a human-readable rationale for the change. | Trust requires transparency. The teacher must see *why* each change was proposed and against *which* of the three quality criteria it acts. | UN-02 |
| **UR-07** | The teacher shall be able to accept or reject each proposed change individually before finalizing the rubric. | The teacher is the domain expert and may have institutional, pedagogical, or contextual reasons to reject a change that the application cannot know. | UN-02 |
| **UR-08** | The teacher shall be able to re-run the assessment after accepting or rejecting changes, in order to see the effect of their decisions on the rubric. | Rubric design is iterative. A teacher may not know in advance how rejecting a change affects overall rubric quality, and may want to explore alternatives before finalizing. | UN-02 |

### 4.4 Output

| ID | Requirement | Rationale | Traces to |
|---|---|---|---|
| **UR-09** | The teacher shall be able to download the final rubric, together with the explanation of all accepted changes organized by criterion, as a single JSON file. | The challenge brief mandates a JSON deliverable containing the improved rubric and the explanation of improvements. The downloaded file is what the teacher takes to their grading team. | UN-03 |

---

## 5. Traceability — User Needs to User Requirements

| User Need | Covered by |
|---|---|
| UN-01 — High-quality rubric for fair and fast grading | UR-01, UR-02, UR-03, UR-04, UR-05 |
| UN-02 — Trust and understand proposed changes | UR-06, UR-07, UR-08 |
| UN-03 — Portable handoff to graders | UR-09 |

Every user requirement traces back to at least one user need. Every user need is covered by at least one user requirement.

---

## Modification log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1.1 | 2026-04-10 | Wiktor Lisowski | Glossary: dropped *Grading intentions* as a separate term (it was redundant with the broad definition of *Rubric*). Folded the natural-language example into the *Rubric* definition. |
| 0.1.0 | 2026-04-10 | Wiktor Lisowski | Initial draft. User Needs (3), User Requirements (9), glossary, scope. System requirements to be added in the next iteration. |
