from __future__ import annotations

from pathlib import Path

import pytest

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments import export_teaching_device_lookup as module


_OP = {
    "ids": 0.001, "vgs": 0.55, "vds": 1.2, "vth": 0.45, "vdsat": 0.1,
    "gm": 0.02, "gds": 1e-5, "cgs": 2e-13, "cgd": 0.0,
}


def _source(root: Path, name: str, bias: float, *, width: str = "300u", length: str = "100n") -> Path:
    run = root / name
    run.mkdir()
    (run / "netlist.scs").write_text(
        f"parameters VDD=1.2 VBIAS={bias} WMOS={width} LMOS={length} LGS=1n LSS=240p LDD=2n\n"
        "model n_teach mos1 type=n vto=0.45 kp=80u lambda=0.03 tox=3n \\\n"
        "    gamma=0 capmod=bsim cgso=0 cgdo=0 tnom=27\n"
        "M1 (drain gate source 0) n_teach w=WMOS l=LMOS\n",
        encoding="ascii",
    )
    (run / "sp.sp").write_text("mock", encoding="ascii")
    (run / "evidence_manifest.json").write_text("mock", encoding="ascii")
    return run


def test_device_lookup_requires_audited_op_and_fixed_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _source(tmp_path, "run_a", 0.5)
    right = _source(tmp_path, "run_b", 0.55)
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(
        module, "audit_teaching_lna",
        lambda run: {"device_op": {**_OP, "vgs": 0.5 if run == left else 0.55}},
    )
    monkeypatch.setattr(
        module, "read_evidenced_metrics",
        lambda run: {"design_parameters": {"vbias_v": 0.5 if run == left else 0.55}},
    )
    monkeypatch.setattr(module, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    output = tmp_path / "lookup"
    result = module.export_teaching_device_lookup([right, left], output)
    assert result["status"] == "single_device_characterization"
    assert [row["vgs_v"] for row in result["rows"]] == [0.5, 0.55]
    assert result["rows"][0]["gm_over_id_v_inv"] == 20.0
    assert "stage" not in result["rows"][0]
    assert read_evidenced_metrics(output) == result
    bad = _source(tmp_path, "run_c", 0.6, length="200n")
    with pytest.raises(ValueError, match="netlists differ"):
        module.export_teaching_device_lookup([left, bad], tmp_path / "bad_geometry")
    assert not (tmp_path / "bad_geometry").exists()


def test_device_lookup_accepts_distinct_widths_at_same_bias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _source(tmp_path, "run_a", 0.55, width="200u")
    right = _source(tmp_path, "run_b", 0.55, width="400u")
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "audit_teaching_lna", lambda run: {"device_op": _OP})
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda run: {
        "design_parameters": {"vbias_v": 0.55, "wmos_um": 400 if run == right else 200}
    })
    monkeypatch.setattr(module, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    output = tmp_path / "lookup"
    result = module.export_teaching_device_lookup([right, left], output)
    assert result["status"] == "multi_width_characterization"
    assert result["widths_um"] == [200.0, 400.0]
    assert [row["w_um"] for row in result["rows"]] == [200.0, 400.0]
    assert read_evidenced_metrics(output) == result
    duplicate = _source(tmp_path, "run_c", 0.55, width="200u")
    with pytest.raises(ValueError, match="duplicated"):
        module.export_teaching_device_lookup([left, duplicate], tmp_path / "duplicate")


def test_device_lookup_rejects_missing_op_before_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _source(tmp_path, "run_a", 0.5)
    right = _source(tmp_path, "run_b", 0.55)
    monkeypatch.setattr(module, "_require_private_path", lambda _: None)
    monkeypatch.setattr(module, "audit_teaching_lna", lambda run: {"status": "verified"})
    output = tmp_path / "missing_op"
    with pytest.raises(ValueError, match="operating-point data"):
        module.export_teaching_device_lookup([left, right], output)
    assert not output.exists()
