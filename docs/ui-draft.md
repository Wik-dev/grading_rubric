# Grading Rubric Studio — UI Draft

**Version**: 0.1.0
**Date**: 2026-04-10
**Status**: Initial draft
**Author**: Wiktor Lisowski

---

## 1. Purpose

This document is a starting sketch of the user interface for *Grading Rubric Studio*. It is intentionally informal at this stage. Its purpose is to make the user requirements tangible and to surface design questions early.

The screens described here cover the three logical stages of the user experience:

1. **Inputs** — the teacher provides whatever materials they have.
2. **Progress** — the application works while keeping the teacher informed.
3. **Review and download** — the teacher reviews proposed changes, decides which to keep, and exports the result.

These three stages collectively realize User Requirements UR-01 through UR-09 (see [`requirements.md`](requirements.md)).

---

## 2. Design principles

A few principles guide the UI sketches below.

- **Single unified flow.** Whether the teacher arrives with nothing, with grading intentions, or with a polished draft rubric, they follow the same flow. The application adapts to what is provided rather than forcing the teacher into a different mode.
- **One mandatory input, the rest optional.** Only the exam question is required (UR-01). Every other input field is clearly marked optional and can be left empty.
- **No internal vocabulary.** The interface speaks in the teacher's language (*"check for ambiguous wording"*) rather than the system's (*"run grader panel with persona variance"*). The teacher does not need to know how the application works internally.
- **Trust through transparency.** Every proposed change is shown together with which of the three criteria it addresses and a human-readable rationale (UR-06). A *Why?* affordance lets the teacher drill into more detail if they want to.
- **The teacher is in charge.** The application proposes; the teacher decides. Each change can be individually accepted or rejected (UR-07), and the assessment can be re-run after edits (UR-08).

---

## 3. Screens

### 3.1 Inputs

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

**Notes**

- The single screen covers UR-01 to UR-04 (all four input requirements) and UR-05 (the trigger).
- The action button label, *Build my rubric*, intentionally covers both the case where there is no starting rubric and the case where there is a draft. The application is unified around a single operation.
- Field optionality is shown in the field label. There are no hidden requirements.

### 3.2 Progress

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
│  ○  Generating the improved rubric                          │
│                                                             │
│  ████████░░░░░░░░░░░░░░░░░░  40 %                           │
└─────────────────────────────────────────────────────────────┘
```

**Notes**

- Each step is described in user language. The three middle steps map to the three quality criteria (Ambiguity, Applicability, Discrimination Power) without using those words explicitly until the review stage.
- Progress feedback is required because the operation is multi-step and the teacher must know the application is working.

### 3.3 Review and download

```
┌─────────────────────────────────────────────────────────────┐
│  Results                          [ Download JSON ]   [ × ] │
├─────────────────────────────────────────────────────────────┤
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
│  │  AMBIGUITY                                        │     │
│  │  Replace "corresponds to the category" with three │     │
│  │  explicit scoring levels (full / partial / none). │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  ├───────────────────────────────────────────────────┤     │
│  │  APPLICABILITY                                    │     │
│  │  Add a penalty for responses that show            │     │
│  │  fundamental misunderstanding of the strategy.    │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  ├───────────────────────────────────────────────────┤     │
│  │  DISCRIMINATION POWER                             │     │
│  │  Split the 0.5 / 0.5 sub-criteria into            │     │
│  │  0.4 / 0.3 / 0.3 to better separate quality       │     │
│  │  levels.                                          │     │
│  │             [ Accept ]  [ Reject ]  [ Why? ▾ ]    │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
│                  [ Re-assess after my edits ]               │
└─────────────────────────────────────────────────────────────┘
```

**Notes**

- The side-by-side view (UR-06) lets the teacher compare original and improved rubric directly.
- Each suggested change is tagged with the criterion it addresses (UR-06) and offers individual *Accept* / *Reject* controls (UR-07).
- The **Why?** affordance expands a panel containing the human-readable evidence behind the change. Trust without leaking implementation details.
- The **Re-assess after my edits** button realizes UR-08 (iteration). Re-running the assessment after rejections lets the teacher explore alternatives before downloading.
- The **Download JSON** button realizes UR-09. The downloaded file reflects the teacher's current acceptance state.

---

## 4. Open design questions

These are deliberately left open at this stage and will be resolved when system requirements are drafted.

1. **Single-page web app vs. multi-page app.** A single page with conditional sections is simpler for a local application but limits navigation. A multi-page flow is more conventional but requires routing. To be decided alongside the technology choice in SR.
2. **Persistence across page reloads.** If the teacher reloads the browser mid-review, are their accept/reject decisions lost? For a single-session local application this may be acceptable; for any multi-session use it is not.
3. **Drilldown depth in the *Why?* panel.** How much evidence to expose without overwhelming a non-technical user. The current sketch shows only a one-line explanation; the panel could include more.
4. **Handling of large input volumes.** When the teacher uploads 100+ student copies, the input screen needs a way to handle file lists gracefully without breaking the layout.
5. **Error and empty states.** What happens when the exam question is missing, when an upload fails, when the assessment finds nothing to improve. Each needs a screen state.

---

## Modification log

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1.0 | 2026-04-10 | Wiktor Lisowski | Initial draft. Three screens (inputs, progress, review and download), design principles, open questions. |
