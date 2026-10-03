from __future__ import annotations

import argparse
import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orfadc.cadence.evidence import write_evidence_manifest
from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.cadence.resource_guard import available_physical_memory_gb
from orfadc.config_loader import write_json
from orfadc.experiments.extract_active_oa import extract_active_oa, write_active_oa_results
from orfadc.experiments.run_active_diagnostic_candidate import _MINIMUM_HOST_FREE_GB, _PRIVATE_ROOT, _require_private_path
from orfadc.metric_contract import validate_metrics_payload


_NETLIST = Path(__file__).resolve().parents[3] / "circuit/spectre/teaching_mos1_lna.scs"
_RAW = ("dcOp.dc", "dcOpInfo.info", "sp.sp", "sp.noise.sp")
_BIAS = re.compile(r"^(parameters VDD=1\.2 VBIAS=)0\.65(?= WMOS=300u LMOS=100n LGS=1n LSS=240p LDD=2n\r?$)", re.MULTILINE)
_WMOS = re.compile(r"(?<= WMOS=)300u(?= LMOS=100n)")
_LGS = re.compile(r"(?<= LGS=)1n(?= LSS=240p)")
_LSS = re.compile(r"(?<= LSS=)240p(?= LDD=2n)")
_LDD = re.compile(r"(?<= LDD=)2n(?=\r?$)", re.MULTILINE)
_CBLOCK = re.compile(r"(?<=^CBLOCK \(drain out\) capacitor c=)5p(?=\r?$)", re.MULTILINE)
_LD_LINE = re.compile(r"^(LD \(vdd drain\) inductor l=LDD)(\r?\n)", re.MULTILINE)
_SP_LINE = re.compile(r"^sp sp start=100M stop=20G lin=199(?= ports=\[PORT1 PORT2\])", re.MULTILINE)


def validate_teaching_netlist(path: Path = _NETLIST) -> bytes:
    if path.resolve() != _NETLIST.resolve() or path.is_symlink():
        raise ValueError("teaching runner accepts only the checked-in MOS1 testbench")
    raw = path.read_bytes()
    source = raw.decode("ascii")
    if (
        "not foundry data" not in source
        or len(re.findall(r"^model n_teach mos1\b", source, re.MULTILINE)) != 1
        or len(re.findall(r"^M1 \(drain gate source 0\) n_teach\b", source, re.MULTILINE)) != 1
        or len(re.findall(r"^dcOp dc\b", source, re.MULTILINE)) != 1
        or len(re.findall(r"^dcOpInfo info what=oppoint where=rawfile$", source, re.MULTILINE)) != 1
        or len(re.findall(r"^sp sp\b", source, re.MULTILINE)) != 1
        or len(re.findall(r"^PORT[12] \(", source, re.MULTILINE)) != 2
        or "CIN (in rf_in) capacitor c=5p" not in source
        or "LG (rf_in gate) inductor l=LGS" not in source
        or re.search(r"^\s*(?:include|ahdl_include|simulator\s+lang=spice)\b", source, re.MULTILINE)
    ):
        raise ValueError("teaching netlist topology or standalone model is invalid")
    return raw


