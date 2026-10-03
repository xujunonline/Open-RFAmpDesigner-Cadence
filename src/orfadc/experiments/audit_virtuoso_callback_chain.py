from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.experiments.audit_virtuoso_form_chain import _mos_params, audit_virtuoso_form_chain
from orfadc.experiments.audit_virtuoso_form_spectre_pair import _design_prefix
from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_callback_netlist import _callback_context
from orfadc.experiments.run_virtuoso_cdf_callback_probe import _render_callback_probe
from orfadc.experiments.run_virtuoso_cdf_readonly import _LAUNCHER, _LOGS
from orfadc.experiments.run_virtuoso_form_netlist import _SCRIPT


_EXPECTED_CHANGES = frozenset({"pd", "ps", "sa", "sb"})
_REPORT_PATH = re.compile(rb'^reportPort=outfile\("(/[A-Za-z0-9._/+-]+)" "w"\)\r?$', re.MULTILINE)


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("callback-chain artifact is missing or unsafe")
    data = path.read_bytes()
    if not data:
        raise ValueError("callback-chain artifact is empty")
    return data


def _status(run_dir: Path, kind: str) -> dict:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("callback-chain archive is missing or unsafe")
    status = json.loads(_read(run_dir / "run_status.json"))
    if (
        status.get("status") != kind or status.get("run_id") != run_dir.name
        or status.get("returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("pdk_write") is not False
        or status.get("cdf_callback_validated") is not False
        or status.get("not_lna_result") is not True
        or status.get("spec_pass") is not None
    ):
        raise ValueError("callback-chain status overstates its diagnostic boundary")
    return status


def _values(report: str, prefix: str) -> dict[str, str]:
    pairs = re.findall(rf"(?m)^{prefix} name=([A-Za-z0-9]+) value=(.+)$", report)
    if len(pairs) != len(set(name for name, _ in pairs)) or not pairs:
        raise ValueError("callback report contains duplicate or missing properties")
    return dict(pairs)


def _other_circuit_lines(netlist: bytes) -> list[bytes]:
    lines = _design_prefix(netlist).splitlines()
    retained = []
    in_mos = False
    for line in lines:
        if line.startswith(b"M1 "):
            in_mos = True
            continue
        if in_mos and line.startswith((b" ", b"\t")):
            continue
        in_mos = False
        if line.strip() and not line.lstrip().startswith(b"//"):
            retained.append(line)
    return retained


def audit_virtuoso_callback_chain(
    form_run: Path, readback_run: Path, form_netlist: Path, baseline_netlist: Path,
    callback_run: Path, callback_netlist: Path,
) -> dict:
    audit_virtuoso_form_chain(form_run, readback_run, form_netlist, baseline_netlist)
    callback = _status(callback_run, "callback_invoked_and_saved")
    netlist = _status(callback_netlist, "netlist_recorded")
    if (
        callback.get("source_form_run") != form_run.name
        or callback.get("callback_invoked") is not True
        or callback.get("user_oa_write") is not True
        or netlist.get("source_callback_run") != callback_run.name
        or netlist.get("source_cell") != callback.get("user_cell_name")
        or netlist.get("user_oa_write") is not False
    ):
        raise ValueError("callback-chain source identity differs")
    lib, lib_path, cell = _callback_context(callback_run)
    script = _read(callback_run / "virtuoso_gui_smoke.il")
    path = _REPORT_PATH.search(script)
    if path is None:
        raise ValueError("callback report destination is missing")
    source_script = _read(form_run / "virtuoso_gui_smoke.il")
    source_cell = re.search(rb'(?m)^cellName="([^"\r\n]+)"\r?$', source_script)
    mos_name = re.search(rb'(?m)^mosName="([^"\r\n]+)"\r?$', source_script)
    if source_cell is None or mos_name is None:
        raise ValueError("callback source instance is missing")
    expected = _render_callback_probe(
        lib_name=lib, lib_path=lib_path, source_cell=source_cell[1].decode("ascii"),
        cell_name=cell, mos_name=mos_name[1].decode("ascii"),
        report_path=path[1].decode("ascii"),
    )
    if (
        script != expected
        or hashlib.sha256(script).hexdigest() != callback.get("rendered_sha256")
        or _read(callback_run / _LAUNCHER.name) != _read(_LAUNCHER)
        or hashlib.sha256(_read(_LAUNCHER)).hexdigest() != callback.get("launcher_sha256")
        or callback.get("downloads") != dict.fromkeys((*_LOGS, "callback_report.txt", "source_after.oa", "sch.oa"), True)
    ):
        raise ValueError("callback script or GUI archive differs from the bounded probe")
    form_oa = _read(form_run / "sch.oa")
    saved_oa = _read(callback_run / "sch.oa")
    if (
        any(_read(callback_run / name) != form_oa for name in ("source_before.oa", "source_after.oa"))
        or hashlib.sha256(form_oa).hexdigest() != callback.get("source_oa_sha256")
        or hashlib.sha256(saved_oa).hexdigest() != callback.get("oa_sha256")
        or _read(callback_netlist / "sch.oa") != saved_oa
        or hashlib.sha256(saved_oa).hexdigest() != netlist.get("source_oa_sha256")
    ):
        raise ValueError("callback changed a source OA or independent netlisting read another OA")
    log = _read(callback_run / "virtuoso.log").decode("utf-8", errors="replace")
    report = _read(callback_run / "callback_report.txt").decode("utf-8", errors="replace")
    if (
        re.search(r"(?m)^\\e \*Error\*", log)
        or "\\o ORFADC_CALLBACK_ATTEMPT" not in log
        or "\\o ORFADC_CALLBACK_RETURNED" not in log
        or any(marker not in report for marker in (
            "copy_save=t", "callback_present=t", "callback_returned=t",
            "check_return=(0 0)", "save_return=t", "callback_probe_end=t",
        ))
    ):
        raise ValueError("callback invocation or Check and Save is unconfirmed")
    before = _values(report, "before_instance")
    after = _values(report, "after_instance")
    before_cdf = _values(report, "before_cdf")
    after_cdf = _values(report, "after_cdf")
    if (
        set(before) != set(after)
        or set(before_cdf) != set(after_cdf)
        or before_cdf != after_cdf
        or frozenset(key for key in before if before[key] != after[key]) != _EXPECTED_CHANGES
    ):
        raise ValueError("callback property response differs from the saved diagnostic")
    if (
        _read(callback_netlist / _SCRIPT.name) != _read(_SCRIPT)
        or hashlib.sha256(_read(_SCRIPT)).hexdigest() != netlist.get("script_sha256")
        or netlist.get("downloads") != dict.fromkeys(
            ("ocean.log", "netlist_report.txt", "sch.oa", "input.scs", "ade_e.scs"), True,
        )
        or hashlib.sha256(_read(callback_netlist / "input.scs")).hexdigest() != netlist.get("netlist_sha256")
    ):
        raise ValueError("independent callback netlist archive is incomplete")
    ocean_log = _read(callback_netlist / "ocean.log").decode("utf-8", errors="replace")
    netlist_report = _read(callback_netlist / "netlist_report.txt").decode("utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", ocean_log) or 'netlist_result="/' not in netlist_report:
        raise ValueError("callback OCEAN netlist was not generated cleanly")
    form_mos = _mos_params(form_netlist / "input.scs")
    callback_mos = _mos_params(callback_netlist / "input.scs")
    if (
        frozenset(key for key in form_mos.keys() | callback_mos.keys()
                  if form_mos.get(key) != callback_mos.get(key)) != _EXPECTED_CHANGES
        or _other_circuit_lines(_read(form_netlist / "input.scs"))
        != _other_circuit_lines(_read(callback_netlist / "input.scs"))
    ):
        raise ValueError("callback netlist changed other circuit components or unexpected MOS parameters")
    return {
        "status": "cdf_callback_invoked_with_partial_parasitic_response",
        "changed_netlist_parameter_count": len(_EXPECTED_CHANGES),
        "model_width_changed": False, "source_oa_unchanged": True,
        "independent_netlist_oa_identical": True,
        "callback_invocation_recorded": True,
        "cdf_callback_validated": False, "physical_qualification": False,
        "not_lna_result": True, "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit private PDK callback/OA/independent netlist diagnostic")
    for name in ("form_run", "readback_run", "form_netlist", "baseline_netlist", "callback_run", "callback_netlist"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_callback_chain(*(
            getattr(args, name) for name in (
                "form_run", "readback_run", "form_netlist", "baseline_netlist", "callback_run", "callback_netlist",
            )
        ))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"CDF callback chain rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
