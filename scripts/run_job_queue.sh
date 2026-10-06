#!/usr/bin/env bash
# macOS/Linux twin of run_job_queue.ps1 (same queue format, same log layout).
# Runs the bench commands listed in scripts/jobs/queue.txt (one per line, arguments after
# "python -m orfadc.repro.bench"), logging to results/windows_checks/<ts>_job/.  Lines starting with # are skipped;
# "set ORFADC_NAME=value" lines set an environment variable (only ORFADC_* names) for the following commands.
# Only orfadc.repro.bench subcommands are accepted.  A failed command is logged and the queue goes on; nothing is
# retried (docs/130: uncertain results are checked by hand, never re-dispatched automatically).
#
#   scripts/run_job_queue.sh                                   # scripts/jobs/queue.txt
#   scripts/run_job_queue.sh jobs/queue_llm_uncapped.txt       # path relative to scripts/ (or absolute)
#   nohup scripts/run_job_queue.sh jobs/<queue>.txt >/dev/null 2>&1 &    # background; follow progress.txt
#
# Environment: ORFADC_QUEUE_PYTHON (interpreter; default .venv/bin/python, then python3, then python),
#              ORFADC_QUEUE_OUT_ROOT (default <repo>/results/windows_checks).
set -u
set -f   # queue arguments are never glob-expanded
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
cd "$repo" || exit 1
queue_arg="${1:-jobs/queue.txt}"
case "$queue_arg" in /*) queue="$queue_arg";; *) queue="$here/$queue_arg";; esac
[ -f "$queue" ] || { echo "queue not found: $queue" >&2; exit 2; }

py="${ORFADC_QUEUE_PYTHON:-}"
if [ -z "$py" ]; then
  if [ -x "$repo/.venv/bin/python" ]; then py="$repo/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then py=python3
  else py=python; fi
fi
export PYTHONPATH="$repo/src" PYTHONIOENCODING=utf-8 PYTHONUTF8=1
unset ANTHROPIC_API_KEY OPENAI_API_KEY
if [ -z "${CODEX_HOME:-}" ] && [ -d "$HOME/.codex-cli" ]; then export CODEX_HOME="$HOME/.codex-cli"; fi
export PATH="$HOME/.local/bin:$PATH"   # claude / codex links (docs/133)
# LLM CLIs only honour HTTPS_PROXY, not the macOS system proxy; adopt an enabled system HTTPS proxy when the variable
# is unset (docs/133: direct connections to the Claude login/API were refused with 403).  ssh to the VM is unaffected.
if [ -z "${HTTPS_PROXY:-}${https_proxy:-}" ] && [ "${ORFADC_QUEUE_SYSTEM_PROXY:-1}" = 1 ] && command -v scutil >/dev/null 2>&1; then
  sp="$(scutil --proxy 2>/dev/null)"
  if printf '%s\n' "$sp" | grep -q 'HTTPSEnable : 1'; then
    ph="$(printf '%s\n' "$sp" | awk '/HTTPSProxy :/ {print $3}')"; pp="$(printf '%s\n' "$sp" | awk '/HTTPSPort :/ {print $3}')"
    if [ -n "$ph" ] && [ -n "$pp" ]; then
      export HTTPS_PROXY="http://$ph:$pp" HTTP_PROXY="http://$ph:$pp" NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,172.16.0.0/12,192.168.0.0/16,10.0.0.0/8}"
      system_proxy_note="PROXY from macOS system settings: $ph:$pp"
    fi
  fi
fi

ts="$(date +%Y%m%dT%H%M%S)"
out="${ORFADC_QUEUE_OUT_ROOT:-$repo/results/windows_checks}/${ts}_job"
mkdir -p "$out" || exit 1
progress="$out/progress.txt"
log() { line="$(date +%H:%M:%S) $1"; echo "$line"; echo "$line" >> "$progress"; }
cp "$queue" "$out/queue.txt"
[ -n "${system_proxy_note:-}" ] && log "$system_proxy_note"

i=0
while IFS= read -r raw || [ -n "$raw" ]; do
  line="${raw%$'\r'}"                                   # tolerate CRLF queues written on Windows
  line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [ -z "$line" ] && continue
  case "$line" in \#*) continue;; esac
  if [[ "$line" =~ ^set[[:space:]]+(ORFADC_[A-Z0-9_]+)=([^[:space:]]*)$ ]]; then
    export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
    log "SET ${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
    continue
  fi
  i=$((i + 1))
  read -r -a parts <<< "$line"
  if ! [[ "${parts[0]}" =~ ^[a-z0-9-]+$ ]]; then log "SKIP (not a bench subcommand): $line"; continue; fi
  name="$(printf '%02d_%s' "$i" "${parts[0]}")"
  log "START $name : $line"
  "$py" -m orfadc.repro.bench "${parts[@]}" --out "$out" > "$out/$name.log" 2>&1 < /dev/null
  code=$?
  log "END   $name exit=$code"
done < "$queue"
log "QUEUE DONE"
echo "done $(date +%Y-%m-%dT%H:%M:%S)" > "$out/DONE.txt"
