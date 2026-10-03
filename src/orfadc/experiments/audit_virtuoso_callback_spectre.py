from __future__ import annotations

import argparse
import json
from pathlib import Path

from orfadc.cadence.ocean_ascii import read_ocnprint_trace, read_ocean_rf_data, read_ocean_vdd_current
from orfadc.experiments.audit_virtuoso_callback_chain import audit_virtuoso_callback_chain
from orfadc.experiments.audit_virtuoso_form_chain import _mos_params
from orfadc.experiments.audit_virtuoso_form_spectre_pair import (
    _export, _read, _spectre, audit_virtuoso_form_spectre_pair,
)
from orfadc.experiments.run_virtuoso_form_export import _TRACE_NAMES


_METRICS = ("s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")


def _trace(export_dir: Path, name: str) -> tuple[list[float], list[float]]:
    if name.startswith("s"):
        signal, component = name.removesuffix(".txt").split("_", 1)
        header = f'{component}(getData("{signal}"'
    else:
        header = f'getData("{name.removesuffix(".txt")}"'
    return read_ocnprint_trace(export_dir / name, header_fragment=header)


def audit_virtuoso_callback_spectre(
    form_run: Path, readback_run: Path, form_netlist: Path, baseline_netlist: Path,
    baseline_spectre: Path, form_spectre: Path, baseline_export: Path, form_export: Path,
    callback_run: Path, callback_netlist: Path, callback_spectre: Path, callback_export: Path,
) -> dict:
    audit_virtuoso_form_spectre_pair(
        form_run, readback_run, form_netlist, baseline_netlist,
        baseline_spectre, form_spectre, baseline_export, form_export,
    )
    audit_virtuoso_callback_chain(
        form_run, readback_run, form_netlist, baseline_netlist,
        callback_run, callback_netlist,
    )
    if callback_spectre in {baseline_spectre, form_spectre} or callback_export in {baseline_export, form_export}:
        raise ValueError("callback Spectre/export archives must be independent")
    callback_mos = _mos_params(callback_netlist / "input.scs")
    _, psf = _spectre(
        callback_spectre, target="callback", form_run=callback_run,
        baseline_mos=_mos_params(baseline_netlist), form_mos=callback_mos,
        form_oa=_read(callback_run / "sch.oa"),
        expected_circuit=_read(callback_netlist / "input.scs"),
    )
    callback_rows = _export(
        callback_export, target="callback", spectre_run=callback_spectre, psf_root=psf,
    )
    form_rows, _ = read_ocean_rf_data(form_export, frequency_rel_tol=1e-12)
    if len(form_rows) != len(callback_rows) or len(form_rows) < 2:
        raise ValueError("callback/form exports have different sample counts")
    if any(
        left["freq_hz"] != right["freq_hz"]
        or any(left[key] != right[key] for key in _METRICS)
        for left, right in zip(form_rows, callback_rows, strict=True)
    ):
        raise ValueError("callback/form sampled SP/noise exports are not identical")
    if any(_trace(form_export, name) != _trace(callback_export, name) for name in _TRACE_NAMES):
        raise ValueError("callback/form raw 15-digit S/noise traces differ")
    form_current = read_ocean_vdd_current(form_export / "form_sp_export_report.txt")
    callback_current = read_ocean_vdd_current(callback_export / "form_sp_export_report.txt")
    if form_current != callback_current:
        raise ValueError("callback/form exported DC currents differ")
    return {
        "status": "callback_parasitic_change_without_sampled_response_delta",
        "sample_count": len(callback_rows),
        "changed_netlist_parameter_count": 4,
        "same_15_digit_sampled_sp_noise": True,
        "same_exported_dc_current": True,
        "model_width_changed": False,
        "cdf_callback_validated": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit callback/form same-condition Spectre diagnostic")
    names = (
        "form_run", "readback_run", "form_netlist", "baseline_netlist",
        "baseline_spectre", "form_spectre", "baseline_export", "form_export",
        "callback_run", "callback_netlist", "callback_spectre", "callback_export",
    )
    for name in names:
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_callback_spectre(*(getattr(args, name) for name in names))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"callback Spectre diagnostic rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
