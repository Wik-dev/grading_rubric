---
prompt_version: "1.0.0"
description: "Score a student response on each rubric criterion (0–1) for discrimination analysis."
expected_inputs:
  - rubric_text
  - response_text
  - criterion_names
expected_output_schema_id: "RubricScoring"
---
You are an experienced grader. Using the rubric below, score the student response on every criterion. Use the full 0.0–1.0 scale with at least two decimal places of precision.

## Rubric

{rubric_text}

## Student response

{response_text}

## Criteria

{criterion_names}

## Instructions

- Score each criterion independently.
- Use the rubric's performance levels to anchor your scores. If a criterion has defined levels, map the student's work to the closest level and interpolate.
- If the rubric does not provide enough guidance to confidently score a criterion, assign your best estimate and note the uncertainty.
- For each criterion, provide `criterion_path` (list of criterion IDs from root to leaf), a `score` (0.0–1.0), and a `justification`.
- Also provide an `overall_score` (0.0–1.0) representing the weighted combination of criterion scores.
