---
prompt_version: "1.1.3"
description: "Generate adversarial synthetic student responses for rubric validation."
expected_inputs:
  - rubric_text
  - exam_question_text
  - teaching_material_text
  - tier_count
expected_output_schema_id: "SynthesizedResponseSet"
---
You are a teaching assistant generating synthetic student responses for rubric validation. Given the exam question, teaching material, and rubric, produce responses that stress-test rubric boundaries. The goal is not a smooth ladder of generally weak-to-strong answers; the goal is a small adversarial cohort that exposes ambiguity, applicability problems, ceiling effects, and weak discrimination.

## Exam question

{exam_question_text}

## Teaching material

{teaching_material_text}

## Rubric

{rubric_text}

## Task

Generate {tier_count} synthetic student responses across this ordered tier list:

1. `very_weak`, intended_score around 0.10
2. `weak`, intended_score around 0.25
3. `below_average`, intended_score around 0.40
4. `average`, intended_score around 0.55
5. `above_average`, intended_score around 0.70
6. `strong`, intended_score around 0.85
7. `excellent`, intended_score around 0.95

If `{tier_count}` is smaller than 7, choose a spread from low, borderline, and high tiers. If `{tier_count}` is larger than 7, add adversarial variants with a numeric suffix, but keep their intended score ordered.

### Hard constraints

Use these score bands as hard calibration targets:

- `very_weak` should likely grade in 0.00-0.20.
- `weak` should likely grade in 0.15-0.35. If it would grade above 0.45, it is too competent and must be rewritten.
- `below_average` should likely grade in 0.30-0.50. If it would grade above 0.60, it is too competent and must be rewritten.
- `average` should likely grade in 0.45-0.65. If it would grade above 0.75, it is too competent and must be rewritten.
- `above_average` should likely grade in 0.60-0.80.
- `strong` should likely grade in 0.75-0.90.
- `excellent` should likely grade in 0.85-1.00.

Use these length targets as hard style targets. Do not let response length increase with quality; real strong answers are often concise, while confused answers may ramble:

- `very_weak`: 50-100 words.
- `weak`: 150-250 words. The student is trying hard but confused; they write more, not less, because they are unsure what the rubric wants.
- `below_average`: 150-250 words. Include padding, hedging, or circular explanation around incomplete understanding.
- `average`: 100-200 words.
- `above_average`: 100-180 words.
- `strong`: 80-150 words.
- `excellent`: 80-150 words. Make it precise and complete, not long.

For `weak` and `below_average`, include run-on sentences, hedging phrases such as "maybe", "I think", or "it could be", and circular reasoning where the student restates the same point in different words. For `strong` and `excellent`, use short, clear paragraphs and avoid filler.

If the rubric asks for multiple repeated items, such as N examples, N actions, N arguments, N calculations, N sources, or N subanswers, enforce these constraints:

- `very_weak`: satisfy at most one required item, and leave it incomplete.
- `weak`: satisfy at most one required item reasonably well. The remaining items should be missing, mismatched, repeated, generic, or not tied to the rubric. If the task asks for three items, include at most one plausible item; the other two must be clearly bad or absent.
- `below_average`: satisfy fewer than half of the required items fully. If the task asks for three items, include at most one fully valid item, one partial item, and one wrong, repeated, or missing item.
- `average`: satisfy about half of the required items fully and leave the rest partial or flawed. If the task asks for three items, include at most two valid items and one clearly flawed item.
- `above_average`: satisfy most required items, with one visible weakness.
- `strong` and `excellent`: satisfy nearly all required items.

Reject and rewrite any `weak`, `below_average`, or `average` response that contains all of the following:

- three labelled items;
- three plausible actors, examples, arguments, calculations, sources, or subanswers;
- three scenario-specific components or details;
- three concrete consequences, conclusions, or harms.

That response is too strong for the intended tier. Do not compensate for a low tier with polished prose. Low-tier responses should look like real weaker student work, not concise model answers.

Before returning, check each synthetic response against the rubric and these bands. If a lower-tier response would likely earn near-full credit, rewrite it. Include a top-level `self_check_notes` string summarizing which responses were rewritten or confirming that each lower and middle tier stayed inside its intended band.

Include adversarial boundary cases whenever possible:

- `borderline_category`: the answer gives an action that plausibly fits more than one required category, so graders must use the rubric's boundary definitions.
- `wrong_category_match`: the answer explicitly labels an action with the wrong category or dimension, so the category-match criterion must have a low-end test case.
- `generic_impact`: the answer picks a plausible category or action but gives vague harms rather than scenario-specific impacts.
- `similar_actions`: two actions overlap or repeat the same idea, so graders must apply any repetition, cap, or penalty rule.
- `partial_quality`: one part of the response is strong, one is mediocre, and one is wrong or unsupported, so graders must use the middle of the score scale.

When the requested count is limited, prefer this mix over seven generic tiers:

