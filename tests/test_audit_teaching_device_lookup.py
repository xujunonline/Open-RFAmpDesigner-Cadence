from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments import audit_teaching_device_lookup as auditor
from orfadc.experiments import export_teaching_device_lookup as exporter


_OP = {
    "ids": 0.001, "vgs": 0.55, "vds": 1.0, "vth": 0.45, "vdsat": 0.1,
    "gm": 0.02, "gds": 1e-5, "cgs": 2e-13, "cgd": 0.0,
}


def _source(root: Path, name: str, width: int, bias: float = 0.55) -> Path:
    run = root / name
    run.mkdir()
    (run / "netlist.scs").write_text(
        f"parameters VDD=1.2 VBIAS={bias} WMOS={width}u LMOS=100n LGS=1n LSS=240p LDD=2n\n"
        "model n_teach mos1 type=n vto=0.45 kp=80u lambda=0.03 tox=3n \\\n"
        "    gamma=0 capmod=bsim cgso=0 cgdo=0 tnom=27\n"
        "M1 (drain gate source 0) n_teach w=WMOS l=LMOS\n",
        encoding="ascii",
    )
    (run / "sp.sp").write_text("mock", encoding="ascii")
    (run / "evidence_manifest.json").write_text("mock", encoding="ascii")
    return run


def test_lookup_auditor_recomputes_sources_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    left = _source(sources, "run200", 200)
    right = _source(sources, "run400", 400)
    original_read = read_evidenced_metrics

    def read(path: Path) -> dict:
        if path == left or path == right:
            return {"design_parameters": {"vbias_v": 0.55, "wmos_um": 200 if path == left else 400}}
        return original_read(path)

    monkeypatch.setattr(exporter, "_require_private_path", lambda path: None)
    monkeypatch.setattr(exporter, "audit_teaching_lna", lambda path: {"device_op": _OP})
    monkeypatch.setattr(auditor, "audit_teaching_lna", lambda path: {"device_op": _OP})
    monkeypatch.setattr(exporter, "read_evidenced_metrics", read)
    monkeypatch.setattr(auditor, "read_evidenced_metrics", read)
    monkeypatch.setattr(exporter, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    monkeypatch.setattr(auditor, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    output = tmp_path / "lookup"
    exported = exporter.export_teaching_device_lookup([right, left], output)
    assert exported["status"] == "multi_width_characterization"
    assert auditor.audit_teaching_device_lookup(output, sources)["rows_verified"] == 2

    metrics_path = output / "metrics.json"
    edited = json.loads(metrics_path.read_text(encoding="utf-8"))
    edited["rows"][0]["gm_s"] *= 2
    metrics_path.write_text(json.dumps(edited), encoding="utf-8")
    manifest = build_evidence_manifest(output, {"metrics": "metrics.json", "lookup": "device_lookup.csv"})
    (output / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="gm_s"):
        auditor.audit_teaching_device_lookup(output, sources)

    edited = json.loads(json.dumps(exported))
    edited["rows"][0]["cgs_f"] *= 1.5
    metrics_path.write_text(json.dumps(edited), encoding="utf-8")
    manifest = build_evidence_manifest(output, {"metrics": "metrics.json", "lookup": "device_lookup.csv"})
    (output / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="cgs_f"):
        auditor.audit_teaching_device_lookup(output, sources)

    metrics_path.write_text(json.dumps(exported), encoding="utf-8")
    manifest = build_evidence_manifest(output, {"metrics": "metrics.json", "lookup": "device_lookup.csv"})
    (output / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (left / "evidence_manifest.json").write_text("changed", encoding="ascii")
    with pytest.raises(ValueError, match="source evidence manifest changed"):
        auditor.audit_teaching_device_lookup(output, sources)


def test_lookup_auditor_accepts_legacy_fixed_width_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    left = _source(sources, "run050", 300, 0.5)
    right = _source(sources, "run055", 300, 0.55)
    original_read = read_evidenced_metrics

    def op(path: Path) -> dict:
        return {"device_op": {**_OP, "vgs": 0.5 if path == left else 0.55}}

    def read(path: Path) -> dict:
        if path in (left, right):
            return {"design_parameters": {"vbias_v": 0.5 if path == left else 0.55}}
        return original_read(path)

    monkeypatch.setattr(exporter, "_require_private_path", lambda path: None)
    monkeypatch.setattr(exporter, "audit_teaching_lna", op)
    monkeypatch.setattr(auditor, "audit_teaching_lna", op)
    monkeypatch.setattr(exporter, "read_evidenced_metrics", read)
    monkeypatch.setattr(auditor, "read_evidenced_metrics", read)
    monkeypatch.setattr(exporter, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    monkeypatch.setattr(auditor, "parse_complex_trace", lambda path, signal: ([1.0], [1j]))
    output = tmp_path / "lookup"
    exported = exporter.export_teaching_device_lookup([left, right], output)
    bias_neutralized, count = exporter._BIAS.subn(
        r"\g<1><BIAS>", (right / "netlist.scs").read_text(encoding="ascii")
    )
    assert count == 1
    exported.pop("widths_um")
    exported["template_sha256"] = hashlib.sha256(bias_neutralized.encode("ascii")).hexdigest()
    (output / "metrics.json").write_text(json.dumps(exported), encoding="utf-8")
    manifest = build_evidence_manifest(output, {"metrics": "metrics.json", "lookup": "device_lookup.csv"})
    (output / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert auditor.audit_teaching_device_lookup(output, sources)["widths_um"] == [300.0]
