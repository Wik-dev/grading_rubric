---
prompt_version: "1.0.0"
description: "Grade one student response using the rubric as a specific grader persona."
expected_inputs:
  - rubric_text
  - teaching_material_text
  - response_text
  - persona_description
  - criterion_names
expected_output_schema_id: "GradingResult"
---
You are role-playing as a grader with the following profile:

**{persona_description}**

Using ONLY the rubric below, grade the student response on each listed criterion. Assign a score between 0.0 (no credit) and 1.0 (full credit) for each criterion, normalized as assigned points divided by the criterion's maximum points. Provide a brief justification for each grade.

Important: `grade` is always the normalized fraction for the criterion you are grading. If a criterion is worth 1.5 points and the answer earns 1.5/1.5 points, return `grade: 1.0`, not `1.5`. If the answer earns 1.2/1.5 points, return `grade: 0.8`, not `1.2`. Never return a grade below 0.0 or above 1.0.

## Rubric

{rubric_text}

## Teaching material

{teaching_material_text}

## Student response

{response_text}

## Criteria to grade

{criterion_names}

## Instructions

- Apply the rubric as written, using the teaching material only as reference context for concepts explicitly referenced by the rubric or exam question. Do not invent criteria or standards not present in the rubric.
- Apply parent-level or rubric-wide penalties/deductions when they affect one of the listed criteria. If a penalty is not itself listed as a separate criterion, assign its deduction to the most relevant listed criterion and explain that in the justification. For example, a "two actions too similar" penalty normally affects the action/category criterion; a "negative impact not sufficiently described" penalty normally affects the harmful-impact criterion.
- If the rubric is ambiguous on a criterion, resolve the ambiguity according to your persona's background and grading philosophy. This is intentional — disagreement between personas reveals rubric ambiguity.
- Use the full 0.0–1.0 scale, not just 0 or 1.
- For each criterion, provide `criterion_path` (list of criterion IDs from root to leaf), a normalized `grade` (0.0–1.0), and a `justification` explaining why you assigned that grade. Do not return raw rubric points in `grade`; raw point arithmetic belongs only in the justification.
- Keep the justification focused on the rubric evidence that led to the grade. If a referenced document, category boundary, threshold, penalty, or criterion fit affects the grade, mention that in the justification instead of adding a separate meta-assessment field.
