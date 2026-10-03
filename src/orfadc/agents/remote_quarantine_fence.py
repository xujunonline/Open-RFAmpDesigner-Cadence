from __future__ import annotations

import base64
import hashlib
import json
import re

from orfadc.cadence.remote_runner import RemoteRunner


FENCE_FILE = ".orfadc_quarantine_fence_v1.json"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PUBLISH_SCRIPT = r'''
# ORFADC_QUARANTINE_FENCE_PUBLISH_V1
set -eu
target='.orfadc_quarantine_fence_v1.json'
encoded="$1"
[ ! -L "$target" ] || exit 12
temporary="$(mktemp './.orfadc_quarantine_fence_v1.tmp.XXXXXXXX')" || exit 13
trap 'rm -f -- "$temporary"' EXIT
printf '%s' "$encoded" | base64 -d > "$temporary" || exit 14
chmod 600 "$temporary"
if ln "$temporary" "$target" 2>/dev/null; then
    printf 'created\n'
elif [ -f "$target" ] && [ ! -L "$target" ] && cmp -s -- "$temporary" "$target"; then
    printf 'existing_same\n'
else
    printf 'conflict\n'
fi
'''
_READ_SCRIPT = r'''
# ORFADC_QUARANTINE_FENCE_READ_V1
set -eu
target='.orfadc_quarantine_fence_v1.json'
[ -f "$target" ] && [ ! -L "$target" ] || exit 12
sha256sum -- "$target"
'''


def fence_bytes(payload: dict) -> bytes:
    """Canonical, bounded decision bytes shared by competing controllers."""
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if len(raw) > 4096:
        raise ValueError("remote quarantine fence is oversized")
    return raw


def remote_fence_sha256(runner: RemoteRunner, remote_dir: str) -> str:
    """Read only: validate the immutable decision's remote digest."""
    result = runner.run_remote(
        ["bash", "-c", _READ_SCRIPT], cwd=remote_dir, timeout_seconds=30,
    )
    if not result.ok or len(result.stdout) > 128:
        raise ValueError("remote quarantine fence is unavailable or unsafe")
    digest, separator, name = result.stdout.strip().partition("  ")
    if separator != "  " or name != FENCE_FILE or not _SHA256.fullmatch(digest):
        raise ValueError("remote quarantine fence digest is malformed")
    return digest


def publish_remote_fence(
    runner: RemoteRunner, remote_dir: str, payload: dict,
) -> tuple[str, bytes]:
    """First immutable remote decision wins; identical retries are idempotent."""
    raw = fence_bytes(payload)
    encoded = base64.b64encode(raw).decode("ascii")
    result = runner.run_remote(
        ["bash", "-c", _PUBLISH_SCRIPT, "--", encoded],
        cwd=remote_dir, timeout_seconds=30,
    )
    if not result.ok or result.stdout not in {"created\n", "existing_same\n"}:
        raise ValueError("remote quarantine fence is unknown or conflicts with this decision")
    expected = hashlib.sha256(raw).hexdigest()
    if remote_fence_sha256(runner, remote_dir) != expected:
        raise ValueError("remote quarantine fence changed after publication")
    return result.stdout.strip(), raw
