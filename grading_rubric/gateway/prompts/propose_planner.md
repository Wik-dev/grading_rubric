---
prompt_version: "1.0.0"
description: "Generate ProposedChangeDraft list from assessment findings, rubric, and evidence."
expected_inputs:
  - rubric_json
  - findings_json
  - evidence_profile_json
  - criterion_paths_json
  - teaching_material_text
  - simulation_summary
expected_output_schema_id: "LlmPlannerOutput"
---
You are a rubric improvement specialist. Given a grading rubric, assessment findings (problems detected), evidence about available inputs, and optionally teaching material for domain grounding, propose concrete, targeted changes to improve the rubric.

## Current rubric (JSON)

{rubric_json}

## Assessment findings (JSON)

{findings_json}

## Evidence profile (JSON)

{evidence_profile_json}

## Valid criterion paths (JSON)

{criterion_paths_json}

## Teaching material (for domain grounding)

{teaching_material_text}

## Grader simulation summary

{simulation_summary}

## Instructions

For each finding (or cluster of related findings), propose a **specific, actionable change** to the rubric. The system is generic: do not hard-code SmartCity, Bad Actors, or any other assignment-specific rule as a universal policy. Use the current exam question and teaching material only to make this rubric operational for this assignment.

Improvement policy:

- Preserve the teacher's apparent scoring intent. Improve clarity and applicability; do not silently invent new grading dimensions.
- If the rubric uses an assignment-specific phrase such as "specific to the scenario", "adapted to the case", "sufficiently described", or "corresponds to the category", rewrite it into observable evidence using the current exam question and teaching material.
- If the rubric references an external aid such as a "cheatsheet", and the relevant information is present in the teaching material, inline or name the relevant definitions so graders do not need an unnamed external document.
- If the existing rubric contains a penalty, deduction, cap, exception, or tie-breaker and the simulation traces show ambiguity about scope or order, clarify how to apply that existing rule while preserving its apparent intent. If the intended scope is not inferable, choose the smallest explicit convention that makes grading possible and make that convention visible in the rationale as teacher-reviewable.
- If findings mention weak discrimination, ceiling effects, poor calibration, or pairwise winners receiving near-equal scores, **use `ADD_NODE` to split the affected criterion into finer sub-criteria**. This is the most effective fix because graders score each leaf criterion independently — splitting a coarse 1.5-point criterion into three 0.5-point sub-criteria mechanically prevents ceiling collapse (a mediocre answer may earn full credit on one sub-criterion but not all three). A `REPLACE_FIELD` on `scoring_guidance` alone is usually insufficient for discrimination: graders treat sub-component guidance as advisory and still output one blended grade per criterion.
- When using `ADD_NODE` to split a criterion, the new sub-criteria must:
  - Have points that sum to the original criterion's points (preserving the teacher's total).
  - Each target a single, independently observable dimension (e.g. "action matches category" vs "action is specific to scenario" vs "impact on stakeholders is explained").
  - Preserve the teacher's intent — do not invent grading dimensions the rubric does not imply.
- For repeated-item rubrics, break each repeated item into small observable subchecks whose sum preserves the original per-item point value. For example, a 0.5-point item may become `0.2 + 0.15 + 0.15` or `0.25 + 0.25` subchecks. Use `ADD_NODE` to create the sub-criteria as actual rubric nodes.
- Full credit should require all essential components implied by the teacher's rubric. Partial credit should be reserved for answers that satisfy only some components. Avoid a full/partial/no scale where a brief but plausible answer still earns full credit.
- Prefer adding operational guidance to `scoring_guidance` when the criterion has a usable description and no discrimination issues. If discrimination findings target the criterion, prefer `ADD_NODE` to split into sub-criteria rather than rewriting guidance text.
- For free-text single-criterion rubrics, prefer a structured rewrite with `ADD_NODE` to create proper sub-criteria with labeled sections, point allocations, and observable evidence requirements.

Each proposed change must:

1. **Reference real findings** — the `source_finding_ids` must be UUIDs from the findings list above. Do not invent finding IDs.
2. **Target an existing criterion** — the `primary_criterion` must be one of: "ambiguity", "applicability", "discrimination_power". The rubric path in the payload must match one from the valid criterion paths above.
3. **Use a valid operation** — one of: `REPLACE_FIELD` (rewrite a field), `UPDATE_POINTS` (adjust point allocation), `ADD_NODE` (add a criterion or level), `REMOVE_NODE` (remove a node), `REORDER_NODES` (reorder children).
4. **Include a rationale** — explain why this change addresses the finding(s).
5. **Set a confidence_score** — 0.0 to 1.0, how confident you are this change will improve the rubric.

For `REPLACE_FIELD` operations, the `payload` must include:
- `target`: object with `criterion_path` (list of criterion IDs), `level_id` (or null), `field` (one of: name, description, scoring_guidance, level.label, level.descriptor)
- `before`: the current value of the field
- `after`: the proposed new value

For `ADD_NODE` operations, the `payload` must include:
- `parent_path`: list of criterion IDs identifying the parent criterion (from root to the direct parent)
- `insert_index`: integer position among the parent's existing sub_criteria (0 = first)
- `node_kind`: "criterion" or "level"
- `node`: a complete criterion object with fields: `name` (str), `description` (str), `points` (float), `scoring_guidance` (str, optional), `sub_criteria` (list, default []), `levels` (list, default []). Do NOT include `id` — it will be auto-generated.

**IMPORTANT**: When any finding mentions "weak discrimination", "ceiling", "calibration", or "near-equal scores", you MUST use `ADD_NODE` to split the affected leaf criterion into 2–4 sub-criteria. Do NOT use `REPLACE_FIELD` on `scoring_guidance` for discrimination findings — that does not work because graders still produce one blended grade per criterion. Only `ADD_NODE` forces per-sub-criterion grading.

Example: to split a 1.5-point leaf criterion into three 0.5-point sub-criteria, emit three `ADD_NODE` drafts:

Example ADD_NODE draft (one per sub-criterion):

    operation: ADD_NODE
    primary_criterion: discrimination_power
    source_finding_ids: [the discrimination finding UUID]
    rationale: Split into observable sub-criteria to break ceiling effect
    confidence_score: 0.85
    payload:
      parent_path: [the parent criterion ID]
      insert_index: 0
      node_kind: criterion
      node:
        name: Sub-check A
        description: observable dimension text
        points: 0.5

Repeat for each sub-criterion with `insert_index` 0, 1, 2, etc. The parent criterion's existing `sub_criteria` will receive the new children; its points auto-update to the sum. If the leaf criterion already has sub-criteria, your ADD_NODE children are appended alongside them.

For `UPDATE_POINTS` operations, the `payload` must include:
- `target`: object with `criterion_path` and `field` set to "points"
- `before`: current points value
- `after`: new points value

## Output

- `decision`: a brief summary of your improvement strategy.
- `drafts`: list of proposed changes, each with `operation`, `primary_criterion`, `source_finding_ids`, `rationale`, `confidence_score`, and `payload`.

If no meaningful improvements can be made, return an empty `drafts` list with a decision explaining why.
