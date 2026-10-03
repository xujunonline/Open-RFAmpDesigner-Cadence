"""Request X11 input focus for the visible property window; no pointer or keys."""

import ctypes
import re
import subprocess
from pathlib import Path


tree = subprocess.run(
    ["xwininfo", "-root", "-tree"], check=True, capture_output=True, text=True,
).stdout
Path("window_tree_at_focus.txt").write_text(tree, encoding="utf-8")
matches = re.findall(
    r'^\s*(0x[0-9a-f]+) "Edit Object Properties":', tree, re.MULTILINE,
)
if len(matches) != 1:
    raise RuntimeError("expected exactly one Edit Object Properties window")
target = int(matches[0], 16)

x11 = ctypes.CDLL("libX11.so.6")
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
x11.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
display = x11.XOpenDisplay(None)
if not display:
    raise RuntimeError("XOpenDisplay failed")
try:
    x11.XRaiseWindow(display, target)
    x11.XSetInputFocus(display, target, 2, 0)
    x11.XSync(display, 0)
    focused = ctypes.c_ulong()
    revert = ctypes.c_int()
    x11.XGetInputFocus(display, ctypes.byref(focused), ctypes.byref(revert))
    x11.XSync(display, 0)
finally:
    x11.XCloseDisplay(display)
print(f"focus_request_sent=t target=0x{target:x} observed=0x{focused.value:x}")
