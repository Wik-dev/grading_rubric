"""DR-LLM-02 *PromptRegistry*.

Prompts live in `grading_rubric/gateway/prompts/<prompt_id>.md` as markdown
files with YAML front-matter (`prompt_version`, `description`, `expected_inputs`,
`expected_output_schema_id`). The gateway loads them once at boot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from grading_rubric.audit.hashing import hash_text


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    template: str
    metadata: dict[str, Any]


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_one(path: Path) -> Prompt:
    raw = path.read_text(encoding="utf-8")
    front: dict[str, Any] = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end > 0:
            front = yaml.safe_load(raw[3:end]) or {}
            body = raw[end + 4 :].lstrip()
    return Prompt(
        prompt_id=path.stem,
        prompt_version=str(front.get("prompt_version", "0.0.0")),
        prompt_hash=hash_text(raw),
        template=body,
        metadata=front,
    )


class PromptRegistry:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or _PROMPTS_DIR
        self._cache: dict[str, Prompt] = {}
        if self._dir.exists():
            for p in sorted(self._dir.glob("*.md")):
                prompt = _load_one(p)
                self._cache[prompt.prompt_id] = prompt

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self._cache:
            # Synthesize a fallback prompt so the gateway can still record an
            # operation event with a prompt_hash; useful for tests and CI runs
            # where prompt files are not yet authored.
            template = f"Synthetic prompt for {prompt_id}"
            return Prompt(
                prompt_id=prompt_id,
                prompt_version="0.0.0-synthetic",
                prompt_hash=hash_text(template),
                template=template,
                metadata={},
            )
        return self._cache[prompt_id]

    def render(self, prompt_id: str, inputs: dict[str, Any]) -> tuple[Prompt, str]:
        """Render `prompt.template` against `inputs` using simple `{key}` substitution.

        Missing keys are tolerated and left as-is. The renderer is intentionally
        minimal — DR-LLM-02 does not require Jinja-style features.
        """

        prompt = self.get(prompt_id)
        try:
            rendered = prompt.template.format(**inputs)
        except (KeyError, IndexError):
            rendered = prompt.template
        return prompt, rendered
