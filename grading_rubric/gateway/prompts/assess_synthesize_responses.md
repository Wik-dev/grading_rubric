---
prompt_version: "2.0.0"
description: "Generate adversarial synthetic student responses for rubric validation."
expected_inputs:
  - rubric_text
  - exam_question_text
  - teaching_material_text
  - tier_count
expected_output_schema_id: "SynthesizedResponseSet"
---
You are a teaching assistant generating synthetic student responses for rubric validation. Given the exam question, teaching material, and rubric, produce responses that stress-test rubric boundaries. The goal is a small adversarial cohort that exposes ceiling effects, weak discrimination, ambiguity, and applicability problems.

## Exam question

{exam_question_text}

## Teaching material

{teaching_material_text}

## Rubric

{rubric_text}

## Task

Generate {tier_count} synthetic student responses across this ordered tier list:

1. `very_weak`, intended_score around 0.02
2. `weak`, intended_score around 0.05
3. `below_average`, intended_score around 0.10
4. `average`, intended_score around 0.25
5. `above_average`, intended_score around 0.40
6. `strong`, intended_score around 0.55
7. `excellent`, intended_score around 0.70

If `{tier_count}` is smaller than 7, choose a spread from low, borderline, and high tiers. If `{tier_count}` is larger than 7, add adversarial variants with a numeric suffix, but keep their intended score ordered.

**CRITICAL — ceiling-killing calibration strategy:**

The biggest problem in rubric validation is the **ceiling effect**: responses from above_average through excellent all score near 1.0, making the rubric useless for distinguishing quality. To break this ceiling, the ENTIRE quality ladder is shifted down aggressively. Even the `excellent` tier should NOT be a perfect answer — it should be the best of a weak cohort, with visible flaws that a strong rubric can detect.

You have access to the exam question, teaching material, and rubric above. But for each tier, you must simulate a student with a **specific level of access and ability**:

### Tier definitions (MANDATORY — follow exactly)

**`very_weak` (intended_score ~0.02, target grade 0.00-0.05):**
Simulate a student who **cannot read the exam question and did not study**. Generate a random, incoherent text of random length (10-40 words) that has NOTHING to do with the exam topic. It could be about cooking, sports, a dream, song lyrics, or complete gibberish. Do NOT reference any concept from the exam, teaching material, or rubric. This is a pure noise floor.

**`weak` (intended_score ~0.05, target grade 0.00-0.10):**
Simulate a student who **did not study and has very poor vocabulary**. The student glanced at the exam paper but can barely write. Generate a wrong answer in exactly 3-5 words. The words should vaguely relate to the exam topic but form no coherent answer. Example patterns: "bad people do things", "computers are dangerous maybe", "hackers money politics yes".

**`below_average` (intended_score ~0.10, target grade 0.05-0.15):**
Simulate a student who **did not study at all** but tries to write something. Generate a completely nonsensical answer (30-80 words) that uses some words from the exam question but arranges them into incoherent, rambling sentences with no logical structure. The student is guessing wildly. No correct categories, no valid actions, no real understanding. May mix in unrelated topics. Example: "The SmartCity is about cities being smart and technology is important for people because when bad things happen it is not good for the community and we need to think about how to make it better with IoT and stuff."

**`average` (intended_score ~0.25, target grade 0.15-0.35):**
This is what a `very_weak` student used to look like. The student **did not study** but can read the question and tries to answer it. They misunderstand the question entirely or give a non-answer:
- Describes normal system costs, design challenges, or accidents instead of malicious attacks.
- Talks about project management, budgets, or user complaints — not security threats.
- Gives one vague sentence about "bad actors" with no specifics.
- Copies/paraphrases the question back without adding content.
- Does NOT correctly identify any motivation category. Does NOT name a plausible attack vector.
- 30-80 words. May trail off.

