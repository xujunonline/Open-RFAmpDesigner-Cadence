#!/bin/bash
# Read-only PDK inventory for Cadence v2 (docs/120 V2-0). Lists, never modifies.
# Output: tagged lines "##TAG<TAB>value" parsed by orfadc.repro.pdk_v2.parse_inventory.
set -u
emit() { printf '##%s\t%s\n' "$1" "$2"; }
emit USER "$(id -un)"
emit SPECTRE "$(command -v spectre 2>/dev/null)"
emit SPECTRE_VERSION "$(spectre -W 2>/dev/null | head -1)"
for v in CDSHOME CDS_INST_DIR PDK_HOME PDK_ROOT PDKPATH CDS_LIC_FILE; do
  val="${!v:-}"; [ -n "$val" ] && emit ENV "$v=$val"
done
# cds.lib DEFINEs (library name -> path) in the usual places
for f in "$HOME/cds.lib" "$HOME"/*/cds.lib "$HOME"/*/*/cds.lib; do
  [ -f "$f" ] || continue
  emit CDSLIB "$f"
  grep -iE '^[[:space:]]*(DEFINE|INCLUDE|SOFTINCLUDE)' "$f" 2>/dev/null | head -60 | while read -r line; do emit CDSLIB_LINE "$f|$line"; done
done
# candidate PDK directories
ROOTS="/opt /eda /tools /usr/local /home/$(id -un) /pdk /data /PDKS /pdks ${PDK_EXTRA_ROOTS:-}"
for r in $ROOTS; do
  [ -d "$r" ] || continue
  timeout 40 find "$r" -maxdepth 5 -type d \( -iname '*pdk*' -o -iname 'gpdk*' -o -iname 'tsmc*' -o -iname 'smic*' \
      -o -iname '*n65*' -o -iname '*65nm*' -o -iname 'crn*' -o -iname 'umc*' -o -iname 'tsmcN*' -o -iname 'freepdk*' \
      -o -iname 'sky130*' -o -iname 'cmos*rf*' \) -not -path '*/proc/*' 2>/dev/null | head -80 | while read -r d; do emit PDKDIR "$d"; done
done
# Spectre model files below candidate dirs (and Cadence sample models)
{
  for r in $ROOTS; do [ -d "$r" ] && timeout 60 find "$r" -maxdepth 9 -type f \( -iname '*.scs' -o -iname '*.mdl' -o -iname '*.lib' -o -iname '*.l' \) \
      \( -ipath '*pdk*' -o -ipath '*model*' -o -ipath '*tsmc*' -o -ipath '*gpdk*' -o -ipath '*smic*' -o -ipath '*umc*' \) \
      -size -200M 2>/dev/null; done
} | sort -u | head -300 | while read -r m; do
  sz=$(stat -c %s "$m" 2>/dev/null || echo 0)
  emit MODELFILE "$m|$sz"
  # sections and model cards (names + level/type keywords only)
  grep -m 40 -iE '^[[:space:]]*(section|library)[[:space:]]+[A-Za-z0-9_]+' "$m" 2>/dev/null | while read -r s; do emit SECTION "$m|$s"; done
  grep -m 60 -iE '^[[:space:]]*(model|subckt|inline subckt)[[:space:]]+[A-Za-z0-9_.]+' "$m" 2>/dev/null | while read -r s; do emit MODEL "$m|$s"; done
done
# how earlier ADE netlists on this host pulled in the PDK (include/section lines and device instances)
for f in $(timeout 30 find "$HOME" -maxdepth 7 -type f -name 'input.scs' 2>/dev/null | head -20); do
  grep -m 30 -iE '^[[:space:]]*(include|ahdl_include)|section|[[:space:]](nch|pch|nmos|pmos)[a-z0-9_]*[[:space:]]' "$f" 2>/dev/null | while read -r s; do emit NETLIST_LINE "$f|$s"; done
done
# PDK top-level layout (two levels) for every DEFINE'd library that lives outside the Cadence install
for d in $(grep -hiE '^[[:space:]]*DEFINE' "$HOME"/cds.lib "$HOME"/*/cds.lib 2>/dev/null | awk '{print $3}' | sort -u); do
  case "$d" in /opt/eda/cadence/*|"$HOME"/*) continue;; esac
  [ -d "$d" ] || { emit LIBDIR_MISSING "$d"; continue; }
  emit LIBDIR "$d"
  p=$(dirname "$d")
  timeout 20 find "$p" -maxdepth 3 -type d 2>/dev/null | head -60 | while read -r x; do emit PDKTREE "$x"; done
  timeout 40 find "$p" -maxdepth 6 -type f \( -iname '*.scs' -o -iname '*.lib' -o -iname '*.l' -o -iname '*.mdl' \) 2>/dev/null | head -60 | while read -r x; do emit PDKMODEL "$x|$(stat -c %s "$x" 2>/dev/null)"; done
done
emit DONE ok
