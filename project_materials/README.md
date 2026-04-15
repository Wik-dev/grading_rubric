# Project Materials

Input files for the Grading Rubric Studio pipeline.

| File | Role | CLI flag |
|------|------|----------|
| `ExamQuestionAndRubric.pdf` | Exam question and existing rubric | `--exam-question`, `--starting-rubric` |
| `TeachingResource-BAD_ACTORS_STRATEGY.pdf` | Teaching material for grounding | `--teaching-material` |
| `StudentAnswer-Student1.pdf` | Student response (handwritten) | `--student-copy` |
| `StudentAnswer-Student2.pdf` | Student response (handwritten) | `--student-copy` |
| `StudentAnswer-Student3.pdf` | Student response (handwritten) | `--student-copy` |

## Quick start

```bash
grading-rubric-cli run-pipeline \
    --exam-question project_materials/ExamQuestionAndRubric.pdf \
    --teaching-material project_materials/TeachingResource-BAD_ACTORS_STRATEGY.pdf \
    --starting-rubric project_materials/ExamQuestionAndRubric.pdf \
    --student-copy project_materials/StudentAnswer-Student1.pdf \
    --student-copy project_materials/StudentAnswer-Student2.pdf \
    --student-copy project_materials/StudentAnswer-Student3.pdf \
    --output result.json
```
