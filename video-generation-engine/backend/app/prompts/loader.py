"""Prompt loading. Prompts live as plain-text files under `app/prompts/`,
never as string literals in Python (implementation guide, Phase M5 advice)
- editing a prompt should never require touching planner logic, and a
diff on a prompt file should be reviewable on its own.
"""

from functools import lru_cache
from pathlib import Path

_PROMPTS_ROOT = Path(__file__).resolve().parent


@lru_cache
def load_prompt(agent: str, version: str) -> str:
    path = _PROMPTS_ROOT / agent / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt file for agent={agent!r} version={version!r}")
    return path.read_text(encoding="utf-8").strip()
