from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import summarize_teaching_matching as module


def _run(root: Path, name: str, ldd_nh: float, cblock_ff: float, *, extra: str = "") -> Path:
    run = root / name
    run.mkdir()
    (run / "netlist.scs").write_text(
        f"parameters VDD=1.2 VBIAS=0.65 WMOS=300u LMOS=100n LGS=1n LSS=240p LDD={ldd_nh}n\n"
        f"CBLOCK (drain out) capacitor c={cblock_ff}f\n{extra}", encoding="ascii",
    )
    (run / "sp.sp").write_text("mock", encoding="ascii")
    (run / "evidence_manifest.json").write_text("mock", encoding="ascii")
    return run


def test_matching_summary_requires_same_source_and_evidenced_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _run(tmp_path, "run_a", 2, 5000)
    right = _run(tmp_path, "run_b", 13, 20)
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(
        module, "audit_teaching_lna",
        lambda _: {"metrics": {"s11_db": -5, "s21_db": 10, "s22_db": -1,
                                "ripple_db": 3, "nf_db": 2, "supply_current_ma": 4},
                   "stability": {"minimum_k": 1.1, "maximum_delta_abs": 0.9}},
    )
    monkeypatch.setattr(
        module, "read_evidenced_metrics",
        lambda run: {"design_parameters": {"vbias_v": 0.65,
                                           "ldd_nh": 2 if run == left else 13,
                                           "cblock_ff": 5000 if run == left else 20}},
    )
    monkeypatch.setattr(
        module, "parse_complex_trace",
        lambda path, name: ([8e9, 10e9, 12e9], [0.5 + 0j, 0.25 + 0j, 0.5 + 0j]),
    )
    output = tmp_path / "summary"
    result = module.summarize_teaching_matching([right, left], output)
    assert [row["ldd_nh"] for row in result["rows"]] == [2.0, 13.0]
    assert result["rows"][0]["s22_10_db"] == pytest.approx(-12.041199826559248)
    assert result["spec_pass"] is None and result["not_lna_result"] is True
    assert read_evidenced_metrics(output) == result


def test_matching_summary_rejects_other_topology_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _run(tmp_path, "run_a", 2, 5000)
    right = _run(tmp_path, "run_b", 13, 20, extra="R1 (a b) resistor r=1k\n")
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(
        module, "audit_teaching_lna",
        lambda _: {"metrics": {"s11_db": -5, "s21_db": 10, "s22_db": -1,
                                "ripple_db": 3, "nf_db": 2, "supply_current_ma": 4},
                   "stability": {"minimum_k": 1.1, "maximum_delta_abs": 0.9}},
    )
    monkeypatch.setattr(
        module, "read_evidenced_metrics",
        lambda run: {"design_parameters": {"vbias_v": 0.65,
                                           "ldd_nh": 2 if run == left else 13,
                                           "cblock_ff": 5000 if run == left else 20}},
    )
    monkeypatch.setattr(
        module, "parse_complex_trace",
        lambda path, name: ([8e9, 10e9, 12e9], [0.5 + 0j] * 3),
    )
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="netlists differ"):
        module.summarize_teaching_matching([left, right], output)
    assert not output.exists()
