import csv

import pytest

from orfadc.experiments import summarize_teaching_matched_hb as module


def _fixture(tmp_path, monkeypatch):
    design = {
        "frequency_ghz": 10.0, "harmonics": 7, "vbias_v": 0.65,
        "ldd_nh": 1.688, "cblock_ff": 225.0, "rdamp_ohm": 150.0,
        "sp_intervals": 160, "sp_start_ghz": 8.0, "sp_stop_ghz": 12.0,
    }
    powers = [-50.0, -40.0, -20.0, -10.0]
    gains = [9.257, 9.2569, 9.25, 9.186]
    root = tmp_path / "hb"
    root.mkdir()
    paths = [root / f"point_{i:02d}" for i in range(4)]
    rejected = root / "warning"
    payloads = {}
    for index, (path, power) in enumerate(zip(paths, powers, strict=True)):
        path.mkdir()
        (path / "evidence_manifest.json").write_text(f"source {index}", encoding="utf-8")
        payloads[path] = {"parameters": {"input_dbm": power, **design}}
    rejected.mkdir()
    (rejected / "evidence_manifest.json").write_text("warning source", encoding="utf-8")
    payloads[rejected] = {
        "status": "model_validity_warning", "simulation_status": "ok",
        "source": "cadence_spectre", "model_kind": "teaching_model",
        "not_lna_result": True, "spec_pass": None,
        "parameters": {"input_dbm": 0.0, **design},
        "quality_flags": ["spectre_warnings", "CMI-2377"],
    }
    monkeypatch.setattr(module, "read_evidenced_metrics", lambda path: payloads[path])

    def fake_audit(path):
        index = paths.index(path)
        return {"metrics": {"output_power_dbm": powers[index] + gains[index],
                            "power_gain_db": gains[index],
                            "small_signal_s21_db": 9.2571}}

    monkeypatch.setattr(module, "audit_teaching_hb", fake_audit)
    return root, paths, rejected, payloads, gains


def test_matched_hb_summary_excludes_warning_and_leaves_p1db_null(tmp_path, monkeypatch):
    _, paths, rejected, _, _ = _fixture(tmp_path, monkeypatch)
    result = module.build_matched_hb_summary(paths, rejected, "summary001")
    assert result["status"] == "unbracketed_model_warning_stop"
    assert result["compression"]["ip1db_dbm"] is None
    assert result["rejected_input_dbm"] == 0.0
    assert result["not_lna_result"] is True and result["spec_pass"] is None


def test_matched_hb_summary_rejects_mixed_design_or_warning_metrics(tmp_path, monkeypatch):
    _, paths, rejected, payloads, _ = _fixture(tmp_path, monkeypatch)
    payloads[paths[1]]["parameters"]["rdamp_ohm"] = 250.0
    with pytest.raises(ValueError, match="designs differ"):
        module.build_matched_hb_summary(paths, rejected, "summary001")
    payloads[paths[1]]["parameters"]["rdamp_ohm"] = 150.0
    payloads[rejected]["metrics"] = {"ip1db_dbm": 0.0}
    with pytest.raises(ValueError, match="model-warning"):
        module.build_matched_hb_summary(paths, rejected, "summary001")


def test_matched_hb_summary_does_not_hide_a_real_crossing(tmp_path, monkeypatch):
    _, paths, rejected, _, gains = _fixture(tmp_path, monkeypatch)
    gains[-1] = 8.0
    with pytest.raises(ValueError, match="expects an unbracketed"):
        module.build_matched_hb_summary(paths, rejected, "summary001")


def test_matched_hb_csv_is_recomputed_from_archives(tmp_path, monkeypatch):
    _, paths, rejected, payloads, _ = _fixture(tmp_path, monkeypatch)
    summary_dir = tmp_path / "summary001"
    summary_dir.mkdir()
    saved = module.build_matched_hb_summary(paths, rejected, summary_dir.name)
    payloads[summary_dir] = saved
    csv_path = summary_dir / "power_sweep.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=module._COLUMNS)
        writer.writeheader()
        writer.writerows(saved["rows"])
    assert module.audit_matched_hb_summary(summary_dir, paths[0].parent)["status"] == "verified"
    csv_path.write_text(csv_path.read_text().replace("9.257", "19.257", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="CSV"):
        module.audit_matched_hb_summary(summary_dir, paths[0].parent)
