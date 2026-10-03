from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from orfadc.experiments.run_active_diagnostic_candidate import _require_private_path
from orfadc.experiments.run_virtuoso_cdf_form_variant import _copied_cell_target, _render_copied_form_variant
from orfadc.experiments.run_virtuoso_cdf_readonly import _LAUNCHER, _LOGS
from orfadc.experiments.run_virtuoso_form_netlist import _SCRIPT as _NETLIST_SCRIPT
from orfadc.experiments.run_virtuoso_form_readback import _SCRIPT as _READBACK_SCRIPT


_BASELINE_SHA256 = "9f0d764fdcf6dd94e427a0227113858e6a2b8ef2ce809dcc1c1a08e58ccab814"
_PARASITICS = {"ad", "as", "pd", "ps", "nrd", "nrs", "sd", "sa", "sb"}


def _read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("CDF form chain artifact is missing or unsafe")
    return path.read_bytes()


def _status(run_dir: Path, expected: str) -> dict:
    _require_private_path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("CDF form chain archive is missing or unsafe")
    value = json.loads(_read(run_dir / "run_status.json"))
    if (
        value.get("status") != expected or value.get("run_id") != run_dir.name
        or value.get("returncode") != 0
        or value.get("host_available_gib_before", 0) < 2.66
        or value.get("pdk_write") is not False
        or value.get("not_lna_result") is not True
        or value.get("spec_pass") is not None
    ):
        raise ValueError("CDF form chain status has an unsupported result claim")
    return value


def _log(run_dir: Path, name: str, *, marker: str) -> str:
    log = _read(run_dir / name).decode("utf-8", errors="replace")
    if re.search(r"(?m)^\\e \*Error\*", log) or marker not in log:
        raise ValueError("CDF form chain log lacks completion or contains a SKILL error")
    return log


def _parts(text: str, prefix: str) -> dict[str, str]:
    pairs = re.findall(rf"(?m)^{re.escape(prefix)} name=(\S+) value=(.*)$", text)
    names = [name for name, _ in pairs]
    if len(names) != len(set(names)):
        raise ValueError("CDF form report repeats a parameter")
    return {name: value.strip().strip('"') for name, value in pairs}


def _mos_params(path: Path) -> dict[str, str]:
    text = _read(path).decode("utf-8", errors="replace")
    blocks = re.findall(r"(?ms)^M1 .*?(?=^\S|\Z)", text)
    if len(blocks) != 1:
        raise ValueError("Spectre source lacks a unique target MOS")
    pairs = re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)=([^\s\\]+)", blocks[0])
    if len(pairs) != len(set(name for name, _ in pairs)):
        raise ValueError("Spectre target MOS repeats a parameter")
    return dict(pairs)


