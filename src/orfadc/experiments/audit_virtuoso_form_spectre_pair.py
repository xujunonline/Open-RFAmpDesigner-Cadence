from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.ocean_ascii import read_ocean_rf_data, read_ocean_vdd_current
from orfadc.experiments.audit_virtuoso_form_chain import _mos_params, audit_virtuoso_form_chain
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_form_export import _SCRIPT as _EXPORT_SCRIPT, _TRACE_NAMES
from orfadc.experiments.run_virtuoso_form_spectre import _READING_FILE, _REPORT_LINE, _RESULTS, _render


_RAW = ("spectre.out", "dcOp.dc", "sp.sp", "sp.noise.sp", "input.scs", "ade_e.scs")
_SPECTRE_DOWNLOADS = (
    "ocean.log", "run_report.txt", "spectre.out", "dcOp.dc", "sp.sp", "sp.noise.sp",
    "oa_after.oa", "input.scs", "ade_e.scs",
)


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("form Spectre comparison artifact is missing or unsafe")
    data = path.read_bytes()
    if not data:
        raise ValueError("form Spectre comparison artifact is empty")
    return data


def _status(run_dir: Path, expected: str, target: str) -> dict:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("form Spectre archive is missing or unsafe")
    status = json.loads(_read(run_dir / "run_status.json"))
    if (
        status.get("status") != expected or status.get("run_id") != run_dir.name
        or status.get("target") != target or status.get("returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("pdk_write") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
    ):
        raise ValueError("form Spectre status overstates its diagnostic boundary")
    return status


def _design_prefix(netlist: bytes) -> bytes:
    marker = b"\nsimulatorOptions "
    if netlist.count(marker) != 1:
        raise ValueError("Spectre netlist lacks a unique circuit/analysis boundary")
    return netlist.split(marker, 1)[0]


def _spectre(
    run_dir: Path, *, target: str, form_run: Path, baseline_mos: dict[str, str],
    form_mos: dict[str, str], form_oa: bytes, expected_circuit: bytes,
) -> tuple[dict, str]:
    status = _status(run_dir, "spectre_raw_recorded", target)
    original = _read(run_dir / "source_ocean.ocn")
    rendered = _read(run_dir / "run_same_condition.ocn")
    first = _REPORT_LINE.search(rendered)
    results = _RESULTS.search(rendered)
    if (
        first is None or results is None
        or hashlib.sha256(original).hexdigest() != status.get("source_sha256")
        or hashlib.sha256(rendered).hexdigest() != status.get("rendered_sha256")
        or status.get("source_callback_run" if target == "callback" else "source_form_run") != form_run.name
        or status.get("analysis") != ["dc", "sp", "noise"]
        or status.get("downloads") != dict.fromkeys(_SPECTRE_DOWNLOADS, True)
    ):
        raise ValueError("form Spectre source or archive is incomplete")
    report_path = re.search(rb'outfile\("([^"\r\n]+)" "w"\)', first[0])
    results_path = re.search(rb'resultsDir\("([^"\r\n]+)"\)', results[0])
    if report_path is None or results_path is None:
        raise ValueError("form Spectre report path is missing")
    expected, baseline_cell = _render(
        original, cell=status["source_cell"],
        report_path=report_path[1].decode("ascii"), results_path=results_path[1].decode("ascii"),
    )
    if (
        expected != rendered
        or (target == "baseline" and status["source_cell"] != baseline_cell)
        or (target != "baseline" and status["source_cell"] == baseline_cell)
    ):
        raise ValueError("form Spectre analyses did not differ only in design cell/results")
    before = _read(run_dir / "oa_before.oa")
    after = _read(run_dir / "oa_after.oa")
    if before != after or hashlib.sha256(before).hexdigest() != status.get("oa_sha256"):
        raise ValueError("Spectre diagnostic changed its source OA")
    if target != "baseline" and before != form_oa:
        raise ValueError("Spectre form run consumed another OA revision")
    for name in _RAW:
        _read(run_dir / name)
    if hashlib.sha256(_read(run_dir / "input.scs")).hexdigest() != status.get("netlist_sha256"):
        raise ValueError("Spectre netlist changed after export")
    if _design_prefix(_read(run_dir / "input.scs")) != _design_prefix(expected_circuit):
        raise ValueError("Spectre job did not consume the audited circuit definition")
    actual_mos = _mos_params(run_dir / "input.scs")
    if actual_mos != (baseline_mos if target == "baseline" else form_mos):
        raise ValueError("Spectre did not simulate the audited MOS parameters")
    ocean_log = _read(run_dir / "ocean.log").decode("utf-8", errors="replace")
    spectre_log = _read(run_dir / "spectre.out").decode("utf-8", errors="replace")
    if (
        re.search(r"(?m)^\\e \*Error\*", ocean_log)
        or "Lic Summary" not in ocean_log
        or not re.search(r"spectre completes with 0 errors,", spectre_log)
        or len(re.findall(r"SFE-1131", spectre_log)) != 5
        or _READING_FILE.search(spectre_log) is None
    ):
        raise ValueError("form Spectre job has unqualified completion or model warnings")
    return status, results_path[1].decode("ascii") + "/psf"


def _export(run_dir: Path, *, target: str, spectre_run: Path, psf_root: str) -> list[dict[str, float]]:
    status = _status(run_dir, "export_recorded", target)
    if (
        status.get("source_spectre_run") != spectre_run.name
        or status.get("ocn_precision_digits") != 15
        or status.get("user_oa_write") is not False
        or status.get("downloads") != dict.fromkeys(
            ("ocean.log", "form_sp_export_report.txt", *_TRACE_NAMES), True,
        )
        or _read(run_dir / _EXPORT_SCRIPT.name) != _read(_EXPORT_SCRIPT)
        or hashlib.sha256(_read(run_dir / _EXPORT_SCRIPT.name)).hexdigest() != status.get("script_sha256")
    ):
        raise ValueError("OCEAN export source is not the audited 15-digit trace set")
    hashes = status.get("source_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(_RAW):
        raise ValueError("OCEAN export lacks a complete raw source binding")
    for name in _RAW:
        if hashlib.sha256(_read(spectre_run / name)).hexdigest() != hashes[name]:
            raise ValueError("OCEAN export raw source changed")
    for name in _TRACE_NAMES:
        _read(run_dir / name)
    log = _read(run_dir / "ocean.log").decode("utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or "Lic Summary" not in log:
        raise ValueError("OCEAN export did not complete cleanly")
    header = "\n".join((run_dir / "s11_real.txt").read_text(encoding="utf-8").splitlines()[:3])
    if f'?resultsDir "{psf_root}"' not in header:
        raise ValueError("OCEAN export points at another PSF source")
    rows, stability = read_ocean_rf_data(run_dir, frequency_rel_tol=1e-12)
    current = read_ocean_vdd_current(run_dir / "form_sp_export_report.txt")
    summary = json.loads(_read(run_dir / "diagnostic_summary.json"))
    expected = {
        "sample_count": len(rows), "start_ghz": rows[0]["freq_ghz"],
        "stop_ghz": rows[-1]["freq_ghz"],
        "worst_s11_db": max(row["s11_db"] for row in rows),
        "worst_s21_db": min(row["s21_db"] for row in rows),
        "worst_nf_db": max(row["nf_db"] for row in rows),
        "current_ma": current,
        "sampled_min_k": stability["minimum_k"] if stability else None,
    }
    if (
        summary.get("status") != "diagnostic_only"
        or summary.get("source_spectre_run") != spectre_run.name
        or summary.get("target") != target
        or summary.get("not_lna_result") is not True
        or summary.get("spec_pass") is not None
        or status.get("sample_count") != len(rows)
    ):
        raise ValueError("OCEAN export summary overstates or omits its provenance")
    for key, value in expected.items():
        recorded = summary.get(key)
        if value is None:
            if recorded is not None:
                raise ValueError("OCEAN export summary disagrees with raw traces")
        elif not isinstance(recorded, (float, int)) or not math.isclose(recorded, value, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("OCEAN export summary disagrees with raw traces")
    return rows


def audit_virtuoso_form_spectre_pair(
    form_run: Path, readback_run: Path, netlist_run: Path, baseline_netlist: Path,
    baseline_spectre: Path, form_spectre: Path, baseline_export: Path, form_export: Path,
) -> dict:
    audit_virtuoso_form_chain(form_run, readback_run, netlist_run, baseline_netlist)
    form_oa = _read(form_run / "sch.oa")
    baseline_mos = _mos_params(baseline_netlist)
    form_mos = _mos_params(netlist_run / "input.scs")
    if baseline_spectre == form_spectre or baseline_export == form_export:
        raise ValueError("paired Spectre experiments must use independent archives")
    _, base_psf = _spectre(
        baseline_spectre, target="baseline", form_run=form_run,
        baseline_mos=baseline_mos, form_mos=form_mos, form_oa=form_oa,
        expected_circuit=_read(baseline_netlist),
    )
    _, variant_psf = _spectre(
        form_spectre, target="form", form_run=form_run,
        baseline_mos=baseline_mos, form_mos=form_mos, form_oa=form_oa,
        expected_circuit=_read(netlist_run / "input.scs"),
    )
    base = _export(baseline_export, target="baseline", spectre_run=baseline_spectre, psf_root=base_psf)
    variant = _export(form_export, target="form", spectre_run=form_spectre, psf_root=variant_psf)
    if len(base) != len(variant) or len(base) < 2 or any(
        left["freq_hz"] != right["freq_hz"] for left, right in zip(base, variant, strict=True)
    ):
        raise ValueError("paired form Spectre runs do not share a frequency grid")
    deltas = {
        key: max(abs(left[key] - right[key]) for left, right in zip(base, variant, strict=True))
        for key in ("s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")
    }
    if not any(value > 1e-6 for value in deltas.values()):
        raise ValueError("form contrast does not produce a measurable SP/noise response")
    return {
        "status": "same_condition_spectre_diagnostic_verified",
        "sample_count": len(base),
        "same_frequency_grid": True,
        "both_spectre_zero_errors": True,
        "both_have_existing_model_warnings": True,
        "max_abs_delta_s11_db": deltas["s11_db"],
        "max_abs_delta_s21_db": deltas["s21_db"],
        "max_abs_delta_s22_db": deltas["s22_db"],
        "max_abs_delta_nf_db": deltas["nf_db"],
        "max_abs_delta_nfmin_db": deltas["nfmin_db"],
        "cdf_callback_validated": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit private same-condition v2/form Spectre DC/SP-noise runs")
    for name in (
        "form_run", "readback_run", "netlist_run", "baseline_netlist",
        "baseline_spectre", "form_spectre", "baseline_export", "form_export",
    ):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_form_spectre_pair(*(
            getattr(args, name) for name in (
                "form_run", "readback_run", "netlist_run", "baseline_netlist",
                "baseline_spectre", "form_spectre", "baseline_export", "form_export",
            )
        ))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"form Spectre pair rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