**`above_average` (intended_score ~0.40, target grade 0.30-0.50):**
This is what a `weak` student used to look like. The student **studied very little** and is confused about what the rubric is asking:
- At most one partly plausible rubric item — and even that item should have something wrong (wrong category label, generic harm, or action that doesn't match the system).
- At least one item that is clearly off-topic, nonsensical, or answers a different question.
- At least one explicit wrong category label (e.g., label says "Money" but the described action is clearly ideology-driven).
- No more than one concrete scenario component across the whole answer.
- Mostly generic harms ("this is bad", "people are affected") with no mechanism.
- The student is CONFUSED, not just lazy. They misunderstand what the rubric is asking for.
- Include hedging phrases: "maybe", "I think", "it could be".
- 100-200 words. The student writes more, not less, because they are unsure.

**`strong` (intended_score ~0.55, target grade 0.45-0.65):**
This is what a `below_average` student used to look like. The student studied a bit but has gaps:
- One item can be mostly correct.
- One item should be partial, vague, or only loosely scenario-specific.
- One item must be clearly flawed, missing, repeated, or category-mismatched.
- Include no more than two concrete scenario components across the whole answer.
- Do NOT include three concrete harms or three clean stakeholder consequences.
- Include at least one substantive conceptual error (wrong category, wrong stakeholder, wrong system component).
- 100-200 words. Include some hedging and padding.

**`excellent` (intended_score ~0.70, target grade 0.60-0.80):**
This is what an `average` student used to look like. The student studied and understands the basics but has clear weaknesses:
- Two plausible items at most.
- One item must be clearly flawed, not merely less detailed.
- Include one visible category mismatch, missing actor, generic consequence, or no scenario connection.
- Do NOT make all three items sound technically feasible and well adapted to the scenario.
- 100-200 words.

**IMPORTANT:** Even the `excellent` response should NOT score above 0.80 on a well-functioning rubric. It has visible, substantive flaws. This is by design — real student answers in the response set provide the upper range. The synthetic cohort's job is to stress-test the lower-to-mid range where discrimination matters most.

### Hard constraints

Use these score bands as hard calibration targets:

- `very_weak` should grade in 0.00-0.05. Random noise = zero credit.
- `weak` should grade in 0.00-0.10. Three wrong words = near-zero credit.
- `below_average` should grade in 0.05-0.15. Nonsensical rambling = near-zero credit.
- `average` should grade in 0.15-0.35. If it would grade above 0.40, it is too competent and must be rewritten.
- `above_average` should grade in 0.30-0.50. If it would grade above 0.55, it is too competent and must be rewritten.
- `strong` should grade in 0.45-0.65. If it would grade above 0.70, it is too competent and must be rewritten.
- `excellent` should grade in 0.60-0.80. If it would grade above 0.85, it is too competent and must be rewritten.

If the rubric asks for multiple repeated items (N examples, N actions, N arguments, etc.), enforce these constraints:

- `very_weak`: no items. Random text.
- `weak`: no items. Three wrong words.
- `below_average`: no coherent items. Nonsensical text with exam keywords.
- `average`: satisfy ZERO required items correctly. Off-topic or non-answer.
- `above_average`: satisfy at most one required item partially (not fully). Rest missing, wrong, or off-topic.
- `strong`: satisfy fewer than half of the required items fully. One OK, one partial, one wrong/missing.
- `excellent`: satisfy about half of the required items fully. Two plausible, one clearly flawed.

Reject and rewrite any `above_average`, `strong`, or `excellent` response that contains all of the following:

- three labelled items;
- three plausible actors, examples, arguments, or actions;
- three scenario-specific components or details;
- three concrete consequences or harms.

That response is too strong for any synthetic tier. The synthetic cohort tests the LOWER half of the quality spectrum. Real student answers test the upper half.

### Style constraints

For `average` through `strong`, write as a struggling student:
- confused terminology, missing or inconsistent labels, incomplete sentences;
- generic words like "bad", "dangerous", "problem", "thing", "people";
- hedging phrases: "maybe", "I think", "it could be";
- answering a related but different question;
- vague actors like "some people" without malicious motivation;
- wrong or missing scenario components.

For `excellent`, the student can be clearer but must still have one substantive flaw (wrong category, repeated action, generic harm, or missing scenario connection).

### Required category-mismatch sentinel

If the rubric or exam asks students to match actions/examples to categories or labels, include at least one `above_average` or `strong` response with an **explicit wrong label**. The mismatch must be obvious: label an item with category X but describe content that clearly belongs to category Y.

### Self-check

Before returning, check each synthetic response against the rubric and these bands. If any response would grade ABOVE its band ceiling, rewrite it to be WORSE. Include a top-level `self_check_notes` string summarizing the calibration check.

Each response should be:

1. **Realistic** — written as a plausible student at that level would write.
2. **Distinct** — the quality difference between tiers should be clearly visible.
3. **Tier-labelled** — use the exact tier labels above.
4. **Calibrated** — no synthetic response should score above 0.80 on a well-functioning rubric.
5. **Adversarial** — the `above_average` through `excellent` responses should target specific rubric edge cases (borderline categories, wrong labels, generic impacts, similar actions, partial quality).

For each response, provide:
- `tier`: the quality tier label.
- `text`: the full synthetic student response.
- `intended_score`: a rough 0.0–1.0 overall score this response should receive under a well-functioning rubric.

For the response set, provide:
- `responses`: the list of synthetic responses.
- `self_check_notes`: a brief audit note describing the calibration check and any rewrites performed.
