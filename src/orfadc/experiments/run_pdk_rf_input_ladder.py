from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_rf_input_lmatch import render_lmatch_wrapper
from orfadc.experiments.search_pdk_rf_input_ladder import audit_pdk_rf_input_ladder_search


_PORT1 = re.compile(r"(?m)^PORT1 \(in 0\) port r=50 num=1 type=sine\r?$")
_NAMES = ("C_MATCH_OUT", "L_MATCH_MID", "L_MATCH_IN", "C_MATCH_IN")
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp")


def render_ladder_netlist(source: bytes, params: dict[str, float]) -> bytes:
    expected = {"c_outer_ff", "c_inner_ff", "l_middle_nh", "l_inner_nh"}
    if not isinstance(params, dict) or set(params) != expected or any(
        type(value) not in {float, int} or not math.isfinite(value) or value <= 0
        for value in params.values()
    ):
        raise ValueError("ladder needs four positive, finite ideal parameters")
    text = source.decode("utf-8")
    if any(re.search(r"(?m)^" + name + r"\s", text) for name in _NAMES):
        raise ValueError("source netlist already contains a ladder instance")
    replacement = (
        "PORT1 (match_out 0) port r=50 num=1 type=sine\n"
        f"C_MATCH_OUT (match_out match_mid) capacitor c={params['c_outer_ff']:.17g}f\n"
        f"L_MATCH_MID (match_mid 0) inductor l={params['l_middle_nh']:.17g}n\n"
        f"L_MATCH_IN (match_mid in) inductor l={params['l_inner_nh']:.17g}n\n"
        f"C_MATCH_IN (in 0) capacitor c={params['c_inner_ff']:.17g}f"
    )
    rendered, count = _PORT1.subn(replacement, text)
    if count != 1:
        raise ValueError("source OA netlist lacks one expected input port")
    return rendered.encode("utf-8")


def render_ladder_wrapper() -> bytes:
    source = render_lmatch_wrapper()
    if source.count(b"matched.s2p") != 1:
        raise ValueError("bounded RF SP/noise wrapper changed")
    return source.replace(b"matched.s2p", b"ladder.s2p")


def run_pdk_rf_input_ladder(
    config_path: Path, output_dir: Path, *, search_dir: Path,
    runner: RemoteRunner | None = None,
) -> dict:
    for path in (output_dir, search_dir):
        _require_private_path(path)
    audit_pdk_rf_input_ladder_search(search_dir)
    search = json.loads((search_dir / "metrics.json").read_text(encoding="utf-8"))
    ids = search["source_run_ids"]
    active_dir = _PRIVATE_ROOT / "pdk_three_stage_fixed" / ids["active"]
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before RF ladder simulation")
    source = (active_dir / "netlist.scs").read_bytes()
    params = search["best_ideal_parameters"]
    netlist = render_ladder_netlist(source, params)
    wrapper = render_ladder_wrapper()
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(netlist)
    (output_dir / "wrapper.scs").write_bytes(wrapper)
    shutil.copy2(active_dir / "ade_e.scs", output_dir / "ade_e.scs")
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"rf_ladder_{uuid4().hex[:12]}")
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "search_run_id": search_dir.name,
        "source_active_run_id": ids["active"], "source_create_run_id": ids["create"],
        "source_oa_netlist_sha256": hashlib.sha256(source).hexdigest(),
        "derived_netlist_sha256": hashlib.sha256(netlist).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "search_manifest_sha256": hashlib.sha256((search_dir / "evidence_manifest.json").read_bytes()).hexdigest(),
        "ideal_parameters": params,
        "host_available_gib_before": available,
        "pdk_write": False, "user_oa_write": False, "physical_qualification": False,
        "cdf_callback_validated": False, "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["spectre_returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    for name in ("netlist.scs", "ade_e.scs", "wrapper.scs"):
        if not runner.upload(output_dir / name, str(PurePosixPath(remote_dir) / name)).ok:
            return finish("upload_failed")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii",
         "-raw", "psf", "+log", "spectre.log", "wrapper.scs"], cwd=remote_dir,
    )
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    names = ("spectre.log", "ladder.s2p", *_RAW, "remote_netlist.scs", "remote_wrapper.scs", "remote_ade_e.scs")
    downloads = {}
    for name in names:
        if name.startswith("remote_"):
            remote_name = name.removeprefix("remote_")
        elif name in _RAW:
            remote_name = f"psf/{name}"
        else:
            remote_name = name
        downloads[name] = runner.download(str(PurePosixPath(remote_dir) / remote_name), output_dir / name).ok
    status["downloads"] = downloads
    if not result.ok or not all(downloads.values()):
        return finish("spectre_or_download_failed", result.returncode)
    if any((output_dir / f"remote_{name}").read_bytes() != (output_dir / name).read_bytes()
           for name in ("netlist.scs", "wrapper.scs", "ade_e.scs")):
        return finish("remote_source_mismatch", result.returncode)
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"spectre completes with 0 errors,\s*5 warnings", log):
        return finish("spectre_log_unexpected", result.returncode)
    return finish("simulation_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate one selected ideal four-element RF input ladder")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--search-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_rf_input_ladder")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    result = run_pdk_rf_input_ladder(args.config, output_dir, search_dir=args.search_dir)
    print(f"status={result['status']} output={output_dir.resolve()}")
    return 0 if result["status"] == "simulation_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
