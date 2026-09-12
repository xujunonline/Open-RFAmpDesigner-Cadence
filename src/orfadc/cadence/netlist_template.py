from __future__ import annotations


def render_parameter_block(parameters: dict[str, float | int | str]) -> str:
    lines = ["parameters"]
    for key, value in sorted(parameters.items()):
        lines.append(f"  {key}={value}")
    return "\n".join(lines) + "\n"

