# Grading Rubric Studio

An AI-powered application that assesses and improves the quality of grading rubrics for large-class exams. Given an exam question and (optionally) teaching materials, an existing rubric, and student copies, the system produces an improved rubric with an explanation of changes against three quality criteria: **Ambiguity**, **Applicability**, and **Discrimination Power**.

## Quick start

### Prerequisites

- Python 3.11+
- An Anthropic API key (Claude)

### Install

```bash
pip install .
```

### Run

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

grading-rubric-cli run-pipeline \
    --exam-question ExamQuestionAndRubric.pdf \
    --teaching-material TeachingResource-BAD_ACTORS_STRATEGY.pdf \
    --student-copy StudentAnswer-Student1.pdf \
    --student-copy StudentAnswer-Student2.pdf \
    --student-copy StudentAnswer-Student3.pdf \
    --output result.json
```

Only `--exam-question` is required. All other inputs are optional:

| Flag | Description |
|------|-------------|
| `--exam-question` | Exam question (PDF, DOCX, or text file) |
| `--teaching-material` | Teaching material for grounding (repeatable) |
| `--starting-rubric` | Existing rubric to improve (PDF, DOCX, or text) |
| `--starting-rubric-inline` | Existing rubric as inline text or JSON |
| `--student-copy` | Student response for discrimination analysis (repeatable) |
| `--output` | Where to write the output JSON |

### Output

The output is a single JSON file (`ExplainedRubricFile`) containing:

- `improved_rubric` — the improved rubric with criteria, levels, and point allocations
- `proposed_changes` — each change proposed by the system, with rationale and application status
- `quality_scores` — per-criterion scores (ambiguity, applicability, discrimination power) with confidence indicators
- `explanation` — teacher-facing narrative explaining the changes and the evidence behind them
- `evidence_profile` — what inputs were available and how they were used
- `starting_rubric` — the original rubric (if one was provided), for comparison

### Per-stage invocation

Each pipeline stage can also be run individually for inspection:

```bash
grading-rubric-cli ingest       --input ingest_inputs.json --output ingest_outputs.json
grading-rubric-cli parse-inputs --input ingest_outputs.json --output parsed_inputs.json
grading-rubric-cli assess       --input parsed_inputs.json  --output assess_outputs.json
grading-rubric-cli propose      --input assess_outputs.json --output propose_outputs.json
grading-rubric-cli score        --input propose_outputs.json --output score_outputs.json
grading-rubric-cli render       --input score_outputs.json   --output explained_rubric.json
```

### Docker

```bash
docker build -t grading-rubric:latest -f docker/grading-rubric/Dockerfile .

docker run -e ANTHROPIC_API_KEY \
    -v "$(pwd)":/work \
    grading-rubric:latest \
    grading-rubric-cli run-pipeline \
        --exam-question ExamQuestionAndRubric.pdf \
        --output result.json
```

### Configuration

All settings are via environment variables (defaults are sensible):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required) |
| `GR_LLM_BACKEND` | `anthropic` | LLM backend (`anthropic`, `openai`, `stub`) |
| `GR_LLM_MODEL` | `claude-sonnet-4-6-20251001` | Model identifier |
| `GR_LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `GR_SCORER_BACKEND` | `llm_panel` | Scorer backend (`llm_panel`, `trained_model`) |

### Tests

```bash
pip install ".[dev]"
pytest
```

## Documentation

- [Requirements](docs/requirements.md) — User needs, user requirements, system requirements
- [Design](docs/design.md) — Architecture, data models, design requirements
- [UI Draft](docs/ui-draft.md) — SPA screen designs
- [Verification Plan](docs/verification-plan.md) — Test strategy and procedures
