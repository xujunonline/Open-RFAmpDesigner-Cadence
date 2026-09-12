from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..config_loader import load_yaml


Executor = Callable[..., subprocess.CompletedProcess[str]]
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.+/-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]*$")
_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/+\-]+$")


@dataclass(frozen=True)
class RemoteCadenceConfig:
    host: str
    user: str
    port: int = 22
    identity_file: Path | None = None
    remote_root: str = "/tmp/open-rfampdesigner"
    ssh_bin: str = "ssh"
    scp_bin: str = "scp"
    ocean_bin: str = "ocean"
    spectre_bin: str = "spectre"
    ocean_nograph: bool = True
    display: str | None = None
    xauthority: str | None = None
    connect_timeout_seconds: int = 10
    command_timeout_seconds: int = 300
    strict_host_key_checking: str = "accept-new"

    def __post_init__(self) -> None:
        if not self.host.strip() or not self.user.strip():
            raise ValueError("remote host and user are required")
        if not _HOST_RE.fullmatch(self.host) or not _USER_RE.fullmatch(self.user):
            raise ValueError("remote host or user contains unsupported characters")
        if not 1 <= self.port <= 65535:
            raise ValueError("remote port must be between 1 and 65535")
        _validate_remote_path(self.remote_root, require_absolute=True)
        if self.strict_host_key_checking not in {"yes", "accept-new"}:
            raise ValueError("strict_host_key_checking must be 'yes' or 'accept-new'")

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass(frozen=True)
class CommandResult:
    action: str
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        payload["argv"] = list(self.argv)
        return payload


def load_remote_config(path: Path) -> RemoteCadenceConfig:
    data = load_yaml(path)
    remote = data.get("remote", {})
    cadence = data.get("cadence", {})
    if not isinstance(remote, dict) or not isinstance(cadence, dict):
        raise ValueError("remote and cadence config sections must be mappings")

    host = _required_string(remote, "host")
    user = _required_string(remote, "user")
    identity_value = remote.get("identity_file")
    identity_file = None
    if identity_value:
        expanded = os.path.expanduser(os.path.expandvars(str(identity_value)))
        if "$" in expanded or "%" in expanded:
            raise ValueError("identity_file contains an unresolved environment variable")
        identity_file = Path(expanded)

    return RemoteCadenceConfig(
        host=host,
        user=user,
        port=int(remote.get("port", 22)),
        identity_file=identity_file,
        remote_root=str(remote.get("work_root", "/tmp/open-rfampdesigner")),
        ssh_bin=str(remote.get("ssh_bin", "ssh")),
        scp_bin=str(remote.get("scp_bin", "scp")),
        ocean_bin=str(cadence.get("ocean_bin", "ocean")),
        spectre_bin=str(cadence.get("spectre_bin", "spectre")),
        ocean_nograph=_boolean(cadence.get("ocean_nograph", True), "cadence.ocean_nograph"),
        display=_optional_string(cadence.get("display")),
        xauthority=_optional_string(cadence.get("xauthority")),
        connect_timeout_seconds=int(remote.get("connect_timeout_seconds", 10)),
        command_timeout_seconds=int(remote.get("command_timeout_seconds", 300)),
        strict_host_key_checking=str(remote.get("strict_host_key_checking", "accept-new")),
    )


