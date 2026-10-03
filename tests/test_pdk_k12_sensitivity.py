from __future__ import annotations

import pytest

from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage
from orfadc.experiments.audit_pdk_k12_sensitivity import (
    _NEW, _OLD, require_single_k12_change,
)


def test_k12_derivative_requires_exactly_one_coupling_change() -> None:
    original = render_teaching_three_stage()
    source = original.decode("ascii")
    assert source.count(_OLD) == 1
    require_single_k12_change(original, source.replace(_OLD, _NEW, 1).encode("ascii"))


def test_k12_derivative_rejects_other_edits() -> None:
    original = render_teaching_three_stage()
    source = original.decode("ascii")
    with pytest.raises(ValueError, match="exactly one K12"):
        require_single_k12_change(original, source.encode("ascii"))
    with pytest.raises(ValueError, match="exactly one K12"):
        require_single_k12_change(
            original,
            source.replace(_OLD, _NEW, 1).replace("r=1787", "r=50", 1).encode("ascii"),
        )


def test_k12_derivative_rejects_missing_original_line() -> None:
    source = render_teaching_three_stage().decode("ascii").replace(_OLD, _NEW, 1)
    with pytest.raises(ValueError, match="exactly one K12"):
        require_single_k12_change(source.encode("ascii"), source.encode("ascii"))
