from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, write_evidence_manifest
from orfadc.experiments.audit_teaching_oa import _PUBLIC_MODEL, _REQUIRED, _check_inductive_topology, audit_teaching_oa
from orfadc.experiments.extract_active_oa import write_active_oa_results
from orfadc.experiments.extract_ocean_oa import extract_ocean_oa


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "teaching_oa_fixture"
    export = root / "ocnprint"
    export.mkdir(parents=True)
    result_dir = "/run/teaching_oa_fixture/results"
    frequencies = (8e9, 12e9)
    for signal, real in (("s11", 0.1), ("s21", 0.5), ("s12", 0.01), ("s22", 0.2)):
        for part, value in (("real", real), ("imag", 0.0)):
            header = f'freq (Hz) {part}(getData("{signal}" ?resultsDir "{result_dir}/psf" ?result "sp"))\n'
            body = "".join(f" {frequency:.6e} {value:.12g}\n" for frequency in frequencies)
            (export / f"{signal}_{part}.txt").write_text(header + body, encoding="utf-8")
    for signal, value in (("NF", 10 * math.log10(2)), ("NFmin", 0.0), ("F", 2.0), ("Fmin", 1.0)):
        header = f'freq (Hz) getData("{signal}" ?resultsDir "{result_dir}/psf" ?result "sp_noise")'
        if signal in {"NF", "NFmin"}:
            header += " (dB)"
        body = "".join(f" {frequency:.6e} {value:.12g}\n" for frequency in frequencies)
        (export / f"{signal}.txt").write_text(header + "\n" + body, encoding="utf-8")
    (export / "report.txt").write_text("vdd_current=-0.0005\n", encoding="utf-8")
    (root / "ocean.log").write_text("INFO (ADE-3071): Simulation completed successfully.\n", encoding="utf-8")
    model_path = f"/run/{root.name}/teaching_mos1_model.scs"
    (root / "spectre.out").write_text(
        f"Reading file:  {model_path}\nspectre completes with 0 errors, 0 warnings\n", encoding="utf-8"
    )
    (root / "netlist.scs").write_text(
        f'include "ade_e.scs"\ninclude "{model_path}"\n'
        "M1 (net4 net2 0 0) n_teach w=300u l=100n\n"
        "PORT1 (net1 0) port r=50 num=1 type=sine\n"
        "PORT2 (net5 0) port r=50 num=2 type=sine\n"
        "VBIAS (net3 0) vsource dc=0.55 type=dc\n"
        "VDD (net6 0) vsource dc=1.2 type=dc\n"
        "RBIAS (net2 net3) resistor r=1Meg\n"
        "RD (net6 net4) resistor r=100\n"
        "CIN (net1 net2) capacitor c=10p\n"
        "COUT (net4 net5) capacitor c=10p\n",
        encoding="ascii",
    )
    (root / "teaching_mos1_model.scs").write_bytes(_PUBLIC_MODEL.read_bytes())
    (root / "ade_e.scs").write_text("simulator lang=spectre\n", encoding="utf-8")
    (root / "oa_view").mkdir()
    (root / "oa_view/sch.oa").write_bytes(b"test OA evidence")
    (root / "schematic_check.txt").write_text("check_return=(0 0)\nsave_return=t\n", encoding="utf-8")
    (root / "ocean_run_report.txt").write_text(f'run_result="{result_dir}"\n', encoding="utf-8")
    (root / "ocean_export_report.txt").write_text("export complete\n", encoding="utf-8")
    (root / "export_ocean.ocn").write_text("selectResult('sp)\n", encoding="utf-8")
    for name in ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp"):
        (root / name).write_text("synthetic fixture, not Spectre output\n", encoding="utf-8")
    rows, payload = extract_ocean_oa(
        export, ocean_log=root / "ocean.log", spectre_log=root / "spectre.out",
        run_id=root.name, supply_voltage_v=1.2, low_ghz=8, high_ghz=12,
        teaching_model=True,
    )
    write_active_oa_results(root, rows, payload)
    write_evidence_manifest(root, _REQUIRED)
    return root