class RemoteRunner:
    def __init__(
        self,
        config: RemoteCadenceConfig,
        *,
        executor: Executor = subprocess.run,
    ) -> None:
        self.config = config
        self._executor = executor

    def run_remote(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        if not command:
            raise ValueError("remote command must not be empty")
        shell_command = shlex.join([str(part) for part in command])
        return self.run_shell(shell_command, cwd=cwd, timeout_seconds=timeout_seconds)

    def run_shell(
        self,
        shell_command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        if not shell_command.strip() or "\x00" in shell_command:
            raise ValueError("remote shell command is empty or invalid")
        if cwd is not None:
            _validate_remote_path(cwd, require_absolute=True)
            shell_command = f"cd {shlex.quote(cwd)} && {shell_command}"
        remote_command = f"bash -lc {shlex.quote(shell_command)}"
        argv = [*self._ssh_base(), self.config.destination, remote_command]
        return self._execute("ssh", argv, timeout_seconds)

    def ensure_remote_dir(self, remote_dir: str) -> CommandResult:
        _validate_remote_path(remote_dir, require_absolute=True)
        return self.run_remote(["mkdir", "-p", "--", remote_dir])

    def upload(self, local_path: Path, remote_path: str) -> CommandResult:
        local_path = local_path.resolve()
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        _validate_remote_path(remote_path, require_absolute=True)
        argv = [
            *self._scp_base(),
            str(local_path),
            f"{self.config.destination}:{remote_path}",
        ]
        return self._execute("upload", argv, None)

    def download(self, remote_path: str, local_path: Path) -> CommandResult:
        _validate_remote_path(remote_path, require_absolute=True)
        local_path = local_path.resolve()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            *self._scp_base(),
            f"{self.config.destination}:{remote_path}",
            str(local_path),
        ]
        return self._execute("download", argv, None)

    def probe(self, tools: Sequence[str] = ("ocean", "spectre", "virtuoso")) -> dict[str, Any]:
        lines = [
            "printf 'user=%s\\n' \"$(id -un)\"",
            "printf 'host=%s\\n' \"$(hostname -f 2>/dev/null || hostname)\"",
            "printf 'pwd=%s\\n' \"$PWD\"",
        ]
        for tool in tools:
            if not _TOOL_NAME_RE.fullmatch(tool):
                raise ValueError(f"invalid tool name: {tool!r}")
            quoted_tool = shlex.quote(tool)
            lines.append(
                f"found=\"$(command -v {quoted_tool} 2>/dev/null || true)\"; "
                f"printf 'tool.{tool}=%s\\n' \"$found\""
            )
        result = self.run_shell("\n".join(lines))
        values: dict[str, str] = {}
        if result.ok:
            for line in result.stdout.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value
        return {
            "status": "ok" if result.ok else "failed",
            "connection": result.to_dict(),
            "user": values.get("user"),
            "host": values.get("host"),
            "pwd": values.get("pwd"),
            "tools": {
                tool: {
                    "found": bool(values.get(f"tool.{tool}")),
                    "path": values.get(f"tool.{tool}") or None,
                }
                for tool in tools
            },
        }

    def verify_transfer(
        self,
        local_source: Path,
        local_download: Path,
        *,
        remote_name: str | None = None,
    ) -> dict[str, Any]:
        local_source = local_source.resolve()
        if not local_source.is_file():
            raise FileNotFoundError(local_source)
        name = remote_name or local_source.name
        if PurePosixPath(name).name != name:
            raise ValueError("remote_name must be a file name, not a path")
        remote_dir = _join_remote(self.config.remote_root, "transfer_probe")
        remote_path = _join_remote(remote_dir, name)

        mkdir_result = self.ensure_remote_dir(remote_dir)
        if not mkdir_result.ok:
            return _transfer_result("mkdir_failed", mkdir_result=mkdir_result)
        upload_result = self.upload(local_source, remote_path)
        if not upload_result.ok:
            return _transfer_result(
                "upload_failed", mkdir_result=mkdir_result, upload_result=upload_result
            )
        download_result = self.download(remote_path, local_download)
        if not download_result.ok:
            return _transfer_result(
                "download_failed",
                mkdir_result=mkdir_result,
                upload_result=upload_result,
                download_result=download_result,
            )

        source_hash = _sha256(local_source)
        downloaded_hash = _sha256(local_download.resolve())
        return {
            "status": "ok" if source_hash == downloaded_hash else "hash_mismatch",
            "source_sha256": source_hash,
            "downloaded_sha256": downloaded_hash,
            "mkdir": mkdir_result.to_dict(),
            "upload": upload_result.to_dict(),
            "download": download_result.to_dict(),
        }

    def run_ocean_script(
        self,
        local_script: Path,
        *,
        run_name: str,
        nograph: bool | None = None,
        local_log: Path | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name):
            raise ValueError("run_name may contain only letters, digits, dot, underscore, and dash")
        local_script = local_script.resolve()
        if local_script.suffix.lower() not in {".ocn", ".il"}:
            raise ValueError("OCEAN/SKILL script must use .ocn or .il")
        remote_dir = _join_remote(self.config.remote_root, run_name)
        remote_script = _join_remote(remote_dir, local_script.name)
        remote_log = _join_remote(remote_dir, f"ocean_{local_script.stem}.log")

        mkdir_result = self.ensure_remote_dir(remote_dir)
        if not mkdir_result.ok:
            return {"status": "mkdir_failed", "mkdir": mkdir_result.to_dict()}
        upload_result = self.upload(local_script, remote_script)
        if not upload_result.ok:
            return {
                "status": "upload_failed",
                "mkdir": mkdir_result.to_dict(),
                "upload": upload_result.to_dict(),
            }

        command = ["env"]
        if self.config.display:
            command.append(f"DISPLAY={self.config.display}")
        if self.config.xauthority:
            command.append(f"XAUTHORITY={self.config.xauthority}")
        command.append(self.config.ocean_bin)
        use_nograph = self.config.ocean_nograph if nograph is None else nograph
        if use_nograph:
            command.append("-nograph")
        command.extend(["-restore", local_script.name, "-log", remote_log])
        ocean_result = self.run_remote(command, cwd=remote_dir)
        payload: dict[str, Any] = {
            "status": "ok" if ocean_result.ok else "ocean_failed",
            "mkdir": mkdir_result.to_dict(),
            "upload": upload_result.to_dict(),
            "ocean": ocean_result.to_dict(),
            "remote_dir": remote_dir,
            "remote_log": remote_log,
        }
        if local_log is not None and ocean_result.ok:
            log_result = self.download(remote_log, local_log)
            payload["log_download"] = log_result.to_dict()
            if not log_result.ok:
                payload["status"] = "log_download_failed"
        return payload

    def _ssh_base(self) -> list[str]:
        return [self.config.ssh_bin, *self._common_options(port_flag="-p")]

    def _scp_base(self) -> list[str]:
        return [self.config.scp_bin, *self._common_options(port_flag="-P")]

    def _common_options(self, *, port_flag: str) -> list[str]:
        options = [
            port_flag,
            str(self.config.port),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.config.connect_timeout_seconds}",
            "-o",
            f"StrictHostKeyChecking={self.config.strict_host_key_checking}",
        ]
        if self.config.identity_file is not None:
            identity_file = self.config.identity_file.expanduser().resolve()
            if not identity_file.is_file():
                raise FileNotFoundError(identity_file)
            options.extend(["-i", str(identity_file), "-o", "IdentitiesOnly=yes"])
        return options

    def _execute(
        self,
        action: str,
        argv: list[str],
        timeout_seconds: int | None,
    ) -> CommandResult:
        timeout = timeout_seconds or self.config.command_timeout_seconds
        try:
            completed = self._executor(
                argv,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action=action,
                argv=tuple(_redact_identity(argv)),
                returncode=124,
                stdout=_timeout_text(exc.stdout),
                stderr=f"command timed out after {timeout} seconds",
            )
        return CommandResult(
            action=action,
            argv=tuple(_redact_identity(argv)),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"remote.{key} must be set in the local config")
    return str(value).strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be true or false")
    return value


