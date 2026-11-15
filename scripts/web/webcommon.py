"""Shared bits of the Wasm browser tests: serve a staged build, launch Chromium the way that works for UE Wasm.

Lessons baked in (guides/playtesting.md):
- Playwright's default headless mode is the "headless shell", which only has SwiftShader: its WebGPU limits are below
  UE's mobile tier and the device gets lost on the first screenshot. channel="chromium" + --headless=new is the full
  browser in new headless mode, with the real GPU adapter (Metal on a Mac).
- Headless cannot touch your system mouse or keyboard focus. --headed (a real window, parked off-screen) can take
  pointer lock and focus: never use it while someone works on the machine.
- The engine's serve.py (sends COOP / COEP so SharedArrayBuffer works) and Python's http.server both call
  socket.getfqdn() on bind, which can hang ~35 s on a Mac: wait generously, or use plain_static_server() below.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROMIUM_ARGS = ["--enable-unsafe-webgpu", "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                 "--disable-backgrounding-occluded-windows", "--autoplay-policy=no-user-gesture-required"]


def engine_serve_py(ue: str = "") -> Path:
    ue = ue or os.environ.get("UE", "")
    if not ue:
        raise SystemExit("set env UE to the engine root (its Wasm serve.py is used)")
    return Path(ue) / "Engine/Platforms/Wasm/Build/Tools/web/serve.py"


def wait_http(url: str, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def start_engine_server(stage: str, port: int, log_path: Path, ue: str = ""):
    """The engine's own dev server (COOP / COEP headers). Returns (process, base_url) or raises SystemExit."""
    base = f"http://127.0.0.1:{port}/index.html"
    p = subprocess.Popen([sys.executable, str(engine_serve_py(ue)), "--root", stage, "--port", str(port)],
                         stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    if not wait_http(base, 120):
        p.kill()
        raise SystemExit("FAIL serve.py did not come up")
    return p, base


PLAIN_SERVER = (
    "import http.server, socketserver, sys, functools\n"
    "class S(http.server.ThreadingHTTPServer):\n"
    "    def server_bind(self):\n"  # skip getfqdn(): it can hang ~35 s
    "        socketserver.TCPServer.server_bind(self); self.server_name='127.0.0.1'; self.server_port=int(sys.argv[1])\n"
    "H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[2])\n"
    "H.func.extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.js': 'text/javascript'}\n"
    "S(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n")


def plain_static_server(stage: str, port: int, log_path: Path):
    """A static server that sends NO isolation headers (like GitHub Pages or a bare CDN). Returns the process."""
    p = subprocess.Popen([sys.executable, "-c", PLAIN_SERVER, str(port), stage], stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    time.sleep(1.5)
    return p


def launch(pw, headed: bool = False, extra_args=()):
    args = CHROMIUM_ARGS + list(extra_args)
    args += ["--window-position=-32000,-32000"] if headed else ["--headless=new"]
    return pw.chromium.launch(channel="chromium", headless=not headed, args=args)
