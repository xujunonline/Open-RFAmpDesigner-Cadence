"""Click the visible Wfg input without typing or submitting the form."""

import ctypes
import re
import subprocess
import time


tree = subprocess.run(
    ["xwininfo", "-root", "-tree"], check=True, capture_output=True, text=True,
).stdout
matches = re.findall(
    r'^\s*0x[0-9a-f]+ "Edit Object Properties":.*?\s+(\d+)x(\d+)\+(\d+)\+(\d+)\s',
    tree, re.MULTILINE,
)
if len(matches) != 1:
    raise RuntimeError("expected exactly one Edit Object Properties window")
width, height, left, top = map(int, matches[0])
if width < 1100 or height < 650:
    raise RuntimeError("property window is too small for the observed field geometry")
x, y = left + 700, top + 497
if not (left < x < left + width and top < y < top + height):
    raise RuntimeError("click target is outside the property window")

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
xtst.XTestFakeButtonEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong,
]
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
    if not xtst.XTestFakeButtonEvent(display, 1, 1, 0):
        raise RuntimeError("XTest button press failed")
    if not xtst.XTestFakeButtonEvent(display, 1, 0, 0):
        raise RuntimeError("XTest button release failed")
    x11.XFlush(display)
    time.sleep(0.2)
finally:
    x11.XCloseDisplay(display)
print(f"click_complete=t target_x={x} target_y={y}")
