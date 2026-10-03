import json
from pathlib import Path

import pytest

from orfadc.experiments import audit_teaching_matched_pair as module


def _fixture(tmp_path, monkeypatch):
    small = tmp_path / "small" / "small001"
    summary = tmp_path / "summary" / "summary001"
    hb_root = tmp_path / "hb"
    for path in (small, summary, hb_root):
        path.mkdir(parents=True, exist_ok=True)
        (path / "evidence_manifest.json").write_text("{}", encoding="utf-8")
    design = {
        "vbias_v": 0.65, "ldd_nh": 1.688, "cblock_ff": 225.0,
        "rdamp_ohm": 150.0, "sp_intervals": 160,
        "sp_start_ghz": 8.0, "sp_stop_ghz": 12.0,
    }
    hb_design = {"frequency_ghz": 10.0, "harmonics": 7, **design}
    source = "PORT1 (in 0) port r=50 num=1 type=sine\nPORT2 (out 0) port r=50 num=2 type=sine\n"
    (small / "netlist.scs").write_text(source, encoding="ascii")
    (small / "sp.sp").write_text("raw", encoding="ascii")
    powers = [-50.0, -40.0, -20.0, -10.0, 0.0]
    points = [hb_root / f"point_{index:02d}" for index in range(5)]
    payloads = {
        small: {"design_parameters": dict(design)},
        summary: {
            "design_parameters": dict(hb_design),
            "rows": [{"run_id": point.name, "pin_dbm": power}
                     for point, power in zip(points[:4], powers[:4], strict=True)],
            "rejected_run_id": points[-1].name,
            "rejected_input_dbm": powers[-1],
            "compression": {"status": "unbracketed"},
        },
    }
    for point, power in zip(points, powers, strict=True):
        point.mkdir()
        netlist = module.expected_hb_netlist(
            source, input_dbm=power, frequency_ghz=10.0, harmonics=7,
        )
        (point / "netlist.scs").write_text(netlist, encoding="ascii")
        (point / "sp.sp").write_text("raw", encoding="ascii")
        (point / "evidence_manifest.json").write_text(
            json.dumps({"artifacts": {"sp_raw": {"path": "sp.sp"}}}), encoding="utf-8",
        )
        payloads[point] = {"parameters": {"input_dbm": power, **hb_design}}
    payloads[points[-1]]["quality_flags"] = ["spectre_warnings", "CMI-2377"]
    (points[-1] / "spectre.log").write_text(
        "CMI-2377\nspectre completes with 0 errors, 3 warnings", encoding="utf-8",
    )
    monkeypatch.setattr(module, "audit_teaching_lna", lambda _: {
        "points_verified": 161, "metrics": {"s21_db": 7.12},
    })
    monkeypatch.setattr(module, "audit_matched_hb_summary", lambda *_: {"points_verified": 4})
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: payloads[path])
    monkeypatch.setattr(module, "extract_sp_s21_at_frequency", lambda *_: 9.257)
    return small, summary, hb_root, points, payloads


def test_matched_pair_binds_all_hb_points_to_small_signal(tmp_path, monkeypatch):
    small, summary, hb_root, points, _ = _fixture(tmp_path, monkeypatch)
    report = module.build_teaching_matched_pair(small, summary, hb_root, "report001")
    assert report["same_netlist_except_stimulus_and_hb"] is True
    assert report["hb_point_run_ids"] == [point.name for point in points]
    assert report["points_hb_valid"] == 4
    assert report["metrics"]["ip1db_dbm"] is None
    assert report["not_lna_result"] is True and report["spec_pass"] is None


def test_matched_pair_rejects_design_or_netlist_changes(tmp_path, monkeypatch):
    small, summary, hb_root, points, payloads = _fixture(tmp_path, monkeypatch)
    payloads[summary]["design_parameters"]["rdamp_ohm"] = 250.0
    with pytest.raises(ValueError, match="design parameters"):
        module.build_teaching_matched_pair(small, summary, hb_root, "report001")
    payloads[summary]["design_parameters"]["rdamp_ohm"] = 150.0
    point = points[2] / "netlist.scs"
    point.write_text(point.read_text(encoding="ascii") + "EXTRA resistor r=1\n", encoding="ascii")
    with pytest.raises(ValueError, match="changes the small-signal circuit"):
        module.build_teaching_matched_pair(small, summary, hb_root, "report001")


def test_matched_pair_rejects_unverified_warning_or_sp(tmp_path, monkeypatch):
    small, summary, hb_root, points, _ = _fixture(tmp_path, monkeypatch)
    warning = points[-1]
    (warning / "spectre.log").write_text("spectre completes with 0 errors, 0 warnings", encoding="utf-8")
    with pytest.raises(ValueError, match="model-validity warning"):
        module.build_teaching_matched_pair(small, summary, hb_root, "report001")
    (warning / "spectre.log").write_text(
        "CMI-2377\nspectre completes with 0 errors, 3 warnings", encoding="utf-8",
    )
    (warning / "evidence_manifest.json").write_text('{"artifacts": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="evidence manifest"):
        module.build_teaching_matched_pair(small, summary, hb_root, "report001")


def test_matched_pair_report_is_recomputed_from_source_ids(tmp_path, monkeypatch):
    small, summary, hb_root, _, payloads = _fixture(tmp_path, monkeypatch)
    report_dir = tmp_path / "reports" / "report001"
    report_dir.mkdir(parents=True)
    report = module.build_teaching_matched_pair(small, summary, hb_root, report_dir.name)
    payloads[report_dir] = report
    assert module.audit_teaching_matched_pair_report(
        report_dir, small.parent, summary.parent, hb_root,
    )["status"] == "verified"
    report["small_signal_run_id"] = ".."
    with pytest.raises(ValueError, match="identity"):
        module.audit_teaching_matched_pair_report(report_dir, small.parent, summary.parent, hb_root)


def test_matched_pair_real_archive_if_available():
    root = Path("results/runs")
    small = root / "teaching_lna" / "20260926T154709Z_0b5d75fe"
    summary = root / "teaching_matched_hb_summaries" / "20260926T155406Z_7e870a71"
    if not small.is_dir() or not summary.is_dir():
        pytest.skip("private Cadence archives are not part of the public test fixture")
    report = module.build_teaching_matched_pair(
        small, summary, root / "teaching_hb", "read_only_test",
    )
    assert report["maximum_point_s21_delta_db"] < 0.001
    assert report["points_small_signal"] == 161
