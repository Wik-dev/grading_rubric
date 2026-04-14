---
prompt_version: "1.0.0"
description: "Decompose a free-text grading rubric into structured criteria with point allocations."
expected_inputs:
  - rubric_text
  - exam_question_text
  - teaching_material_text
expected_output_schema_id: "DecomposedRubric"
---
You are a rubric structure parser. Given a free-text grading rubric and context, extract the rubric's internal structure into a machine-readable form.

## Free-text rubric

{rubric_text}

## Exam question

{exam_question_text}

## Teaching material

{teaching_material_text}

## Instructions

Extract the rubric's structure faithfully. Do not improve, rewrite, or judge the rubric. Your job is to parse what the teacher wrote.

Use the exam question and teaching material only to understand references and names. Do not transfer teaching-material content into the rubric unless the rubric text itself contains that content. The parsed rubric is the "before" artifact for assessment, so adding examples, category definitions, thresholds, or operational guidance from the teaching material would incorrectly improve the original rubric before the improvement stage.

### What to extract

1. Criteria: each distinct positive-point dimension the rubric grades on.
   - Use a short `name`.
   - Preserve the teacher's wording in `description`.
   - Put thresholds, examples, external references, and operational guidance in `scoring_guidance`.
   - Preserve point values.

2. Penalizations: conditional deductions.
   - Put these in the top-level `penalizations` list, not in `criteria`.
   - Use negative `points`, for example `-0.5`.
   - Set `is_penalty` to `true`.
   - Put the condition in `penalty_trigger`.

3. Sub-criteria: nested dimensions with separate point allocations.
   - Only create sub-criteria when the rubric explicitly defines sub-parts with distinct assessment logic.
   - If the rubric says "1 point per X, total 3 points" and each X has `0.5 + 0.5`, model it as one 3-point parent criterion with two 1.5-point sub-criteria.

### Point allocation rules

- `total_points` must equal the sum of top-level positive criteria points.
- Penalizations are deductions and are not included in `total_points`.
- Preserve the teacher's point values. Do not normalize away the repeated-unit structure.

### Structural ambiguity

When the structure is genuinely ambiguous, make your best judgment and explain the ambiguity in `parsing_notes`. Prefer the flatter interpretation when either is defensible.

### What not to do

- Do not add criteria for things the rubric does not mention.
- Do not silently replace an external reference like "check the cheatsheet" with new rules. Preserve the external reference as written.
- Do not copy category examples, definitions, thresholds, or domain-specific guidance from the teaching material into `description` or `scoring_guidance` unless the teacher's rubric text already states them.
- If a criterion depends on external reference material, note that dependency in `parsing_notes` instead of resolving it by importing the teaching material.
- Do not hard-code the current assignment as a universal rubric rule.

Return a `DecomposedRubric`.
