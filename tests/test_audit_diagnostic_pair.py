import json

import pytest

from orfadc.experiments import audit_diagnostic_pair as module
from orfadc.cadence.evidence import write_evidence_manifest


_ACTIVE = "\n".join((
    "VDD (vdd 0) vsource dc=1.1 type=dc",
    "PORT1 (in 0) port r=50 num=1 type=sine",
    "RD (vdd out) resistor r=150",
    "PORT2 (out 0) port r=50 num=2 type=sine",
))


def test_expected_hb_netlist_preserves_the_active_circuit():
    output = module.expected_hb_netlist(_ACTIVE, input_dbm=-40, frequency_ghz=10.0, harmonics=7)
    assert "RD (vdd out) resistor r=150" in output
    assert "PORT1 (in 0) port r=50 num=1 type=sine dbm=-40 freq=10000000000" in output
    assert "PORT2 (out 0) port r=50 num=2 type=dc" in output
    assert output.endswith("hb hb fundfreqs=[10000000000] maxharms=[7] annotate=status")
    with pytest.raises(ValueError, match="ports"):
        module.expected_hb_netlist(_ACTIVE.replace("num=2", "num=3"),
                                   input_dbm=-40, frequency_ghz=10.0, harmonics=7)


def _fixture(tmp_path, monkeypatch):
    candidate_dir = tmp_path / "candidate001"
    sweep_dir = tmp_path / "sweep001"
    candidate_dir.mkdir()
    sweep_dir.mkdir()
    (candidate_dir / "netlist.scs").write_text(_ACTIVE, encoding="utf-8")
    (candidate_dir / "ade_e.scs").write_text("same model", encoding="utf-8")
    (candidate_dir / "evidence_manifest.json").write_text(json.dumps({"artifacts": {
        key: {"path": value} for key, value in {
            "netlist": "netlist.scs", "ade_companion": "ade_e.scs",
            "dc_raw": "psf/dcOp.dc", "sp_raw": "psf/sp.sp",
            "noise_raw": "psf/sp.noise.sp", "spectre_log": "spectre.log",
        }.items()
    }}), encoding="utf-8")
    config = {"input_powers_dbm": [-60, -50, -40, -20], "rd_ohm": 150.0,
              "vbias_v": 0.67, "frequency_ghz": 10.0, "harmonics": 7,
              "template_sha256": "other template"}
    (sweep_dir / "sweep_config.json").write_text(json.dumps(config), encoding="utf-8")
    (sweep_dir / "summary.json").write_text("{}", encoding="utf-8")
    for index, power in enumerate(config["input_powers_dbm"]):
        point_dir = sweep_dir / f"point_{index:02d}"
        point_dir.mkdir()
        (point_dir / "netlist.scs").write_text(
            module.expected_hb_netlist(_ACTIVE, input_dbm=power, frequency_ghz=10.0, harmonics=7),
            encoding="utf-8",
        )
        (point_dir / "ade_e.scs").write_text("same model", encoding="utf-8")
        (point_dir / "evidence_manifest.json").write_text("source", encoding="utf-8")
    active = {
        "status": "ok_with_warnings", "simulation_status": "ok",
        "source": "cadence_spectre", "source_run_kind": "oa_netlist_derivative_bias_load_direct_spectre",
        "circuit_class": "active_common_source_smoke", "not_lna_result": True,
        "spec_pass": None, "run_id": candidate_dir.name,
        "candidate": {"candidate_id": "c1", "spec_id": "S1", "active_params": {
            "rd_ohm": 150.0, "vbias_v": 0.67,
        }},
        "reference_planes": {"z0_ohm": 50.0},
        "frequency_band_ghz": {"low": 0.1, "high": 20.0},
        "points": 1, "stability": {"minimum_k": 0.5},
        "metrics": {"s21_db": 2.2}, "source_template_sha256": "one template",
    }

    def fake_read(path):
        if path == candidate_dir:
            return active
        index = int(path.name.split("_")[1])
        return {"parameters": {"rd_ohm": 150.0, "vbias_v": 0.67,
                               "input_dbm": config["input_powers_dbm"][index],
                               "frequency_ghz": 10.0, "harmonics": 7}}

    monkeypatch.setattr(module, "read_evidenced_metrics", fake_read)
    monkeypatch.setattr(module, "audit_hb_sweep", lambda _: {
        "compression": {"status": "ok", "ip1db_dbm": -9.0, "op1db_dbm": -7.0},
    })
    monkeypatch.setattr(module, "extract_active_oa", lambda *args, **kwargs: (
        [{"freq_ghz": 10.0}], {"metrics": {"s21_db": 2.2},
                                "stability": {"minimum_k": 0.5}},
    ))
    monkeypatch.setattr(module, "extract_sp_s21_at_frequency", lambda *args: 2.2)
    return candidate_dir, sweep_dir, active


def test_diagnostic_pair_accepts_only_same_circuit(tmp_path, monkeypatch):
    candidate_dir, sweep_dir, _ = _fixture(tmp_path, monkeypatch)
    report = module.audit_diagnostic_pair(candidate_dir, sweep_dir)
    assert report["status"] == "verified_diagnostic_pair"
    assert report["points_hb"] == 4
    assert report["template_hashes_match"] is False
    assert report["metrics"]["ip1db_dbm"] == -9.0
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_diagnostic_pair_rejects_changed_hb_component(tmp_path, monkeypatch):
    candidate_dir, sweep_dir, _ = _fixture(tmp_path, monkeypatch)
    netlist = sweep_dir / "point_02" / "netlist.scs"
    netlist.write_text(netlist.read_text().replace("r=150", "r=151"), encoding="utf-8")
    with pytest.raises(ValueError, match="beyond allowed"):
        module.audit_diagnostic_pair(candidate_dir, sweep_dir)


def test_diagnostic_pair_rejects_changed_model_companion(tmp_path, monkeypatch):
    candidate_dir, sweep_dir, _ = _fixture(tmp_path, monkeypatch)
    (sweep_dir / "point_02" / "ade_e.scs").write_text("different model", encoding="utf-8")
    with pytest.raises(ValueError, match="different model"):
        module.audit_diagnostic_pair(candidate_dir, sweep_dir)


def test_diagnostic_pair_rejects_changed_active_metric(tmp_path, monkeypatch):
    candidate_dir, sweep_dir, active = _fixture(tmp_path, monkeypatch)
    active["metrics"]["s21_db"] = 9.9
    with pytest.raises(ValueError, match="active metric"):
        module.audit_diagnostic_pair(candidate_dir, sweep_dir)


def test_diagnostic_pair_report_rebuilds_from_sources(tmp_path, monkeypatch):
    candidate_dir, sweep_dir, _ = _fixture(tmp_path, monkeypatch)
    report_dir = tmp_path / "report001"
    report_dir.mkdir()
    report = module.audit_diagnostic_pair(candidate_dir, sweep_dir)
    report["run_id"] = report_dir.name
    (report_dir / "metrics.json").write_text(json.dumps(report), encoding="utf-8")
    write_evidence_manifest(report_dir, {"metrics": "metrics.json"})
    original = module.read_evidenced_metrics
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: original(path) if path != report_dir else report)
    assert module.audit_diagnostic_pair_report(report_dir, candidate_dir, sweep_dir)["status"] == "verified"
    report["metrics"]["ip1db_dbm"] = -99.0
    with pytest.raises(ValueError, match="differs"):
        module.audit_diagnostic_pair_report(report_dir, candidate_dir, sweep_dir)
