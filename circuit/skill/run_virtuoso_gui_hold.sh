#!/usr/bin/env bash
set -euo pipefail

: "${ORFADC_XVFB:?}"
: "${ORFADC_DISPLAY_NUMBER:?}"
if [[ ! "$ORFADC_DISPLAY_NUMBER" =~ ^[0-9]{3,5}$ ]]; then
  exit 96
fi

socket="/tmp/.X11-unix/X${ORFADC_DISPLAY_NUMBER}"
if [[ -e "$socket" ]]; then
  exit 97
fi

xvfb_pid=""
virtuoso_pid=""
cleanup() {
  local rc=$?
  trap - EXIT TERM INT
  if [[ -n "$virtuoso_pid" ]]; then
    kill "$virtuoso_pid" 2>/dev/null || true
    wait "$virtuoso_pid" 2>/dev/null || true
  fi
  if [[ -n "$xvfb_pid" ]]; then
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

"$ORFADC_XVFB" ":$ORFADC_DISPLAY_NUMBER" -screen 0 1280x800x24 -nolisten tcp >xvfb.stdout 2>xvfb.stderr &
xvfb_pid=$!
for _ in $(seq 1 50); do
  if [[ -S "$socket" ]] && kill -0 "$xvfb_pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ ! -S "$socket" ]] || ! kill -0 "$xvfb_pid" 2>/dev/null; then
  exit 98
fi

export DISPLAY=":$ORFADC_DISPLAY_NUMBER"
unset XAUTHORITY
virtuoso -nocdsinit -nographE -restore virtuoso_gui_smoke.il -log virtuoso.log >virtuoso.stdout 2>virtuoso.stderr &
virtuoso_pid=$!
wait "$virtuoso_pid"
virtuoso_pid=""
