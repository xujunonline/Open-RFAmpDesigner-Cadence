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
from orfadc.experiments.summarize_teaching_stage2_three_methods import (
    audit_teaching_stage2_three_methods,
)


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FILE = "teaching_stage2_three_methods.png"
_METHODS = (
    ("Random", "random_mean_best", "#087f79"),
    ("PSO", "pso_mean_best", "#d05a31"),
    ("SA", "sa_mean_best", "#367344"),
)


def _source(source_dir: Path) -> tuple[dict, str]:
    _require_private_path(source_dir)
    if not source_dir.is_dir() or source_dir.is_symlink():
        raise ValueError("three-method plot source is missing or unsafe")
    audit_teaching_stage2_three_methods(source_dir)
    source = read_evidenced_metrics(source_dir)
    if (
        source.get("not_lna_result") is not True or source.get("spec_pass") is not None
        or source.get("model_kind") != "teaching_model"
        or source.get("circuit_class") != "teaching_mos1_common_source"
    ):
        raise ValueError("plot source exceeds its teaching diagnostic boundary")
    digest = hashlib.sha256((source_dir / "evidence_manifest.json").read_bytes()).hexdigest()
    return source, digest


def _series(source: dict) -> tuple[list[int], list[tuple[str, list[float], str]]]:
    rows = source.get("per_evaluation")
    budget = source.get("budget_per_method")
    if type(budget) is not int or budget < 2 or not isinstance(rows, list) or len(rows) != budget:
        raise ValueError("three-method plot series is incomplete")
    xs = list(range(1, budget + 1))
    series = []
    for name, key, color in _METHODS:
        values = []
        for index, row in enumerate(rows, 1):
            value = row.get(key)
            if row.get("evaluations") != index or type(value) not in {float, int} or not math.isfinite(value) or value < 0:
                raise ValueError("three-method plot data is invalid")
            values.append(float(value))
        series.append((name, values, color))
    return xs, series


def _render(source: dict) -> bytes:
    xs, series = _series(source)
    image = Image.new("RGB", (1200, 760), "#ffffff")
    draw = ImageDraw.Draw(image)
    title = ImageFont.load_default(size=31)
    body = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=17)
    draw.text((85, 45), "Teaching MOS1 Stage 2: three-method pilot", font=title, fill="#1d2730")
    draw.text((85, 94),
              f"{source['seed_count']} seeds, {source['budget_per_method']} Spectre evaluations per method",
              font=body, fill="#44515b")
    draw.text((85, 126), "Diagnostic cost only; not paper Fig. 10 or a qualified LNA result",
              font=small, fill="#a4392b")
    left, top, right, bottom = 130, 220, 1120, 620
    all_values = [value for _, values, _ in series for value in values]
    low, high = min(all_values), max(all_values)
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
    for name, values, color in series:
        coordinates = [point(x, y) for x, y in zip(xs, values, strict=True)]
        draw.line(coordinates, fill=color, width=5, joint="curve")
        for px, py in coordinates:
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=color, outline="#ffffff", width=2)
    draw.text((left, 185), "Mean best diagnostic cost (lower is better)", font=body, fill="#38434a")
    draw.text((470, 675), "Evaluations per method", font=body, fill="#38434a")
    for offset, (name, _, color) in enumerate(series):
        x = 740 + 135 * offset
        draw.line((x, 181, x + 30, 181), fill=color, width=5)
        draw.text((x + 38, 169), name, font=small, fill="#1d2730")
    draw.text((85, 723), f"Source archive: {source['run_id']}", font=small, fill="#68737b")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def build_teaching_stage2_three_method_plot(source_dir: Path, output_dir: Path) -> dict:
    _require_private_path(output_dir)
    source, source_digest = _source(source_dir)
    png = _render(source)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / _FILE).write_bytes(png)
    metrics = {
        "schema_version": 1, "status": "teaching_three_method_plot_generated",
        "simulation_status": "unknown", "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model", "not_lna_result": True, "spec_pass": None,
        "run_id": output_dir.name, "source_run_id": source_dir.name,
        "source_manifest_sha256": source_digest,
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "seed_count": source["seed_count"], "budget_per_method": source["budget_per_method"],
        "scope": "Teaching random/PSO/SA diagnostic sample efficiency; not paper Fig. 10",
    }
    write_json(output_dir / "metrics.json", metrics)
    write_evidence_manifest(output_dir, {"metrics": "metrics.json", "figure": _FILE})
    return metrics


def audit_teaching_stage2_three_method_plot(output_dir: Path) -> dict:
    _require_private_path(output_dir)
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError("three-method plot archive is missing or unsafe")
    saved = read_evidenced_metrics(output_dir)
    source_id = saved.get("source_run_id")
    if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
        raise ValueError("three-method plot source ID is unsafe")
    source, digest = _source(_PRIVATE_ROOT / "teaching_stage2_three_methods" / source_id)
    png = _render(source)
    path = output_dir / _FILE
    if not path.is_file() or path.is_symlink():
        raise ValueError("three-method plot image is missing or unsafe")
    expected = {
        "schema_version": 1, "status": "teaching_three_method_plot_generated",
        "simulation_status": "unknown", "circuit_class": "teaching_mos1_common_source",
        "model_kind": "teaching_model", "not_lna_result": True, "spec_pass": None,
        "run_id": output_dir.name, "source_run_id": source_id,
        "source_manifest_sha256": digest, "image_sha256": hashlib.sha256(png).hexdigest(),
        "seed_count": source["seed_count"], "budget_per_method": source["budget_per_method"],
        "scope": "Teaching random/PSO/SA diagnostic sample efficiency; not paper Fig. 10",
    }
    if saved != expected or path.read_bytes() != png:
        raise ValueError("three-method plot differs from reaudited Spectre source")
    return {"status": "verified", "seed_count": source["seed_count"],
            "budget_per_method": source["budget_per_method"], "not_lna_result": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot or audit a three-method teaching Stage 2 pilot")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-root", type=Path, default=_PRIVATE_ROOT / "teaching_stage2_plots")
    parser.add_argument("--audit-dir", type=Path)
    args = parser.parse_args()
    if args.audit_dir is not None:
        result = audit_teaching_stage2_three_method_plot(args.audit_dir)
        print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']}")
        return 0
    if args.source is None:
        parser.error("--source is required unless --audit-dir is provided")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = args.output_root / run_id
    build_teaching_stage2_three_method_plot(args.source, output_dir)
    result = audit_teaching_stage2_three_method_plot(output_dir)
    print(f"status={result['status']} seeds={result['seed_count']} budget={result['budget_per_method']} "
          f"output={output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
