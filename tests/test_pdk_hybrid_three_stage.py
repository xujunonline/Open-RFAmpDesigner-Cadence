from __future__ import annotations

import pytest

from orfadc.cadence.teaching_three_stage_netlist import render_teaching_three_stage
from orfadc.experiments.audit_pdk_hybrid_three_stage import validate_hybrid_topology


def test_hybrid_topology_contract_accepts_public_structural_analogue() -> None:
    validate_hybrid_topology(render_teaching_three_stage().decode("ascii"))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("PORT2 (outp outn) port r=1787", "PORT2 (outp outn) port r=50"),
        ("CL (outp outn) capacitor c=62f", "CL (outp outn) capacitor c=60f"),
        ("K23 mutual_inductor", "K23 inductor"),
        ("CN3N (", "C3N ("),
        ("M6 (", "X6 ("),
    ],
)
def test_hybrid_topology_contract_rejects_structural_changes(old: str, new: str) -> None:
    source = render_teaching_three_stage().decode("ascii")
    assert old in source
    with pytest.raises(ValueError, match="topology|inventory"):
        validate_hybrid_topology(source.replace(old, new, 1))
