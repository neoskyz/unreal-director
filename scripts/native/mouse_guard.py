"""Watches the system mouse while a native (non-browser) game run is going, so a test can never fight the user for it.

You keep working on this machine while an agent runs tests. A game window that captures the mouse hides the cursor and
warps it to the middle of its window every frame (macOS high-precision mouse mode), which makes the machine unusable.
The game itself should not do that in unattended runs (see reference/cpp/NoMouse.cpp); this guard is the second line
of defence:

  guard = MouseGuard(on_grab=lambda: p.kill()); guard.start() ... guard.stop(); print(guard.summary())

It samples the cursor position (CoreGraphics, no permissions needed) 5 times a second. A cursor that sits on the exact
centre of a display for 3 samples in a row is a program pinning it there (a hand cannot hold a mouse still on one exact
pixel pair that happens to be the centre): on_grab is called once, and the run should fail. It also notes whether the
game became the frontmost app (focus stolen), which is reported but does not fail the run.
"""
import ctypes
import ctypes.util
import subprocess
import threading
import time


class _Pt(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]


def _cg():
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = _Pt
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
    cg.CGDisplayBounds.restype = _Rect
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    return cg, cf


def cursor_pos(cg=None, cf=None):
    if cg is None:
        cg, cf = _cg()
    e = cg.CGEventCreate(None)
    p = cg.CGEventGetLocation(e)
    cf.CFRelease(e)
    return (p.x, p.y)


def display_centres(cg):
    ids = (ctypes.c_uint32 * 16)()
    n = ctypes.c_uint32(0)
    cg.CGGetActiveDisplayList(16, ids, ctypes.byref(n))
    out = []
    for i in range(n.value):
        r = cg.CGDisplayBounds(ids[i])
        out.append((r.x + r.w / 2.0, r.y + r.h / 2.0))
    return out


def front_app():
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=5).stdout.strip()
        info = subprocess.run(["lsappinfo", "info", "-only", "name", asn], capture_output=True, text=True, timeout=5).stdout
        return info.strip().split('"')[1] if '"' in info else "?"  # first line: "<name>" ASN:... (in front)
    except Exception:
        return "?"


class MouseGuard(threading.Thread):
    def __init__(self, on_grab=None, app_name="UnrealEditor", period=0.2):
        super().__init__(daemon=True)
        self.on_grab, self.app_name, self.period = on_grab, app_name, period
        self.samples = self.centre_hits = self.front_hits = self.front_checks = 0
        self.grabbed = False
        self.min_centre_dist = 1e9
        self._stop_evt = threading.Event()
        try:
            self.cg, self.cf = _cg()
            self.centres = display_centres(self.cg)
        except Exception as e:  # not macOS: nothing to guard
            self.cg = None
            self.centres = []
            print(f"mouse guard off: {e}", flush=True)

    def run(self):
        if not self.cg:
            return
        streak = 0
        last_front = 0.0
        while not self._stop_evt.is_set():
            x, y = cursor_pos(self.cg, self.cf)
            self.samples += 1
            d = min((abs(x - cx) + abs(y - cy) for cx, cy in self.centres), default=1e9)
            self.min_centre_dist = min(self.min_centre_dist, d)
            if d <= 2.0:
                self.centre_hits += 1
                streak += 1
            else:
                streak = 0
            if streak >= 3 and not self.grabbed:
                self.grabbed = True
                print("SG_MOUSE_GRAB the system cursor is pinned to the centre of a display: stopping the game", flush=True)
                if self.on_grab:
                    self.on_grab()
            if time.time() - last_front > 2.0:
                last_front = time.time()
                self.front_checks += 1
                if self.app_name.lower() in front_app().lower():
                    self.front_hits += 1
            self._stop_evt.wait(self.period)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=5)

    def summary(self):
        return (f"MOUSE_GUARD samples={self.samples} centre_hits={self.centre_hits} grabbed={self.grabbed} "
                f"min_centre_dist={self.min_centre_dist:.0f}px front_app_hits={self.front_hits}/{self.front_checks}")


if __name__ == "__main__":  # quick self-check: where is the cursor, which app is in front
    cg, cf = _cg()
    print("cursor", cursor_pos(cg, cf), "display centres", display_centres(cg), "front app", front_app())
