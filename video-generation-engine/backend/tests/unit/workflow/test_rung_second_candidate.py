"""Pure classifier for §18.5 / RV-Q22 rate reporting. No DB, no API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from measure_rung_second_candidate import cell_kind  # noqa: E402


def test_cell_kind_stable_and_mixed():
    assert cell_kind(0, 3) == "pass"
    assert cell_kind(3, 3) == "reject"
    assert cell_kind(1, 3) == "MIXED"
    assert cell_kind(2, 3) == "MIXED"
