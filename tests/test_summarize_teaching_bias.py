from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import summarize_teaching_bias as module


_METRICS = {
    "s11_db": -3.0, "s21_db": 1.0, "s22_db": -1.0, "ripple_db": 2.0,
    "nf_db": 3.0, "nfmin_db": 0.5, "supply_current_ma": 1.0,
    "supply_power_mw": 1.2, "points_in_band": 3,
}


def _source_dir(root: Path, name: str, bias: float, *, extra: str = "") -> Path:
    run = root / name
    run.mkdir()
    (run / "netlist.scs").write_text(
        f"parameters VDD=1.2 VBIAS={bias} WMOS=300u\n{extra}", encoding="ascii"
    )
    (run / "sp.sp").write_text("mock", encoding="ascii")
    (run / "evidence_manifest.json").write_text("mock", encoding="ascii")
    return run


def test_summary_requires_audited_same_template_grid_and_distinct_bias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _source_dir(tmp_path, "run_a", 0.5)
    right = _source_dir(tmp_path, "run_b", 0.6)
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(
        module, "audit_teaching_lna",
        lambda run: {"metrics": _METRICS},
    )
    monkeypatch.setattr(
        module, "read_evidenced_metrics",
        lambda run: {"design_parameters": {"vbias_v": 0.5 if run == left else 0.6}},
    )
    monkeypatch.setattr(module, "parse_complex_trace", lambda path, signal: ([1.0, 2.0], [1j, 2j]))
    output = tmp_path / "summary"
    result = module.summarize_teaching_bias([right, left], output)
    assert result["run_ids"] == ["run_a", "run_b"]
    assert result["frequency_points"] == 2
    assert result["not_lna_result"] is True and result["spec_pass"] is None
    assert read_evidenced_metrics(output) == result
    with pytest.raises(ValueError, match="distinct"):
        module.summarize_teaching_bias([left, left], tmp_path / "duplicate")
    assert not (tmp_path / "duplicate").exists()


def test_summary_rejects_mismatched_netlist_before_output_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _source_dir(tmp_path, "run_a", 0.5)
    right = _source_dir(tmp_path, "run_b", 0.6, extra="R1 (a b) resistor r=1k\n")
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "audit_teaching_lna", lambda run: {"metrics": _METRICS})
    monkeypatch.setattr(
        module, "read_evidenced_metrics",
        lambda run: {"design_parameters": {"vbias_v": 0.5 if run == left else 0.6}},
    )
    monkeypatch.setattr(module, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="netlists differ"):
        module.summarize_teaching_bias([left, right], output)
    assert not output.exists()