def render_teaching_lna_netlist(
    vbias_v: float = 0.65, *, wmos_um: float = 300.0,
    lgs_nh: float = 1.0, lss_ph: float = 240.0,
    ldd_nh: float = 2.0, cblock_ff: float = 5000.0,
    rdamp_ohm: float | None = None,
    sp_intervals: int = 199,
    sp_start_ghz: float = 0.1,
    sp_stop_ghz: float = 20.0,
    topology: str = "common_source", vcas_v: float = 0.95,
) -> bytes:
    if topology not in {"common_source", "cascode"}:
        raise ValueError("unsupported teaching topology")
    if type(vcas_v) not in {int, float} or not math.isfinite(vcas_v) or not 0.8 <= vcas_v <= 1.1:
        raise ValueError("teaching VCAS must be finite and within 0.8..1.1 V")
    if topology == "common_source" and vcas_v != 0.95:
        raise ValueError("VCAS is only used by the cascode topology")
    if type(vbias_v) not in {int, float} or not math.isfinite(vbias_v) or not 0.5 <= vbias_v <= 0.7:
        raise ValueError("teaching VBIAS must be finite and within 0.5..0.7 V")
    if type(wmos_um) not in {int, float} or not math.isfinite(wmos_um) or not 100 <= wmos_um <= 500:
        raise ValueError("teaching WMOS must be finite and within 100..500 um")
    if type(ldd_nh) not in {int, float} or not math.isfinite(ldd_nh) or not 1 <= ldd_nh <= 16:
        raise ValueError("teaching LDD must be finite and within 1..16 nH")
    if type(lgs_nh) not in {int, float} or not math.isfinite(lgs_nh) or not 0.2 <= lgs_nh <= 2:
        raise ValueError("teaching LGS must be finite and within 0.2..2 nH")
    if type(lss_ph) not in {int, float} or not math.isfinite(lss_ph) or not 100 <= lss_ph <= 500:
        raise ValueError("teaching LSS must be finite and within 100..500 pH")
    if type(cblock_ff) not in {int, float} or not math.isfinite(cblock_ff) or not 15 <= cblock_ff <= 5000:
        raise ValueError("teaching CBLOCK must be finite and within 15..5000 fF")
    if rdamp_ohm is not None and (
        type(rdamp_ohm) not in {int, float} or not math.isfinite(rdamp_ohm)
        or not 100 <= rdamp_ohm <= 10000
    ):
        raise ValueError("teaching RDAMP must be finite and within 100..10000 ohm")
    if type(sp_intervals) is not int or not 40 <= sp_intervals <= 999:
        raise ValueError("teaching SP intervals must be an integer in 40..999")
    if (
        any(type(value) not in {int, float} or not math.isfinite(value)
            for value in (sp_start_ghz, sp_stop_ghz))
        or not 0.1 <= sp_start_ghz < sp_stop_ghz <= 20.0
        or (sp_stop_ghz - sp_start_ghz) / sp_intervals > 0.10001
    ):
        raise ValueError("teaching SP range must be finite, within 0.1..20 GHz and sampled at <=0.1 GHz")
    source = validate_teaching_netlist().decode("ascii")
    source, count = _BIAS.subn(lambda match: f"{match[1]}{vbias_v:.17g}", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected bias parameter")
    source, count = _WMOS.subn(f"{wmos_um:.17g}u", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected MOS width")
    source, count = _LGS.subn(f"{lgs_nh:.17g}n", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected input inductor")
    source, count = _LSS.subn(f"{lss_ph:.17g}p", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected source inductor")
    source, count = _LDD.subn(f"{ldd_nh:.17g}n", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected drain inductor")
    capacitance = "5p" if cblock_ff == 5000 else f"{cblock_ff:.17g}f"
    source, count = _CBLOCK.subn(capacitance, source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected output series capacitor")
    if rdamp_ohm is not None:
        source, count = _LD_LINE.subn(
            lambda match: f"{match[1]}{match[2]}RDAMP (vdd drain) resistor r={rdamp_ohm:.17g}{match[2]}",
            source,
        )
        if count != 1:
            raise ValueError("teaching netlist lacks the expected output shunt inductor")
    start = "100M" if sp_start_ghz == 0.1 else f"{sp_start_ghz:.17g}G"
    stop = f"{sp_stop_ghz:.17g}G"
    source, count = _SP_LINE.subn(f"sp sp start={start} stop={stop} lin={sp_intervals}", source)
    if count != 1:
        raise ValueError("teaching netlist lacks the expected SP linear sweep")
    if topology == "cascode":
        source = source.replace(
            "// Pedagogic MOS1 LNA testbench.",
            "// Pedagogic MOS1 cascode first-stage testbench.", 1,
        )
        source, count = re.subn(
            r"^(VBIAS_SRC \(bias 0\) vsource dc=VBIAS\r?\n)",
            lambda match: match[1] + f"VCAS_SRC (casgate 0) vsource dc={vcas_v:.17g}\n",
            source, count=1, flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError("teaching netlist lacks the expected bias source")
        source, count = re.subn(
            r"^M1 \(drain gate source 0\) n_teach w=WMOS l=LMOS$",
            "M1 (cas gate source 0) n_teach w=WMOS l=LMOS\n"
            "M2 (drain casgate cas 0) n_teach w=WMOS l=LMOS",
            source, count=1, flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError("teaching netlist lacks the expected MOS connection")
    return source.encode("ascii")


def run_teaching_lna(
    config_path: Path, output_dir: Path, *, vbias_v: float = 0.65,
    wmos_um: float = 300.0,
    lgs_nh: float = 1.0, lss_ph: float = 240.0,
    ldd_nh: float = 2.0, cblock_ff: float = 5000.0,
    rdamp_ohm: float | None = None,
    sp_intervals: int = 199,
    sp_start_ghz: float = 0.1,
    sp_stop_ghz: float = 20.0,
    topology: str = "common_source", vcas_v: float = 0.95,
    runner: RemoteRunner | None = None,
) -> dict:
    _require_private_path(output_dir)
    raw = render_teaching_lna_netlist(
        vbias_v, wmos_um=wmos_um, lgs_nh=lgs_nh, lss_ph=lss_ph,
        ldd_nh=ldd_nh, cblock_ff=cblock_ff, rdamp_ohm=rdamp_ohm,
        sp_intervals=sp_intervals, sp_start_ghz=sp_start_ghz,
        sp_stop_ghz=sp_stop_ghz,
        topology=topology, vcas_v=vcas_v,
    )
    available = available_physical_memory_gb()
    if available < _MINIMUM_HOST_FREE_GB:
        raise RuntimeError("host physical-memory gate failed before teaching LNA simulation")
    runner = runner or RemoteRunner(load_remote_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "netlist.scs").write_bytes(raw)
    remote_dir = str(PurePosixPath(runner.config.remote_root) / f"teach_mos1_{uuid4().hex[:12]}")
    base = {
        "schema_version": 1,
        "status": "unknown",
        "simulation_status": "unknown",
        "circuit_class": "teaching_mos1_cascode" if topology == "cascode" else "teaching_mos1_common_source",
        "not_lna_result": True,
        "spec_pass": None,
        "run_id": output_dir.name,
        "scope": "single-stage MOS1 cascode teaching diagnostic; not a foundry PDK or paper result"
                 if topology == "cascode" else "single-stage MOS1 teaching LNA; not a foundry PDK or paper result",
        "analysis": ["dc", "op_info", "sp", "noise"],
        "model_kind": "teaching_model",
        "design_parameters": {
            "vbias_v": vbias_v, "wmos_um": wmos_um,
            "lgs_nh": lgs_nh, "lss_ph": lss_ph,
            "ldd_nh": ldd_nh, "cblock_ff": cblock_ff,
            **({"rdamp_ohm": rdamp_ohm} if rdamp_ohm is not None else {}),
            **({"sp_intervals": sp_intervals} if sp_intervals != 199 else {}),
            **({"sp_start_ghz": sp_start_ghz} if sp_start_ghz != 0.1 else {}),
            **({"sp_stop_ghz": sp_stop_ghz} if sp_stop_ghz != 20.0 else {}),
            **({"topology": topology, "vcas_v": vcas_v} if topology == "cascode" else {}),
        },
        "netlist_sha256": hashlib.sha256(raw).hexdigest(),
        "host_available_gib_before": available,
    }

    def artifacts() -> dict[str, str]:
        names = {
            "metrics": "metrics.json", "netlist": "netlist.scs", "spectre_log": "spectre.log",
            "dc_raw": "dcOp.dc", "op_raw": "dcOpInfo.info", "sp_raw": "sp.sp", "noise_raw": "sp.noise.sp",
            "touchstone": "teaching_mos1_lna.s2p", "waveforms": "waveforms.csv",
            "stdout": "spectre.stdout.log", "stderr": "spectre.stderr.log",
        }
        return {key: name for key, name in names.items() if (output_dir / name).is_file()}

    def fail(status: str, *, simulation_status: str = "unknown", error: str | None = None) -> dict:
        payload = {**base, "status": status, "simulation_status": simulation_status}
        if error:
            payload["error"] = error
        if simulation_status == "ok":
            payload["source"] = "cadence_spectre"
        validate_metrics_payload(payload)
        write_json(output_dir / "metrics.json", payload)
        write_evidence_manifest(output_dir, artifacts())
        return payload

    created = runner.ensure_remote_dir(remote_dir)
    if not created.ok:
        return fail("mkdir_failed", error=f"returncode={created.returncode}")
    uploaded = runner.upload(output_dir / "netlist.scs", str(PurePosixPath(remote_dir) / "netlist.scs"))
    if not uploaded.ok:
        return fail("upload_failed", error=f"returncode={uploaded.returncode}")
    result = runner.run_remote(
        [runner.config.spectre_bin, "-64", "+escchars", "-format", "psfascii", "-raw", "psf",
         "+log", "spectre.log", "netlist.scs"], cwd=remote_dir,
    )
    (output_dir / "spectre.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "spectre.stderr.log").write_text(result.stderr, encoding="utf-8")
    log_result = runner.download(str(PurePosixPath(remote_dir) / "spectre.log"), output_dir / "spectre.log")
    if not result.ok:
        return fail("spectre_failed", simulation_status="failed", error=f"returncode={result.returncode}")
    if not log_result.ok:
        return fail("log_download_failed", error=f"returncode={log_result.returncode}")
    log = (output_dir / "spectre.log").read_text(encoding="utf-8", errors="replace")
    if "spectre completes with 0 errors" not in log:
        return fail("unclean_spectre_log")
    warning_count = re.search(r"spectre completes with 0 errors,\s*(\d+) warnings", log)
    if not warning_count:
        return fail("log_summary_missing")
    for name in (*_RAW, "teaching_mos1_lna.s2p"):
        remote_name = name if name.endswith(".s2p") else f"psf/{name}"
        downloaded = runner.download(str(PurePosixPath(remote_dir) / remote_name), output_dir / name)
        if not downloaded.ok:
            return fail("raw_download_failed", simulation_status="ok",
                        error=f"file={name} returncode={downloaded.returncode}")
    if int(warning_count[1]) > 0:
        base["quality_flags"] = ["spectre_warnings", *sorted(set(re.findall(r"\b(?:CMI|SPECTRE)-\d+\b", log)))]
        return fail("model_validity_warning", simulation_status="ok")
    try:
        rows, extracted = extract_active_oa(
            output_dir, run_id=output_dir.name, supply_voltage_v=1.2,
            supply_current_signal="VDD_SRC:p", low_ghz=8.0, high_ghz=12.0,
            source_run_kind="teaching_mos1_cascode_direct_spectre"
                            if topology == "cascode" else "teaching_mos1_direct_spectre",
        )
        extracted.update(base)
        extracted["status"] = "ok_with_warnings"
        extracted["simulation_status"] = "ok"
        extracted["circuit_class"] = base["circuit_class"]
        validate_metrics_payload(extracted)
        write_active_oa_results(output_dir, rows, extracted)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        return fail("result_parse_failed", simulation_status="ok", error=type(exc).__name__)
    write_evidence_manifest(output_dir, artifacts())
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the public MOS1 teaching LNA in Cadence Spectre")
    parser.add_argument("--config", type=Path, default=Path("config/remote_cadence.local.yaml"))
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_lna")
    parser.add_argument("--vbias-v", type=float, default=0.65)
    parser.add_argument("--wmos-um", type=float, default=300.0)
    parser.add_argument("--lgs-nh", type=float, default=1.0)
    parser.add_argument("--lss-ph", type=float, default=240.0)
    parser.add_argument("--ldd-nh", type=float, default=2.0)
    parser.add_argument("--cblock-ff", type=float, default=5000.0)
    parser.add_argument("--rdamp-ohm", type=float)
    parser.add_argument("--sp-intervals", type=int, default=199)
    parser.add_argument("--sp-start-ghz", type=float, default=0.1)
    parser.add_argument("--sp-stop-ghz", type=float, default=20.0)
    parser.add_argument("--topology", choices=("common_source", "cascode"), default="common_source")
    parser.add_argument("--vcas-v", type=float, default=0.95)
    args = parser.parse_args()
    output_dir = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    try:
        payload = run_teaching_lna(
            args.config, output_dir, vbias_v=args.vbias_v,
            wmos_um=args.wmos_um,
            lgs_nh=args.lgs_nh, lss_ph=args.lss_ph,
            ldd_nh=args.ldd_nh, cblock_ff=args.cblock_ff, rdamp_ohm=args.rdamp_ohm,
            sp_intervals=args.sp_intervals, sp_start_ghz=args.sp_start_ghz,
            sp_stop_ghz=args.sp_stop_ghz,
            topology=args.topology, vcas_v=args.vcas_v,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(type(exc).__name__)
    print(f"status={payload['status']} output={output_dir.resolve()}")
    return 0 if payload["status"] == "ok_with_warnings" else 1


if __name__ == "__main__":
    raise SystemExit(main())
