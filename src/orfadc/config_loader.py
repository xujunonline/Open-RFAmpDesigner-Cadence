from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import Spec


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read YAML config files.") from exc
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def load_specs(path: Path) -> list[Spec]:
    data = load_yaml(path)
    specs = [Spec(**item) for item in data.get("specs", [])]
    identifiers = [spec.id for spec in specs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate spec id in specs configuration")
    return specs


def write_json(path: Path, payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(serialized)
