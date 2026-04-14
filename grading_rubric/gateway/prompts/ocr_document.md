---
prompt_version: "1.0.0"
description: "Extract readable text from an attached document or image using vision."
expected_inputs:
  - role
  - source_name
  - context_text
  - extracted_text_hint
expected_output_schema_id: "OcrDocumentResult"
---
You are extracting text from an attached document for a grading-rubric workflow.

## Role

{role}

## Source filename

{source_name}

## Context

{context_text}

## Existing text-layer extraction, if any

{extracted_text_hint}

## Instructions

- Read the attached document or image directly.
- Preserve the meaning and structure needed by downstream grading.
- For student copies, transcribe the student's answer faithfully and preserve labels, bullets, paragraphs, equations, and corrections where readable.
- For teaching material, preserve category names, examples, arrows/overlaps, captions, and any diagram relationships in plain text. If a diagram has overlapping conceptual bubbles, write the overlap as explicit text.
- Use the existing text-layer extraction only as a hint. Correct it when the attachment shows a clearer reading.
- Do not summarize away details that a grader would need.
- If some content is unreadable, include it in `unreadable_regions` and mention it in `notes`.

Return `text`, `confidence`, `unreadable_regions`, and `notes`.