def _rehash(root: Path) -> None:
    (root / "evidence_manifest.json").write_text(
        json.dumps(build_evidence_manifest(root, _REQUIRED)), encoding="utf-8"
    )


def test_audit_teaching_oa_recomputes_synthetic_fixture(run_dir: Path) -> None:
    result = audit_teaching_oa(run_dir)
    assert result["status"] == "verified"
    assert result["points_verified"] == 2
    assert result["not_lna_result"] is True


def test_audit_teaching_oa_rejects_unhashed_report_change(run_dir: Path) -> None:
    (run_dir / "ocnprint/report.txt").write_text("vdd_current=-0.0007\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        audit_teaching_oa(run_dir)


def test_audit_teaching_oa_rejects_rehashed_metric_change(run_dir: Path) -> None:
    path = run_dir / "metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["s21_db"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash(run_dir)
    with pytest.raises(ValueError, match="disagrees with raw OCEAN data"):
        audit_teaching_oa(run_dir)


def test_audit_teaching_oa_rejects_rehashed_wrong_model(run_dir: Path) -> None:
    path = run_dir / "teaching_mos1_model.scs"
    path.write_text("simulator lang=spectre\nmodel n_teach mos1\n", encoding="ascii")
    _rehash(run_dir)
    with pytest.raises(ValueError, match="differs from the public teaching model"):
        audit_teaching_oa(run_dir)


def test_audit_teaching_oa_rejects_wrong_trace_provenance(run_dir: Path) -> None:
    path = run_dir / "ocnprint/s11_real.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("/run/teaching_oa_fixture/results", "/run/other/results"), encoding="utf-8")
    _rehash(run_dir)
    with pytest.raises(ValueError, match="not bound to this OCEAN run"):
        audit_teaching_oa(run_dir)


def _make_inductive_fixture(run_dir: Path) -> None:
    (run_dir / "netlist.scs").write_text(
        'include "ade_e.scs"\n'
        f'include "/run/{run_dir.name}/teaching_mos1_model.scs"\n'
        "M1 (drain gate source 0) n_teach w=300u l=100n\n"
        "PORT1 (input 0) port r=50 num=1 type=sine\n"
        "PORT2 (output 0) port r=50 num=2 type=sine\n"
        "VBIAS (bias 0) vsource dc=0.65 type=dc\n"
        "VDD (vdd 0) vsource dc=1.2 type=dc\n"
        "RBIAS (gate bias) resistor r=100k\n"
        "CIN (input rf_input) capacitor c=5p\n"
        "LG (rf_input gate) inductor l=1n\n"
        "LS (source 0) inductor l=240p\n"
        "LD (vdd drain) inductor l=2n\n"
        "COUT (drain output) capacitor c=5p\n",
        encoding="ascii",
    )
    payload_path = run_dir / "metrics.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["source_run_kind"] = "teaching_mos1_inductive_oa_ocean_classic_batch"
    payload["circuit_class"] = "teaching_mos1_inductive_common_source"
    payload["teaching_topology"] = "inductive"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash(run_dir)


def test_audit_teaching_oa_accepts_inductive_connection_fixture(run_dir: Path) -> None:
    _make_inductive_fixture(run_dir)
    assert audit_teaching_oa(run_dir)["points_verified"] == 2


def test_audit_teaching_oa_rejects_rehashed_inductor_miswire(run_dir: Path) -> None:
    _make_inductive_fixture(run_dir)
    netlist = run_dir / "netlist.scs"
    netlist.write_text(
        netlist.read_text(encoding="ascii").replace("LD (vdd drain)", "LD (vdd gate)"), encoding="ascii"
    )
    _rehash(run_dir)
    with pytest.raises(ValueError, match="connection or device value differs"):
        audit_teaching_oa(run_dir)


def test_damped_oa_netlist_requires_parallel_resistor_and_values(run_dir: Path) -> None:
    _make_inductive_fixture(run_dir)
    source = (run_dir / "netlist.scs").read_text(encoding="ascii")
    source = source.replace("LD (vdd drain) inductor l=2n", "LD (vdd drain) inductor l=1.68809309279457n")
    source = source.replace("COUT (drain output) capacitor c=5p", "COUT (drain output) capacitor c=225.079079039277f")
    source += "RDAMP (vdd drain) resistor r=150\n"
    _check_inductive_topology(source, damped=True)
    with pytest.raises(ValueError, match="damped OA"):
        _check_inductive_topology(source.replace("RDAMP (vdd drain)", "RDAMP (vdd gate)"), damped=True)
    with pytest.raises(ValueError, match="damped OA"):
        _check_inductive_topology(source.replace("r=150", "r=250"), damped=True)
    with pytest.raises(ValueError, match="additional devices"):
        _check_inductive_topology(source + "UNEXPECTED (vdd 0) resistor r=1\n", damped=True)


def test_damped_ocean_payload_has_separate_provenance(run_dir: Path) -> None:
    _, payload = extract_ocean_oa(
        run_dir / "ocnprint", ocean_log=run_dir / "ocean.log",
        spectre_log=run_dir / "spectre.out", run_id="synthetic_damped",
        supply_voltage_v=1.2, low_ghz=8.0, high_ghz=12.0,
        teaching_model=True, teaching_topology="damped",
    )
    assert payload["source_run_kind"] == "teaching_mos1_damped_oa_ocean_classic_batch"
    assert payload["circuit_class"] == "teaching_mos1_damped_common_source"
    assert payload["not_lna_result"] is True and payload["spec_pass"] is None


def test_cascode_oa_netlist_requires_upper_device_bias_and_grounded_body(run_dir: Path) -> None:
    _make_inductive_fixture(run_dir)
    source = (run_dir / "netlist.scs").read_text(encoding="ascii")
    source = source.replace("M1 (drain gate source 0)", "M1 (cas gate source 0)")
    source += "M2 (drain casgate cas 0) n_teach w=300u l=100n\n"
    source += "VCAS (casgate 0) vsource dc=0.95 type=dc\n"
    source += "RDAMP (vdd drain) resistor r=150\n"
    source = source.replace("LD (vdd drain) inductor l=2n", "LD (vdd drain) inductor l=1.68809309279457n")
    source = source.replace("COUT (drain output) capacitor c=5p", "COUT (drain output) capacitor c=225.079079039277f")
    _check_inductive_topology(source, damped=True, cascode=True)
    with pytest.raises(ValueError, match="M2 geometry, body, or M1 drain"):
        _check_inductive_topology(source.replace("casgate cas 0)", "casgate source 0)"),
                                  damped=True, cascode=True)
    with pytest.raises(ValueError, match="M2 geometry, body, or M1 drain"):
        _check_inductive_topology(source.replace("casgate cas 0)", "casgate cas source)"),
                                  damped=True, cascode=True)
    with pytest.raises(ValueError, match="cascode bias connection or value"):
        _check_inductive_topology(source.replace("VCAS (casgate 0)", "VCAS (gate 0)"),
                                  damped=True, cascode=True)
    _check_inductive_topology(source.replace("dc=0.95 type=dc", "dc=1.05 type=dc"),
                              damped=True, cascode=True, vcas_v=1.05)


def test_cascode_ocean_payload_has_separate_provenance(run_dir: Path) -> None:
    _, payload = extract_ocean_oa(
        run_dir / "ocnprint", ocean_log=run_dir / "ocean.log",
        spectre_log=run_dir / "spectre.out", run_id="synthetic_cascode",
        supply_voltage_v=1.2, low_ghz=8.0, high_ghz=12.0,
        teaching_model=True, teaching_topology="cascode",
    )
    assert payload["source_run_kind"] == "teaching_mos1_cascode_oa_ocean_classic_batch"
    assert payload["circuit_class"] == "teaching_mos1_cascode"
    assert payload["not_lna_result"] is True and payload["spec_pass"] is None
