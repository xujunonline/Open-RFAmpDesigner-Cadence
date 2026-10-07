#!/usr/bin/env bash
# Run several job queues in parallel from ONE terminal (each through run_job_queue.sh, same queue format and logs).
#   scripts/run_job_queues_parallel.sh jobs/queue_a.txt jobs/queue_b.txt jobs/queue_c.txt
# Queues start ORFADC_PARALLEL_STAGGER_S seconds apart (default 3), each prints into its own
# results/windows_checks/<ts>_job*/progress.txt; this script prefixes their console lines with the queue name and
# waits for all of them.  Exit code = number of queues whose runner failed (individual design failures are only logged,
# as in run_job_queue.sh; nothing is retried).  The stagger also keeps the per-second output folders of
# run_job_queue.sh distinct.  Do not edit run_job_queue.sh while queues run: bash reads scripts incrementally.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -ge 1 ] || { echo "usage: $0 jobs/<queue1>.txt [jobs/<queue2>.txt ...]" >&2; exit 2; }
for q in "$@"; do
  case "$q" in /*) f="$q";; *) f="$here/$q";; esac
  [ -f "$f" ] || { echo "queue not found: $f" >&2; exit 2; }
done
pids=()
for q in "$@"; do
  tag="$(basename "$q" .txt)"
  ( set -o pipefail; "$here/run_job_queue.sh" "$q" 2>&1 | sed -u "s/^/[$tag] /" ) &
  pids+=("$!")
  echo "[parallel] started $tag (pid $!)"
  sleep "${ORFADC_PARALLEL_STAGGER_S:-3}"
done
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=$((fail + 1)); done
echo "[parallel] all ${#pids[@]} queues finished ($fail runner failures)"
exit "$fail"
