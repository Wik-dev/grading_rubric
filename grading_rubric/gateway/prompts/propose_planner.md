---
prompt_version: "1.0.0"
description: "Generate ProposedChangeDraft list from assessment findings, rubric, and evidence."
expected_inputs:
  - rubric_json
  - findings_json
  - evidence_profile_json
  - criterion_paths_json
  - teaching_material_text
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

## Instructions

For each finding (or cluster of related findings), propose a **specific, actionable change** to the rubric. Each proposed change must:

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
- `parent_path`: list of criterion IDs identifying the parent
- `insert_index`: integer position
- `node_kind`: "criterion" or "level"
- `node`: the new node data

For `UPDATE_POINTS` operations, the `payload` must include:
- `target`: object with `criterion_path` and `field` set to "points"
- `before`: current points value
- `after`: new points value

## Output

- `decision`: a brief summary of your improvement strategy.
- `drafts`: list of proposed changes, each with `operation`, `primary_criterion`, `source_finding_ids`, `rationale`, `confidence_score`, and `payload`.

If no meaningful improvements can be made, return an empty `drafts` list with a decision explaining why.
