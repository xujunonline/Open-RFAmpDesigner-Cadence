from __future__ import annotations

import math
from pathlib import Path


PUBLIC_NETLIST = Path(__file__).resolve().parents[3] / "circuit/spectre/teaching_three_stage_probe.scs"
PUBLIC_MODEL = Path(__file__).resolve().parents[3] / "circuit/spectre/teaching_mos1_model.scs"
_LOAD_LINE = "CL (outp outn) capacitor c=62f\n"
_SECONDARY_LINE = "L3S (outp outn) inductor l=1n\n"
_INPUT_PORT = "PORT1 (in 0) port r=50 num=1 type=sine\n"
_OUTPUT_PORT = "PORT2 (outp outn) port r=1787 num=2 type=sine\n"
_SP_GRID = "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2]"


def render_teaching_three_stage(
    *, output_tune_ff: float = 0.0, output_secondary_nh: float = 1.0,
    broadband: bool = False,
) -> bytes:
    if (type(output_tune_ff) not in {int, float} or not math.isfinite(output_tune_ff)
            or not 0 <= output_tune_ff <= 500):
        raise ValueError("teaching output tuning capacitance must be within 0..500 fF")
    if (type(output_secondary_nh) not in {int, float} or not math.isfinite(output_secondary_nh)
            or not 0.5 <= output_secondary_nh <= 16):
        raise ValueError("teaching output secondary inductance must be within 0.5..16 nH")
    if type(broadband) is not bool:
        raise ValueError("teaching three-stage broadband setting must be boolean")
    raw = PUBLIC_NETLIST.read_bytes()
    source = raw.decode("ascii")
    if (source.count(_LOAD_LINE) != 1 or source.count(_SECONDARY_LINE) != 1
            or source.count("PORT2 (outp outn) port r=1787 num=2 type=sine") != 1
            or source.count(_SP_GRID) != 1):
        raise ValueError("public three-stage template has changed unexpectedly")
    if output_tune_ff == 0 and output_secondary_nh == 1 and not broadband:
        return raw
    if output_secondary_nh != 1:
        source = source.replace(
            _SECONDARY_LINE,
            f"L3S (outp outn) inductor l={output_secondary_nh:.17g}n\n",
        )
    if output_tune_ff:
        source = source.replace(
            _LOAD_LINE,
            _LOAD_LINE + f"COUTTUNE (outp outn) capacitor c={output_tune_ff:.17g}f\n",
        )
    if broadband:
        source = source.replace(_SP_GRID, "sp sp start=100M stop=20.1G lin=400 ports=[PORT1 PORT2]")
    return source.encode("ascii")


def render_teaching_three_stage_hb(
    input_dbm: float, *, output_secondary_nh: float = 1.0,
    frequency_ghz: float = 10.0, harmonics: int = 7,
) -> bytes:
    if (type(input_dbm) not in {int, float} or not math.isfinite(input_dbm)
            or not -100 <= input_dbm <= 0):
        raise ValueError("teaching three-stage HB input must be within -100..0 dBm")
    if (type(frequency_ghz) not in {int, float} or not math.isfinite(frequency_ghz)
            or not 8 <= frequency_ghz <= 12
            or not math.isclose((frequency_ghz - 8) / 0.025,
                                round((frequency_ghz - 8) / 0.025), abs_tol=1e-8)):
        raise ValueError("teaching three-stage HB frequency must lie on the 161-point SP grid")
    if type(harmonics) is not int or not 1 <= harmonics <= 11:
        raise ValueError("teaching three-stage HB harmonics must be within 1..11")
    source = render_teaching_three_stage(output_secondary_nh=output_secondary_nh).decode("ascii")
    if source.count(_INPUT_PORT) != 1 or source.count(_OUTPUT_PORT) != 1:
        raise ValueError("public three-stage ports changed unexpectedly")
    source = source.replace(
        _INPUT_PORT,
        f"PORT1 (in 0) port r=50 num=1 type=sine dbm={input_dbm:.17g} freq={frequency_ghz * 1e9:.17g}\n",
    ).replace(_OUTPUT_PORT, "PORT2 (outp outn) port r=1787 num=2 type=dc\n")
    return (source + f"\nhb hb fundfreqs=[{frequency_ghz * 1e9:.17g}] "
            f"maxharms=[{harmonics}] annotate=status\n").encode("ascii")
