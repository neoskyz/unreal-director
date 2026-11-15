#!/usr/bin/env python3
"""What a player sees when the browser gives WebGPU no graphics card (hardware acceleration switched off).

Opens the staged build in headless Chromium started with the GPU disabled, waits for the engine page's error card
(#error, with #error-title / #error-text), saves a screenshot and reports its text, how long it took and how many MB
had been downloaded by then. The card should come before the big game files, not after a 100 MB download.

  python3 scripts/web/gpu_message_test_web.py --stage Builds/MyGame_Wasm_Shipping/Wasm [--expect-title "graphics acceleration"]

--expect-title: a phrase the card title must contain (Starseal rewrote the strings in its page's wasm-strings.js).
Exit 0 = the card appeared (and contained --expect-title when given).
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
    ap.add_argument("--port", type=int, default=8815)
    ap.add_argument("--out", default="runs/gpu_msg")
    ap.add_argument("--expect-title", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    srv, base = webcommon.start_engine_server(a.stage, a.port, out / "serve.log")
    res = {"card": False}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="chromium", headless=True, args=["--headless=new", "--disable-gpu", "--disable-software-rasterizer"])
            page = b.new_page(viewport={"width": 1280, "height": 720})
            got = {"bytes": 0}
            page.on("response", lambda r: got.__setitem__("bytes", got["bytes"] + int(r.headers.get("content-length", 0) or 0)))
            logs: list[str] = []
            page.on("console", lambda m: logs.append(m.text))
            t0 = time.time()
            page.goto(base, timeout=120000)
            t1 = time.time()
            try:
                page.wait_for_function("() => { const e = document.getElementById('error'); return e && getComputedStyle(e).display !== 'none'; }", timeout=120000)
                res["card"] = True
            except Exception as e:  # noqa: BLE001
                res["error"] = str(e)[:200]
            res["seconds_after_load"] = round(time.time() - t1, 1)
            res["megabytes_requested_by_then"] = round(got["bytes"] / 1e6, 1)
            res["title"] = page.evaluate("() => (document.getElementById('error-title') || {}).textContent || ''")
            res["text"] = page.evaluate("() => (document.getElementById('error-text') || {}).textContent || ''")
            res["unsupported_line"] = next((l for l in logs if "PAGE UNSUPPORTED" in l or "UE_RUN ERROR" in l), "")
            page.screenshot(path=str(out / "no_gpu_card.png"))
            b.close()
            res["wall_s"] = round(time.time() - t0, 1)
    finally:
        srv.terminate()
    (out / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    ok = res["card"] and (not a.expect_title or a.expect_title.lower() in res.get("title", "").lower())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
