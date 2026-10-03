"""Read-only Wfg focus probe using the property's absolute X11 geometry."""

import ctypes
from pathlib import Path
import re
import subprocess
import time


_WINDOW = re.compile(r'^\s*(0x[0-9a-fA-F]+) "Edit Object Properties":', re.MULTILINE)


def property_window_id(tree: str) -> str:
    matches = _WINDOW.findall(tree)
    if len(matches) != 1:
        raise ValueError("expected exactly one Edit Object Properties window")
    return matches[0]


def absolute_geometry(details: str, window_id: str) -> tuple[int, int, int, int]:
    heading = re.search(r"xwininfo: Window id: (0x[0-9a-fA-F]+)\b", details)
    if heading is None or int(heading[1], 16) != int(window_id, 16):
        raise ValueError("xwininfo details refer to a different property window")
    labels = ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height")
    values = []
    for label in labels:
        match = re.search(rf"(?m)^\s*{re.escape(label)}:\s*(-?\d+)\s*$", details)
        if match is None:
            raise ValueError("xwininfo absolute geometry is incomplete")
        values.append(int(match[1]))
    left, top, width, height = values
    if width < 1100 or height < 650 or width > 1920 or height > 1080:
        raise ValueError("property window has unexpected dimensions")
    x, y = left + 700, top + 497
    if not (left < x < left + width and top < y < top + height and 0 <= x < 1920 and 0 <= y < 1080):
        raise ValueError("Wfg click target is outside the visible property window")
    return left, top, width, height


def _xwininfo(*args: str) -> str:
    return subprocess.run(
        ["xwininfo", *args], check=True, capture_output=True, text=True,
    ).stdout


def main() -> None:
    window_id = property_window_id(_xwininfo("-root", "-tree"))
    first = _xwininfo("-id", window_id)
    left, top, width, height = absolute_geometry(first, window_id)
    x, y = left + 700, top + 497

    x11 = ctypes.CDLL("libX11.so.6")
    xtst = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XWarpPointer.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int,
    ]
    x11.XWarpPointer.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeButtonEvent.restype = ctypes.c_int
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("XOpenDisplay failed")
    try:
        root = x11.XDefaultRootWindow(display)
        if not x11.XWarpPointer(display, 0, root, 0, 0, 0, 0, x, y):
            raise RuntimeError("XWarpPointer failed")
        x11.XFlush(display)
        time.sleep(0.2)
        second = _xwininfo("-id", window_id)
        if absolute_geometry(second, window_id) != (left, top, width, height):
            raise RuntimeError("property window moved before the pointer click")
        Path("window_details_at_click.txt").write_text(second, encoding="utf-8")
        if not xtst.XTestFakeButtonEvent(display, 1, 1, 0):
            raise RuntimeError("XTest button press failed")
        if not xtst.XTestFakeButtonEvent(display, 1, 0, 0):
            raise RuntimeError("XTest button release failed")
        x11.XFlush(display)
        time.sleep(0.2)
    finally:
        x11.XCloseDisplay(display)
    print(
        f"click_complete=t window_id={window_id} window_left={left} window_top={top} "
        f"window_width={width} window_height={height} target_x={x} target_y={y} geometry_stable=t"
    )


if __name__ == "__main__":
    main()
