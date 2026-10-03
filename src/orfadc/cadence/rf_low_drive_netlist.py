from __future__ import annotations

import re


def render_rf_hb_netlist(source: bytes, input_dbm: int, *, harmonics: int = 7) -> bytes:
    """Derive a bounded HB drive point without changing the OA circuit body."""
    if type(input_dbm) is not int or not -100 <= input_dbm <= 0:
        raise ValueError("RF HB input must be an integer in -100..0 dBm")
    if type(harmonics) is not int or harmonics not in {7, 9, 11}:
        raise ValueError("RF HB harmonics must be 7, 9, or 11")
    text = source.decode("utf-8")
    if re.search(r"^(?:dcOp |dcOpInfo |sp |hb )", text, re.MULTILINE):
        raise ValueError("OA source already has an analysis")
    text, input_count = re.subn(
        r"^PORT1 \(in 0\) port r=50 num=1 type=sine$",
        f"PORT1 (in 0) port r=50 num=1 type=sine dbm={input_dbm} freq=10G",
        text, flags=re.MULTILINE,
    )
    text, output_count = re.subn(
        r"^PORT2 \(outp outn\) port r=1787 num=2 type=sine$",
        "PORT2 (outp outn) port r=1787 num=2 type=dc",
        text, flags=re.MULTILINE,
    )
    if input_count != 1 or output_count != 1 or 'include "ade_e.scs"' not in text:
        raise ValueError("OA source has unexpected ports or companion")
    text += (
        "\ndcOp dc\n"
        "dcOpInfo info what=oppoint where=rawfile\n"
        "sp sp start=8G stop=12G lin=160 ports=[PORT1 PORT2] \\\n"
        '    paramtype=s file="rf_default_hb_probe.s2p" datafmt=touchstone \\\n'
        "    donoise=yes oprobe=PORT2 iprobe=PORT1 noisedata=twoport\n"
        f"hb hb fundfreqs=[10G] maxharms=[{harmonics}] annotate=status\n"
    )
    return text.encode("utf-8")


def render_rf_default_hb_netlist(source: bytes) -> bytes:
    """Preserve the original -70 dBm low-drive archive contract."""
    return render_rf_hb_netlist(source, -70)
