from __future__ import annotations

import csv
from pathlib import Path


def read_metric_csv(path: Path) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            parsed: dict[str, float | str] = {}
            for key, value in row.items():
                if value is None:
                    parsed[key] = ""
                    continue
                try:
                    parsed[key] = float(value)
                except ValueError:
                    parsed[key] = value
            rows.append(parsed)
    return rows


def psfascii_placeholder(psf_dir: Path) -> dict:
    return {
        "status": "not_implemented",
        "psf_dir": str(psf_dir),
        "note": "Prefer exporting CSV/PSFASCII from OCEAN in MVP; add native PSF parser later.",
    }