def _validate_remote_path(path: str, *, require_absolute: bool) -> None:
    if not path or any(char in path for char in "\r\n\x00"):
        raise ValueError("remote path is empty or invalid")
    if any(char.isspace() for char in path):
        raise ValueError("remote paths containing whitespace are not supported")
    if require_absolute and not PurePosixPath(path).is_absolute():
        raise ValueError(f"remote path must be absolute: {path}")
    if require_absolute and not _REMOTE_PATH_RE.fullmatch(path):
        raise ValueError(f"remote path contains unsupported characters: {path}")
    if ".." in PurePosixPath(path).parts:
        raise ValueError(f"remote path must not contain '..': {path}")


def _join_remote(root: str, *parts: str) -> str:
    path = PurePosixPath(root).joinpath(*parts)
    text = str(path)
    _validate_remote_path(text, require_absolute=True)
    return text


def _redact_identity(argv: Sequence[str]) -> list[str]:
    redacted = list(argv)
    for index, value in enumerate(redacted[:-1]):
        if value == "-i":
            redacted[index + 1] = "<identity-file>"
    return redacted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timeout_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _transfer_result(status: str, **steps: CommandResult | None) -> dict[str, Any]:
    return {
        "status": status,
        **{name.removesuffix("_result"): value.to_dict() for name, value in steps.items() if value},
    }
