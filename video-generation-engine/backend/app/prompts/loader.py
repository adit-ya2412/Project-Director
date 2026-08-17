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


@lru_cache
def load_style_fragment(agent: str, style: str | None) -> str | None:
    """`None` (not `FileNotFoundError`) when `style` is `None` or has no
    fragment file for `agent` - deliberately different from `load_prompt`
    above. §4.3's own reasoning: not every style needs planner-specific
    wording for every planner (plan §2.8 - three styles, four planners,
    twelve possible pairs, most of which are "behave exactly like the
    unstyled default"). A missing fragment means "this planner's base
    prompt already does the right thing for this style", not a
    configuration mistake to raise on. Composed at call time
    (`base_prompt + fragment`) by the caller, never cached as one
    combined string here, so `load_prompt`'s own cache entry for the
    base prompt stays shared and correct across every style."""
    if style is None:
        return None
    path = _PROMPTS_ROOT / f"{agent}_styles" / f"{style}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()
