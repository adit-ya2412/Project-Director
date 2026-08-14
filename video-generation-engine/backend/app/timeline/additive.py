"""Additive-only enforcement for Timeline mutations (implementation guide,
Phase M3 advice: "enforce additive-only in code, not by convention").

A planner may only:
  - fill a field that was previously null/empty, or
  - freely modify a field it has explicitly declared ownership of (`owns`).

Anything else - a previously-populated field changing value, or
disappearing - is a bug in the calling planner, caught here rather than
silently corrupting the Timeline.

Works on plain JSON-shaped dicts (the output of `Timeline.model_dump(mode="json")`
on both sides), never on live Pydantic objects, so the comparison is
apples-to-apples regardless of how each side was constructed.
"""

from typing import Any

_EMPTY: tuple[Any, ...] = (None, "", [], {})


def _is_owned(path: str, owns: frozenset[str]) -> bool:
    """A path is owned if it, or any of its ancestor paths, is declared
    in `owns`. Owning "scenes" means owning everything under scenes."""
    parts = path.split(".")
    return any(".".join(parts[: i + 1]) in owns for i in range(len(parts)))


def find_additive_violations(old: Any, new: Any, owns: frozenset[str], path: str = "") -> list[str]:
    violations: list[str] = []

    if isinstance(old, dict) and isinstance(new, dict):
        for key, old_value in old.items():
            child_path = f"{path}.{key}" if path else key
            if key not in new:
                if old_value not in _EMPTY and not _is_owned(child_path, owns):
                    violations.append(f"{child_path}: field removed")
                continue
            violations.extend(find_additive_violations(old_value, new[key], owns, child_path))
        return violations

    if isinstance(old, list) and isinstance(new, list):
        if old and old != new and not _is_owned(path, owns):
            violations.append(
                f"{path}: list changed ({len(old)} -> {len(new)} items, or reordered)"
            )
        return violations

    if old not in _EMPTY and old != new and not _is_owned(path, owns):
        violations.append(f"{path}: {old!r} -> {new!r}")

    return violations
