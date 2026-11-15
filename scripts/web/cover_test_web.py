#!/usr/bin/env python3
"""The Wasm page as a player first sees it: no harness switch, the engine page's cover, one click to start.

Waits until the cover asks for the click (document.body.dataset.cover == "click", set by the engine's wasm-play.js;
states: loading, engine, level, ready, click, lifted), saves a screenshot, clicks, and checks that the cover lifts and
that the game prints its first line (--expect).

  python3 scripts/web/cover_test_web.py --stage Builds/MyGame_Wasm_Shipping/Wasm [--expect "SG_STATE Title"]

Starseal replaced the cover with its own page (a BEGIN button, an opening film with Skip and Mute); its test checked
those element ids instead. If you customise the page, extend --click-selector / the checks here the same way.
Exit 0 = cover reached "click", lifted after the click, and --expect arrived.
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
    ap.add_argument("--port", type=int, default=8813)
    ap.add_argument("--out", default="runs/cover")
    ap.add_argument("--viewport", default="1280x720")
    ap.add_argument("--expect", default="UE_RUN READY")
    ap.add_argument("--click-selector", default="", help="click this element instead of the middle of the page")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in a.viewport.split("x"))
    srv, base = webcommon.start_engine_server(a.stage, a.port, out / "serve.log")
    res = {"cover_click_state": False, "lifted": False, "started": False}
    logs: list[str] = []
    try:
        with sync_playwright() as pw:
            b = webcommon.launch(pw)
            page = b.new_page(viewport={"width": w, "height": h})
            page.on("console", lambda m: logs.append(m.text))
            t0 = time.time()
            page.goto(base, wait_until="load", timeout=120000)
            try:
                page.wait_for_function("() => document.body.dataset.cover === 'click'", timeout=240000)
                res["cover_click_state"] = True
                res["seconds_to_click_state"] = round(time.time() - t0, 1)
                page.screenshot(path=str(out / "cover.png"))
                if a.click_selector:
                    page.click(a.click_selector)
                else:
                    page.mouse.click(w // 2, h // 2)
                page.wait_for_function("() => document.body.dataset.cover === 'lifted'", timeout=30000)
                res["lifted"] = True
                end = time.time() + 120
                while time.time() < end and not any(a.expect in l for l in logs):
                    page.wait_for_timeout(500)  # (not time.sleep: console events only arrive while Playwright runs)
                res["started"] = any(a.expect in l for l in logs)
                page.wait_for_timeout(2500)
                page.screenshot(path=str(out / "after_click.png"))
            except Exception as e:  # noqa: BLE001
                res["error"] = str(e)[:300]
                page.screenshot(path=str(out / "cover_timeout.png"))
            res["cover_state"] = page.evaluate("() => document.body.dataset.cover || ''")
            b.close()
    finally:
        srv.terminate()
    (out / "console.log").write_text("\n".join(logs))
    (out / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0 if res["cover_click_state"] and res["lifted"] and res["started"] else 1


if __name__ == "__main__":
    sys.exit(main())
