from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ..config_loader import load_specs


_ROOT = Path(__file__).resolve().parents[3]
_FIELDS = (
    "spec_id", "fc_ghz", "fbw_ratio", "band_low_ghz", "band_high_ghz",
    "power_ma", "gain_db", "nf_max_db", "ip1db_min_dbm", "source_type",
)


def export_table_iii_specs(source: Path, output: Path) -> int:
    specs = load_specs(source)
    if not specs:
        raise ValueError("spec configuration is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        writer.writeheader()
        for spec in specs:
            low, high = spec.band_edges_ghz
            writer.writerow({
                "spec_id": spec.id, "fc_ghz": spec.fc_ghz,
                "fbw_ratio": spec.fbw_ratio, "band_low_ghz": low,
                "band_high_ghz": high, "power_ma": spec.power_ma,
                "gain_db": spec.gain_db, "nf_max_db": spec.nf_max_db,
                "ip1db_min_dbm": spec.ip1db_min_dbm,
                "source_type": "paper_table_iii_transcription",
            })
    return len(specs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export paper Table III specifications; no simulation data")
    parser.add_argument("--source", type=Path, default=_ROOT / "config/specs_table_iii.yaml")
    parser.add_argument("--output", type=Path, default=_ROOT / "results/tables/table_iii_specs.csv")
    args = parser.parse_args()
    count = export_table_iii_specs(args.source, args.output)
    print(f"Exported {count} paper specifications to {args.output}")


if __name__ == "__main__":
    main()
