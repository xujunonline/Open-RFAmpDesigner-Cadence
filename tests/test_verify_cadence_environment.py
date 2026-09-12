from pathlib import Path

from orfadc.cadence.verify_cadence_environment import _parse_key_values


def test_parse_ocean_smoke_report(tmp_path: Path) -> None:
    report = tmp_path / "verify_design_report.txt"
    report.write_text("status=ok\nengine=ocean_skill\n", encoding="utf-8")

    assert _parse_key_values(report) == {
        "status": "ok",
        "engine": "ocean_skill",
    }
