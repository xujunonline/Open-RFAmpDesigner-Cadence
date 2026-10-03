from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_BOX = re.compile(rf"\(\({_NUMBER}\s+{_NUMBER}\)\s+\({_NUMBER}\s+{_NUMBER}\)\)")
_PARAM = re.compile(r'^parameter name="([^"]+)" type="([^"]+)" value="([^"]+)"$', re.MULTILINE)
_PLACEMENT = re.compile(
    r'^inst=dbCreateParamInstByMasterName\(cv "([^"]+)" "([^"]+)" "layout" "M1" 0:0 "R0" 1'
    r'(?:\s+list\(list\("([^"]+)" "([^"]+)" "([^"]+)"\)\))?\)$', re.MULTILINE,
)


def _bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError("PCell probe artifact is missing or unsafe")
    return path.read_bytes()


def _text(path: Path) -> str:
    return _bytes(path).decode("utf-8")


def _box(raw: str) -> tuple[float, float, float, float]:
    match = _BOX.fullmatch(raw)
    if match is None:
        raise ValueError("PCell bbox is malformed")
    values = tuple(float(item) for item in re.findall(_NUMBER, raw))
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        raise ValueError("PCell bbox is nonfinite")
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        raise ValueError("PCell bbox has no area")
    return values


def _status(run_dir: Path, *, user_oa_write: bool) -> dict:
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("PCell probe directory is missing or unsafe")
    status = json.loads(_text(run_dir / "run_status.json"))
    if (
        status.get("status") != "probe_ok" or status.get("ocean_returncode") != 0
        or status.get("host_available_gib_before", 0) < 2.66
        or status.get("log_downloaded") is not True
        or status.get("report_downloaded") is not True
        or status.get("pdk_write") is not False
        or status.get("user_oa_write") is not user_oa_write
        or status.get("cdf_callback_invoked" if user_oa_write else "callback_invoked") is not False
        or (user_oa_write and status.get("oa_downloaded") is not True)
    ):
        raise ValueError("PCell probe run status is not accepted")
    log = _text(run_dir / "ocean.log")
    if "probe: complete" not in log or "*Error*" in log or "fatal X IO error" in log:
        raise ValueError("PCell probe OCEAN did not complete cleanly")
    return status


def _creation(run_dir: Path) -> tuple[
    dict[str, tuple[str, str]], tuple[float, float, float, float], tuple[str, str], tuple[str, str, str] | None,
]:
    status = _status(run_dir, user_oa_write=True)
    script = _bytes(run_dir / "create.ocn")
    if (
        script != _bytes(run_dir / "remote_create.ocn")
        or hashlib.sha256(script).hexdigest() != status.get("script_sha256")
        or script.count(b"dbCreateParamInstByMasterName") != 1
        or b"vfoSetParam" in script or b"cdfSet" in script
        or f'cellName="{run_dir.name}"'.encode("ascii") not in script
        or _bytes(run_dir / "layout.oa") != _bytes(run_dir / "remote_layout.oa")
    ):
        raise ValueError("PCell creation source or OA readback differs")
    placement = _PLACEMENT.search(script.decode("ascii"))
    if placement is None:
        raise ValueError("PCell placement is not the expected single-input call")
    report = _text(run_dir / "report.txt")
    if report.count("save=t") != 1 or "master_shapes=" not in report or "master_terminals=4" not in report:
        raise ValueError("PCell creation report lacks saved geometry")
    top = re.search(r"^instance_bbox=(\(\([^\n]+\)\)) master_bbox=(\(\([^\n]+\)\))$", report, re.MULTILINE)
    if top is None or _box(top[1]) != _box(top[2]):
        raise ValueError("PCell instance and master geometry differ")
    entries = _PARAM.findall(report)
    params = {name: (kind, value) for name, kind, value in entries}
    if len(entries) != len(params) or len(entries) < 2:
        raise ValueError("PCell expected string parameters are incomplete")
    explicit = (placement[3], placement[4], placement[5]) if placement[3] is not None else None
    return params, _box(top[1]), (placement[1], placement[2]), explicit


def _saved_children(run_dir: Path, cell_names: tuple[str, str]) -> dict[str, tuple[tuple[float, ...], tuple[float, ...]]]:
    status = _status(run_dir, user_oa_write=False)
    script = _bytes(run_dir / "probe.ocn")
    if script != _bytes(run_dir / "remote_probe.ocn") or hashlib.sha256(script).hexdigest() != status.get("script_sha256"):
        raise ValueError("PCell child geometry probe script differs from remote")
    report = _text(run_dir / "report.txt")
    blocks = re.findall(r"^cell=([^\s]+) opened=t\n(.*?)(?=^cell=|\Z)", report, re.MULTILINE | re.DOTALL)
    if len(blocks) != 2 or {name for name, _ in blocks} != set(cell_names):
        raise ValueError("PCell saved-cell readback lacks one of the paired cells")
    result = {}
    for name, body in blocks:
        top = re.search(r'^  top="M1" bbox=(\(\([^\n]+\)\)) master_bbox=(\(\([^\n]+\)\))$', body, re.MULTILINE)
        children = re.findall(r'^    child="[^"]+" bbox=(\(\([^\n]+\)\)) master_bbox=(\(\([^\n]+\)\))$', body, re.MULTILINE)
        if top is None or len(children) < 1 or _box(top[1]) != _box(top[2]):
            raise ValueError("PCell saved-cell geometry is incomplete")
        core = max((_box(child_box) for child_box, _ in children), key=lambda box: (box[2]-box[0])*(box[3]-box[1]))
        result[name] = (_box(top[1]), core)
    return result


def audit_pdk_rf_pcell_geometry(default_dir: Path, variant_dir: Path, children_dir: Path) -> dict:
    """Verify low-level PCell response only; no CDF, DRC, netlist, or LNA qualification."""
    default_params, default_box, default_master, default_explicit = _creation(default_dir)
    variant_params, variant_box, variant_master, variant_explicit = _creation(variant_dir)
    changed = [name for name in default_params if default_params[name] != variant_params.get(name)]
    if (
        default_master != variant_master
        or default_explicit is not None or variant_explicit is None
        or set(default_params) != set(variant_params)
        or len(changed) != 1
        or variant_explicit != (changed[0], *variant_params[changed[0]])
        or variant_explicit[1] != "string"
        or default_box == variant_box
    ):
        raise ValueError("PCell pair is not a one-input width response")
    saved = _saved_children(children_dir, (default_dir.name, variant_dir.name))
    if (saved[default_dir.name][0] != default_box or saved[variant_dir.name][0] != variant_box
            or saved[default_dir.name][1] == saved[variant_dir.name][1]):
        raise ValueError("PCell saved core geometry does not track the width response")
    return {
        "status": "raw_pcell_width_response_verified",
        "default_run_id": default_dir.name,
        "variant_run_id": variant_dir.name,
        "changed_parameter": changed[0],
        "parameter_before": default_params[changed[0]][1],
        "parameter_after": variant_params[changed[0]][1],
        "outer_bbox_before": default_box,
        "outer_bbox_after": variant_box,
        "core_bbox_changed": True,
        "cdf_callback_validated": False,
        "drc_validated": False,
        "schematic_netlist_matched": False,
        "physical_qualification": False,
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reaudit paired private RF PCell geometry probes")
    parser.add_argument("default_dir", type=Path)
    parser.add_argument("variant_dir", type=Path)
    parser.add_argument("children_dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit_pdk_rf_pcell_geometry(args.default_dir, args.variant_dir, args.children_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"PCell geometry audit rejected: {type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
