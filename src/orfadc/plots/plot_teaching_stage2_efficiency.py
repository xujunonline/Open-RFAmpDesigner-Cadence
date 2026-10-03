from __future__ import annotations

import argparse
import hashlib
import io
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from orfadc.cadence.evidence import read_evidenced_metrics, write_evidence_manifest
from orfadc.config_loader import write_json
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT, _require_private_path
from orfadc.experiments.summarize_teaching_stage2_multiseed import audit_teaching_stage2_multiseed


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_WIDTH, _HEIGHT = 1200, 760


def _source(source_dir: Path) -> tuple[dict, str]:
    _require_private_path(source_dir)
    if not source_dir.is_dir() or source_dir.is_symlink():
        raise ValueError("teaching multiseed source is missing or unsafe")
    if audit_teaching_stage2_multiseed(source_dir)["status"] != "verified":
        raise ValueError("teaching multiseed source did not reaudit")
    source = read_evidenced_metrics(source_dir)
    if (
        source.get("not_lna_result") is not True
        or source.get("spec_pass") is not None
        or source.get("model_kind") != "teaching_model"
        or source.get("circuit_class") != "teaching_mos1_common_source"
    ):
        raise ValueError("plot source exceeds its teaching diagnostic boundary")
    manifest = source_dir / "evidence_manifest.json"
    return source, hashlib.sha256(manifest.read_bytes()).hexdigest()


def _series(source: dict) -> tuple[list[int], list[float], list[float]]:
    rows = source.get("per_evaluation")
    budget = source.get("budget_per_method")
    if type(budget) is not int or budget < 2 or not isinstance(rows, list) or len(rows) != budget:
        raise ValueError("teaching sample-efficiency series is incomplete")
    xs, random, pso = [], [], []
    for expected, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("evaluations") != expected:
            raise ValueError("teaching evaluation axis is inconsistent")
        values = (row.get("random_mean_best"), row.get("pso_mean_best"))
        if any(type(value) not in {float, int} or not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("teaching mean best cost is invalid")
        xs.append(expected)
        random.append(float(values[0]))
        pso.append(float(values[1]))
    return xs, random, pso


def _render(source: dict) -> bytes:
    xs, random, pso = _series(source)
    image = Image.new("RGB", (_WIDTH, _HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(image)
    title = ImageFont.load_default(size=31)
    body = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=17)
    draw.text((85, 45), "Teaching MOS1 Stage 2: sample efficiency", font=title, fill="#1d2730")
    draw.text(
        (85, 94),
        f"{source['seed_count']} seeds, {source['budget_per_method']} Spectre evaluations per method",
        font=body, fill="#44515b",
    )
    draw.text((85, 126), "Diagnostic cost only; not a paper Fig. 10 or qualified LNA result",
              font=small, fill="#a4392b")
    left, top, right, bottom = 130, 220, 1120, 620
    values = random + pso
    low, high = min(values), max(values)
    padding = max((high - low) * 0.12, abs(high) * 0.01, 1.0)
    low -= padding
    high += padding

    def point(x: int, y: float) -> tuple[int, int]:
        px = left + round((x - 1) / (len(xs) - 1) * (right - left))
        py = bottom - round((y - low) / (high - low) * (bottom - top))
        return px, py

    for tick in range(5):
        y = top + round(tick * (bottom - top) / 4)
        value = high - tick * (high - low) / 4
        draw.line((left, y, right, y), fill="#e4e8e9", width=2)
        label = f"{value:,.1f}"
        bbox = draw.textbbox((0, 0), label, font=small)
        draw.text((left - 16 - (bbox[2] - bbox[0]), y - 9), label, font=small, fill="#465159")
    draw.line((left, top, left, bottom, right, bottom), fill="#38434a", width=3)
    for x in xs:
        px, _ = point(x, low)
        draw.line((px, bottom, px, bottom + 7), fill="#38434a", width=2)
        draw.text((px - 5, bottom + 18), str(x), font=small, fill="#38434a")
    for values, color in ((random, "#087f79"), (pso, "#d05a31")):
        coordinates = [point(x, y) for x, y in zip(xs, values, strict=True)]
        draw.line(coordinates, fill=color, width=5, joint="curve")
        for px, py in coordinates:
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=color, outline="#ffffff", width=2)
    draw.text((left, 185), "Mean best diagnostic cost (lower is better)", font=body, fill="#38434a")
    draw.text((470, 675), "Evaluations per method", font=body, fill="#38434a")
    draw.line((780, 181, 820, 181), fill="#087f79", width=5)
    draw.text((830, 169), "Random", font=small, fill="#1d2730")
    draw.line((950, 181, 990, 181), fill="#d05a31", width=5)
    draw.text((1000, 169), "PSO", font=small, fill="#1d2730")
    draw.text((85, 723), f"Source archive: {source['run_id']}", font=small, fill="#68737b")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def build_teaching_stage2_plot(source_dir: Path, output_dir: Path) -> dict:
    _require_private_path(output_dir)
    source, source_digest = _source(source_dir)
    png = _render(source)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "teaching_stage2_sample_efficiency.png").write_bytes(png)
    metrics = {
        "schema_version": 1, "status": "teaching_plot_generated",
        "simulation_status": "unknown", "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model", "not_lna_result": True, "spec_pass": None,
        "run_id": output_dir.name, "source_run_id": source_dir.name,
        "source_manifest_sha256": source_digest,
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "seed_count": source["seed_count"], "budget_per_method": source["budget_per_method"],
        "scope": "Teaching Stage 2 diagnostic sample efficiency; not paper Fig. 10 or LNA pass@1",
    }
    write_json(output_dir / "metrics.json", metrics)
    write_evidence_manifest(output_dir, {
        "metrics": "metrics.json", "figure": "teaching_stage2_sample_efficiency.png",
    })
    return metrics


def audit_teaching_stage2_plot(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError("teaching plot archive is missing or unsafe")
    saved = read_evidenced_metrics(output_dir)
    source_id = saved.get("source_run_id")
    if not isinstance(source_id, str) or _RUN_ID.fullmatch(source_id) is None:
        raise ValueError("teaching plot source ID is unsafe")
    source, digest = _source(_PRIVATE_ROOT / "teaching_stage2_multiseed" / source_id)
    png = _render(source)
    archived = (output_dir / "teaching_stage2_sample_efficiency.png").read_bytes()
    if (
        saved.get("status") != "teaching_plot_generated"
        or saved.get("run_id") != output_dir.name
        or saved.get("source_manifest_sha256") != digest
        or saved.get("image_sha256") != hashlib.sha256(png).hexdigest()
        or archived != png
        or saved.get("seed_count") != source["seed_count"]
        or saved.get("budget_per_method") != source["budget_per_method"]
        or saved.get("not_lna_result") is not True
        or saved.get("spec_pass") is not None
        or saved.get("model_kind") != "teaching_model"
    ):
        raise ValueError("teaching plot differs from reaudited Spectre source")
    return {"status": "verified", "seed_count": source["seed_count"],
            "budget_per_method": source["budget_per_method"], "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot an audited teaching MOS1 Stage 2 sample-efficiency pilot")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_plots")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_plot(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    if args.source is None:
        parser.error("--source is required unless --audit-dir is provided")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = args.output_root / run_id
    build_teaching_stage2_plot(args.source, output_dir)
    result = audit_teaching_stage2_plot(output_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} "
          f"output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
