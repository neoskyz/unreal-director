#!/usr/bin/env python3
"""Does the Wasm stage start on a plain static server that sends NO COOP / COEP headers?

UE Wasm needs SharedArrayBuffer, which needs a cross-origin isolated page. With the project setting
bInjectIsolationHeaders=True the staged sw.js (a service worker) adds the headers itself: the first load is not
isolated, the page registers the worker and reloads once, the second load is. This test proves that on a server that
sends nothing (GitHub Pages / a bare CDN behave the same).

  python3 scripts/web/isolation_test_web.py --stage Builds/MyGame_Wasm_Shipping/Wasm [--expect "SG_STATE Title"]

Exit 0 = the --expect console line arrived (default: the engine's UE_RUN READY). result.json says whether the page
reloaded under the service worker and whether window.crossOriginIsolated was true at the end.
This is NOT the itch.io case (the game inside a cross-origin iframe): see guides/itch-deploy.md and
scripts/build/prepare_web_upload.py --check-sw.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcommon  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--port", type=int, default=8814)
    ap.add_argument("--out", default="runs/isolation_web")
    ap.add_argument("--expect", default="UE_RUN READY")
    ap.add_argument("--timeout", type=int, default=240)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    srv = webcommon.plain_static_server(a.stage, a.port, out / "http_server.log")
    t0 = time.time()
    seen = {"expect": None, "ready": None, "isolation_reload": None, "not_isolated_msg": None}
    log = open(out / "console.log", "w", buffering=1)

    def on_console(msg):
        t = msg.text
        log.write(f"[{time.time() - t0:7.2f}] {t}\n")
        if "PAGE ISOLATION" in t and seen["isolation_reload"] is None:
            seen["isolation_reload"] = round(time.time() - t0, 1)
        if "UE_RUN READY" in t and seen["ready"] is None:
            seen["ready"] = round(time.time() - t0, 1)
        if a.expect in t and seen["expect"] is None:
            seen["expect"] = round(time.time() - t0, 1)
        if "not cross-origin isolated" in t:
            seen["not_isolated_msg"] = round(time.time() - t0, 1)

    with sync_playwright() as pw:
        b = webcommon.launch(pw)
        page = b.new_context(viewport={"width": 1280, "height": 720}).new_page()
        page.on("console", on_console)
        page.goto(f"http://127.0.0.1:{a.port}/index.html?harness=1", wait_until="load", timeout=120000)
        end = time.time() + a.timeout
        while time.time() < end and seen["expect"] is None:
            page.wait_for_timeout(500)
        try:
            seen["crossOriginIsolated"] = page.evaluate("() => window.crossOriginIsolated")
        except Exception as e:
            seen["crossOriginIsolated"] = f"eval failed: {e}"[:120]
        page.wait_for_timeout(3000)
        page.screenshot(path=str(out / "plain_static.png"))
        b.close()
    srv.kill()
    seen["pass"] = seen["expect"] is not None
    (out / "result.json").write_text(json.dumps(seen, indent=2))
    print(json.dumps(seen, indent=2))
    return 0 if seen["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