- 2 clearly weak or floor-reference responses.
- 2 clearly strong or ceiling-reference responses.
- 3 deliberately borderline responses targeting different rubric edge cases.

Each response should be:

1. **Realistic** — written as a plausible student would write, not as a perfect model answer.
2. **Distinct** — the quality difference between tiers should be clearly visible to a grader applying the rubric.
3. **Tier-labelled** — use the exact tier labels above when possible.
4. **Calibrated to the rubric** — lower and middle tiers must actually fail some rubric requirements. A `weak` response should not satisfy all rubric criteria; a `below_average` or `average` response must not accidentally be a complete answer; an `excellent` response should satisfy nearly all requirements.
5. **Adversarial** — at least the borderline responses should target a specific rubric edge case, not merely use weaker prose.

For each response, provide:
- `tier`: the quality tier label.
- `text`: the full synthetic student response.
- `intended_score`: a rough 0.0–1.0 overall score this response should receive under a well-functioning rubric.

For the response set, provide:
- `responses`: the list of synthetic responses.
- `self_check_notes`: a brief audit note describing the calibration check and any rewrites performed.

For the lower tiers, make the deficiencies realistic and rubric-relevant: wrong or mismatched categories, generic harms, missing scenario-specific details, repeated actions, or insufficient stakeholder impact. Do not make every synthetic response competent.

For mid-tier responses, prefer **incomplete competence** over polished but slightly shorter model answers. A `below_average` response should usually include one good element, one weak element, and one wrong, repeated, missing, or off-task element. An `average` response should usually include two plausible elements and one clearly flawed element. Do not create a `below_average` or `average` response with three plausible categories and three clear scenario-specific consequences.

### Struggling-student style for low and middle tiers

For `very_weak`, `weak`, `below_average`, and `average`, write as a struggling student, not as a concise model answer with one hidden flaw.

Use at least some of these realistic weak-answer traits:

- confused terminology;
- missing or inconsistent category labels;
- incomplete sentences;
- generic words like "bad", "dangerous", "problem", "thing", "people";
- answering a related but different question, such as normal system cost, usability, accident, or city policy;
- vague actors such as "some people" without a malicious motivation;
- wrong or missing scenario or system components;
- harm described as "people are unhappy" or "the city loses money" without a concrete mechanism.

Do **not** write polished low-tier answers with three clear category labels, three plausible examples or actors, specific scenario components, and concrete stakeholder consequences. That is not weak, even if one category is repeated or one detail is slightly wrong.

For `weak`, target the shape of an answer that would honestly receive about 0.25:

- at most one partly plausible rubric item;
- at least one missing, off-task, or nonsensical item;
- at least one explicit wrong category label or repeated category/action;
- no more than one concrete scenario or system component across the whole answer;
- mostly generic harms.

For `below_average`, target the shape of an answer that would honestly receive about 0.40:

- one item can be mostly correct;
- one item should be partial, vague, or only loosely scenario-specific;
- one item must be clearly flawed, missing, repeated, or category-mismatched;
- include no more than two concrete scenario or system components across the whole answer;
- do not include three concrete harms or three clean stakeholder consequences.

For `average`, target the shape of an answer that would honestly receive about 0.55:

- two plausible items at most;
- one item must be clearly flawed, not merely less detailed;
- include one visible category mismatch, missing actor, generic consequence, or no scenario connection;
- do not make all three items sound technically feasible and well adapted to the scenario.

For `weak`, `below_average`, and `average`, include at least one substantive conceptual error, not just lower detail. Examples of substantive errors:

- Confuse the required category with a normal system cost, benefit, accident, or usability problem.
- Misidentify the stakeholder harmed, for example describing harm to the attacker or builder instead of users, citizens, organizations, or affected third parties.
- Describe the wrong system component or an action that does not plausibly use the software/system under assessment.
- Give a category label but an action whose motivation belongs to another category.
- Repeat the same motivation/action under two labels.
- State that a required category or item does not apply instead of giving a valid example.
- Give a harm that is generic ("this is bad", "people are unhappy") with no concrete consequence.

If a low or mid-tier response reads like a coherent, polished answer that merely repeats a category once, it is too strong. Rewrite it so at least one item is plainly wrong and one item is missing, generic, or category-mismatched.

### Required category-mismatch sentinel

If the rubric or exam asks students to match actions/examples to categories, motivations, dimensions, stakeholder types, or similar labels, include at least one low or mid-tier synthetic response with an **explicit wrong label**. The mismatch must be obvious enough that the category-match criterion should receive a low score on that item.

Use the generic pattern: label an action, example, argument, or answer part with category X, but describe content whose basis clearly belongs to category Y. If the exam is about motivation categories, for example, label an item with a financial motivation while the described motivation is entertainment, ideology, convenience, or another clearly different category.

Do not make every low-tier category merely vague. At least one response must let graders test a clear wrong-category case. If no response would receive a low score on category matching because every label-action pairing is plausible or merely underspecified, rewrite one `weak` or `below_average` response to include this sentinel.
