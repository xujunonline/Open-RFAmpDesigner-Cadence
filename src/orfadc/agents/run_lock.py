from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def agent_run_lock(run_dir: Path) -> Iterator[None]:
    """Hold an OS-released writer lock for one agent run directory."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("agent run directory is missing or unsafe")
    path = run_dir / "agent_writer.lock"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("agent writer lock path is unsafe")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("agent run is already owned by another writer") from exc
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("agent run is already owned by another writer") from exc
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"1")
                os.fsync(fd)
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
