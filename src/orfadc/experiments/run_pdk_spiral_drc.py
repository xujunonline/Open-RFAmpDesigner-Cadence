from __future__ import annotations

import argparse
import hashlib
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.audit_pdk_spiral_stream import audit_pdk_spiral_stream_report
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.run_pdk_spiral_stream import _CELLS


_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+\Z")


def render_spiral_drc_script(remote_dir: str, source_deck: str, top_cell: str) -> bytes:
    if (
        any(_REMOTE_PATH.fullmatch(value) is None for value in (remote_dir, source_deck))
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", top_cell)
    ):
        raise ValueError("diagnostic Calibre paths or top cell are unsafe")
    directory = shlex.quote(remote_dir)
    deck = shlex.quote(source_deck)
    top = shlex.quote(top_cell)
    return f'''#!/usr/bin/env bash
set -euo pipefail
source_deck={deck}
run_dir={directory}
gds="$run_dir/input.gds"
top={top}
test -s "$source_deck"
test -s "$gds"
test "$(grep -Fc 'LAYOUT PATH "GDSFILENAME"' "$source_deck")" -eq 1
test "$(grep -Fc 'LAYOUT PRIMARY "TOPCELLNAME"' "$source_deck")" -eq 1
awk -v gds="$gds" -v top="$top" '
  $0 == "LAYOUT PATH \\"GDSFILENAME\\"" {{ print "LAYOUT PATH \\"" gds "\\""; next }}
  $0 == "LAYOUT PRIMARY \\"TOPCELLNAME\\"" {{ print "LAYOUT PRIMARY \\"" top "\\""; next }}
  {{ print }}
' "$source_deck" > "$run_dir/rules.svrf"
test "$(grep -Fc "LAYOUT PATH \\"$gds\\"" "$run_dir/rules.svrf")" -eq 1
test "$(grep -Fc "LAYOUT PRIMARY \\"$top\\"" "$run_dir/rules.svrf")" -eq 1
! grep -Fq '"GDSFILENAME"' "$run_dir/rules.svrf"
! grep -Fq '"TOPCELLNAME"' "$run_dir/rules.svrf"
sha256sum "$source_deck" "$run_dir/rules.svrf" "$gds" > "$run_dir/source_hashes.txt"
cd "$run_dir"
set +e
calibre -drc -hier -turbo 1 rules.svrf > calibre.stdout 2> calibre.stderr
rc=$?
set -e
printf '%s\\n' "$rc" > calibre.exitcode
exit "$rc"
'''.encode("ascii")


def run_pdk_spiral_drc(
    config_path: Path, output_dir: Path, *, stream_summary: Path,
    variant: str, source_deck: str, runner: RemoteRunner | None = None,
) -> dict:
    for path in (output_dir, stream_summary):
        _require_private_path(path)
    if variant not in _CELLS or _REMOTE_PATH.fullmatch(source_deck) is None:
        raise ValueError("spiral DRC needs a known diagnostic GDS and private deck path")
    audit_pdk_spiral_stream_report(stream_summary)
    source = read_evidenced_metrics(stream_summary)
    stream_id = source["source_run_ids"][variant]
    gds_path = stream_summary.parent / stream_id / "layout.gds"
    gds = gds_path.read_bytes()
    if hashlib.sha256(gds).hexdigest() != source["source_artifact_sha256"][variant]["layout.gds"]:
        raise ValueError("diagnostic GDS changed after its stream audit")
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before diagnostic Calibre")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"spiral_drc_{uuid4().hex[:12]}")
    script = render_spiral_drc_script(remote_dir, source_deck, _CELLS[variant][0])
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "run_drc.sh").write_bytes(script)
    status = {
        "schema_version": 1, "status": "unknown", "run_id": output_dir.name,
        "variant": variant, "source_stream_run_id": stream_id,
        "source_stream_summary_run_id": stream_summary.name,
        "source_stream_manifest_sha256": hashlib.sha256(
            (stream_summary / "evidence_manifest.json").read_bytes(),
        ).hexdigest(),
        "source_gds_sha256": hashlib.sha256(gds).hexdigest(),
        "script_sha256": hashlib.sha256(script).hexdigest(),
        "source_deck_path_sha256": hashlib.sha256(source_deck.encode("utf-8")).hexdigest(),
        "host_available_gib_before": available,
        "pdk_write": False, "user_oa_write": False,
        "drc_input_qualified": False, "drc_pass": False,
        "cdf_callback_validated": False, "physical_qualification": False,
        "not_lna_result": True, "spec_pass": None,
    }

    def finish(kind: str, code: int | None = None) -> dict:
        status["status"] = kind
        status["returncode"] = code
        write_json(output_dir / "run_status.json", status)
        return status

    if not runner.ensure_remote_dir(remote_dir).ok:
        return finish("remote_directory_failed")
    for local, remote in (
        (gds_path, f"{remote_dir}/input.gds"),
        (output_dir / "run_drc.sh", f"{remote_dir}/run_drc.sh"),
    ):
        if not runner.upload(local, remote).ok:
            return finish("upload_failed")
    result = runner.run_remote(["bash", "run_drc.sh"], cwd=remote_dir, timeout_seconds=600)
    (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    names = (
        "remote_run_drc.sh", "remote_input.gds", "calibre.stdout", "calibre.stderr",
        "calibre.exitcode", "source_hashes.txt", "DRC.rep", "DRC_RES.db",
    )
    downloads = {}
    for name in names:
        remote_name = name.removeprefix("remote_") if name.startswith("remote_") else name
        downloads[name] = runner.download(f"{remote_dir}/{remote_name}", output_dir / name).ok
    status["downloads"] = downloads
    if not result.ok or not all(downloads.values()):
        return finish("calibre_or_download_failed", result.returncode)
    if (
        (output_dir / "remote_run_drc.sh").read_bytes() != script
        or (output_dir / "remote_input.gds").read_bytes() != gds
        or (output_dir / "calibre.exitcode").read_text(encoding="utf-8").strip() != "0"
    ):
        return finish("remote_source_or_exit_mismatch", result.returncode)
    return finish("diagnostic_drc_recorded", result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run diagnostic-only Calibre on a warned spiral GDS")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--stream-summary", type=Path, required=True)
    parser.add_argument("--variant", choices=tuple(_CELLS), required=True)
    parser.add_argument("--source-deck", required=True)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "pdk_spiral_drc")
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    status = run_pdk_spiral_drc(
        args.config, output_dir, stream_summary=args.stream_summary,
        variant=args.variant, source_deck=args.source_deck,
    )
    print(f"status={status['status']} output={output_dir.resolve()}")
    return 0 if status["status"] == "diagnostic_drc_recorded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
