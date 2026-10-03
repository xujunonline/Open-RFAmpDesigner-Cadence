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
wm_pid=""
virtuoso_pid=""
focus_pid=""
cleanup() {
  local rc=$?
  trap - EXIT TERM INT
  if [[ -n "$focus_pid" ]]; then
    kill "$focus_pid" 2>/dev/null || true
    wait "$focus_pid" 2>/dev/null || true
  fi
  if [[ -n "$virtuoso_pid" ]]; then
    kill "$virtuoso_pid" 2>/dev/null || true
    wait "$virtuoso_pid" 2>/dev/null || true
  fi
  if [[ -n "$wm_pid" ]]; then
    kill "$wm_pid" 2>/dev/null || true
    wait "$wm_pid" 2>/dev/null || true
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

"$ORFADC_XVFB" ":$ORFADC_DISPLAY_NUMBER" -screen 0 1920x1080x24 -nolisten tcp >xvfb.stdout 2>xvfb.stderr &
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
mutter --x11 --sm-disable >mutter.stdout 2>mutter.stderr &
wm_pid=$!
for _ in $(seq 1 40); do
  xprop -root _NET_SUPPORTING_WM_CHECK >wm_property.txt 2>wm_property.stderr || true
  if grep -q '_NET_SUPPORTING_WM_CHECK(WINDOW)' wm_property.txt; then
    break
  fi
  if ! kill -0 "$wm_pid" 2>/dev/null; then
    break
  fi
  sleep 0.25
done
if ! grep -q '_NET_SUPPORTING_WM_CHECK(WINDOW)' wm_property.txt; then
  exit 99
fi

virtuoso -nocdsinit -nographE -restore virtuoso_gui_smoke.il -log virtuoso.log >virtuoso.stdout 2>virtuoso.stderr &
virtuoso_pid=$!
(
  for _ in $(seq 1 60); do
    if xwininfo -root -tree >window_tree.txt 2>window_tree.stderr \
      && grep -q 'Object Properties' window_tree.txt; then
      sleep 8
      python3 x11_focus_form_window.py >window_focus_report.txt 2>window_focus.stderr || true
      exit 0
    fi
    sleep 0.5
  done
) &
focus_pid=$!
wait "$virtuoso_pid"
virtuoso_pid=""
wait "$focus_pid"
focus_pid=""