def audit_virtuoso_form_chain(
    form_run: Path, readback_run: Path, netlist_run: Path, baseline_netlist: Path,
) -> dict:
    _require_private_path(baseline_netlist)
    form = _status(form_run, "form_action_recorded")
    readback = _status(readback_run, "readback_recorded")
    netlist = _status(netlist_run, "netlist_recorded")
    if (
        form.get("baseline_copy") is not True
        or form.get("user_oa_write") is not True
        or form.get("cdf_callback_validated") is not False
        or form.get("physical_qualification") is not False
        or readback.get("user_oa_write") is not False
        or readback.get("cdf_callback_invoked") is not False
        or netlist.get("user_oa_write") is not False
        or readback.get("source_form_run") != form_run.name
        or netlist.get("source_form_run") != form_run.name
        or readback.get("source_cell") != form.get("user_cell_name")
        or netlist.get("source_cell") != form.get("user_cell_name")
    ):
        raise ValueError("CDF form chain does not bind one new user cell")
    source = _read(form_run / "source_copy.ocn")
    reference = _read(form_run / "reference_cdf.txt")
    target = _copied_cell_target(reference)
    if (
        hashlib.sha256(source).hexdigest() != form.get("source_sha256")
        or hashlib.sha256(reference).hexdigest() != form.get("reference_sha256")
        or hashlib.sha256(target.encode("ascii")).hexdigest() != form.get("target_sha256")
    ):
        raise ValueError("CDF form chain source or target changed")
    rendered = _read(form_run / "virtuoso_gui_smoke.il")
    match = re.match(rb'reportPort=outfile\("([^"\r\n]+/form_report\.txt)" "w"\)\r?\n', rendered)
    if match is None:
        raise ValueError("CDF form replay report path is missing")
    expected, _ = _render_copied_form_variant(
        source, report_path=match[1].decode("ascii"),
        cell_name=form["user_cell_name"], target_wfg=target,
    )
    if (
        rendered != expected
        or hashlib.sha256(rendered).hexdigest() != form.get("rendered_sha256")
        or _read(form_run / _LAUNCHER.name) != _read(_LAUNCHER)
        or hashlib.sha256(_read(form_run / _LAUNCHER.name)).hexdigest() != form.get("launcher_sha256")
        or form.get("downloads") != dict.fromkeys((*_LOGS, "form_report.txt", "sch.oa"), True)
    ):
        raise ValueError("CDF form replay or archive is not the recorded single-field edit")
    for name in (*_LOGS, "launcher.stdout", "launcher.stderr"):
        _read(form_run / name)
    _log(form_run, "virtuoso.log", marker="\\o ORFADC_FORM_APPLY_RETURNED")
    report = _read(form_run / "form_report.txt").decode("utf-8", errors="replace")
    for field in ("copy_save=t", "form_done_return=t", "check_return=(0 0)",
                  "save_return=t", "form_probe_end=t"):
        if report.count(field) != 1:
            raise ValueError("CDF form edit did not check and save cleanly")
    base_blocks = re.split(r"(?m)^cell=", reference.decode("utf-8"))[1:]
    if len(base_blocks) != 2:
        raise ValueError("CDF reference cell pair is incomplete")
    base = dict(re.findall(r'instance name=(\S+) value="([^"]+)"', base_blocks[1]))
    before = re.search(r"(?m)^form_field_before=(.*)$", report)
    assigned = re.search(r"(?m)^form_field_assigned=(.*)$", report)
    if before is None or assigned is None:
        raise ValueError("CDF form field values are missing")
    normalize = lambda value: value.strip().strip('"')
    after = _parts(report, "after_instance")
    after_cdf = _parts(report, "after_cdf")
    if (
        normalize(before[1]) != base.get("Wfg")
        or normalize(assigned[1]) != target
        or after.get("Wfg") != target
        or after_cdf.get("Wfg") != target
        or any(after.get(name) != base.get(name) for name in ("w", "l", "nf", "fingers"))
    ):
        raise ValueError("CDF form result is not the expected single-field contrast")
    oa = _read(form_run / "sch.oa")
    oa_sha = hashlib.sha256(oa).hexdigest()
    for run_dir, status, script, report_name in (
        (readback_run, readback, _READBACK_SCRIPT, "readback_report.txt"),
        (netlist_run, netlist, _NETLIST_SCRIPT, "netlist_report.txt"),
    ):
        archived_script = _read(run_dir / script.name)
        if (
            archived_script != _read(script)
            or hashlib.sha256(archived_script).hexdigest() != status.get("script_sha256")
            or _read(run_dir / "sch.oa") != oa
            or status.get("oa_sha256") != oa_sha
        ):
            raise ValueError("readback/netlist did not use the unchanged saved OA")
        _read(run_dir / report_name)
        _read(run_dir / "ocean.stdout")
        _read(run_dir / "ocean.stderr")
        _log(run_dir, "ocean.log", marker="Lic Summary")
    if readback.get("downloads") != dict.fromkeys(("ocean.log", "readback_report.txt", "sch.oa"), True):
        raise ValueError("independent OA readback archive is incomplete")
    saved = _read(readback_run / "readback_report.txt").decode("utf-8", errors="replace")
    if "readback_open=t" not in saved or "readback_complete=t" not in saved:
        raise ValueError("independent OA readback did not complete")
    persisted = dict(re.findall(r"(?m)^instance name=(\S+) type=\S+ value=(.*)$", saved))
    if any(normalize(persisted.get(name, "")) != after.get(name) for name in ("Wfg", "w", "l", "nf", "fingers")):
        raise ValueError("form changes did not persist in the saved OA")
    if netlist.get("downloads") != dict.fromkeys(
        ("ocean.log", "netlist_report.txt", "sch.oa", "input.scs", "ade_e.scs"), True,
    ):
        raise ValueError("Spectre netlist export archive is incomplete")
    if hashlib.sha256(_read(netlist_run / "input.scs")).hexdigest() != netlist.get("netlist_sha256"):
        raise ValueError("exported Spectre netlist changed")
    _read(netlist_run / "ade_e.scs")
    if hashlib.sha256(_read(baseline_netlist)).hexdigest() != _BASELINE_SHA256:
        raise ValueError("fixed v2 Spectre baseline changed")
    base_mos = _mos_params(baseline_netlist)
    new_mos = _mos_params(netlist_run / "input.scs")
    differing = {key for key in set(base_mos) | set(new_mos) if base_mos.get(key) != new_mos.get(key)}
    if (
        any(base_mos.get(key) != new_mos.get(key) for key in ("w", "l", "nf"))
        or not differing or not differing.issubset(_PARASITICS)
    ):
        raise ValueError("netlist geometry contrast differs from the recorded diagnostic")
    return {
        "status": "form_change_persisted_with_partial_model_propagation",
        "single_form_field_changed": True,
        "sch_check_clean": True,
        "saved_oa_identical_across_three_archives": True,
        "independent_readback_matches_form": True,
        "spectre_netlist_exported": True,
        "model_width_changed": False,
        "changed_parasitic_parameter_count": len(differing),
        "cdf_callback_validated": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit one private CDF form/OA/netlist evidence chain")
    for name in ("form_run", "readback_run", "netlist_run", "baseline_netlist"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = audit_virtuoso_form_chain(
            args.form_run, args.readback_run, args.netlist_run, args.baseline_netlist,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"CDF form chain rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
