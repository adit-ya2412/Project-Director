"""Parse ffmpeg ebur128 filter stderr.

Shared by the OQ-0a report (`metrics.py`) and the OQ-1c pre-concat
level match (`audio.py`). This module is the allowed render-path
dependency; `metrics.build_render_metrics_report` still must not be.
"""

from __future__ import annotations

import re

_EBUR128_I_RE = re.compile(
    r"^\s*I:\s*([-+]?\d+(?:\.\d+)?)\s+LUFS\s*$", re.MULTILINE | re.IGNORECASE
)
_EBUR128_LRA_RE = re.compile(
    r"^\s*LRA:\s*([-+]?\d+(?:\.\d+)?)\s+LU\s*$", re.MULTILINE | re.IGNORECASE
)
# Some builds label the true-peak line "Peak:"; others "True peak:".
_EBUR128_PEAK_RE = re.compile(
    r"^\s*(?:True\s+peak|Peak):\s*([-+]?\d+(?:\.\d+)?)\s+dB(?:FS|TP)?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def parse_ebur128_summary(stderr: str) -> dict[str, float] | None:
    """Extract integrated LUFS / true peak / LRA from an ebur128 Summary."""
    summary_idx = stderr.rfind("Summary:")
    region = stderr[summary_idx:] if summary_idx >= 0 else stderr
    i_match = _EBUR128_I_RE.search(region)
    lra_match = _EBUR128_LRA_RE.search(region)
    peak_match = _EBUR128_PEAK_RE.search(region)
    if not (i_match and lra_match and peak_match):
        return None
    return {
        "integrated_lufs": float(i_match.group(1)),
        "true_peak_db": float(peak_match.group(1)),
        "lra": float(lra_match.group(1)),
    }
