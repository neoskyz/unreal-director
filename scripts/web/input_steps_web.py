#!/usr/bin/env python3
"""Real-input test for a Wasm build: Playwright sends real clicks and key presses (no autoplay) and every step waits
for the console line that proves the game reacted.

  export UE=/path/to/UnrealEngine
  python3 scripts/web/input_steps_web.py --stage Builds/MyGame_Wasm_Shipping/Wasm --steps my_steps.json --out runs/input

my_steps.json is a list of steps, run in order (see scripts/web/input_steps.example.json):
  {"name": "title_click", "click": [640, 600], "expect": "SG_STATE Intro", "timeout": 20}
  {"name": "next", "key": "Space", "expect": "SG_INTRO 2"}
  {"name": "walk", "hold": "w", "ms": 1300}
  {"name": "look", "drag": [[640, 360], [940, 360]], "steps": 15}       mouse moves (no button) along a line
  {"wait": 1500}
  {"shot": "explore_after_w"}
  {"name": "launch", "click": [890, 143], "expect": "SG_LIFT", "new": true}
"expect" is a prefix of a console line. With "new": true only lines that arrive after the step count (use it when the
same line appears more than once). Coordinates are in --viewport pixels: take them from a screenshot of the same size.
The page is opened with ?harness=1 plus --query (e.g. "&sgtrace=1&sgbattle=1": the game's own debug switches).

Exit 0 = every step with an "expect" saw its line. result.json lists each step's outcome.
How Starseal used it: click the title, Space through the intro, fit three ship parts by mouse, launch, skip a
cutscene, sweep the mouse and read the camera yaw from a trace line, hold W and read the distance walked, click the
attack and seal buttons until a capture. A game-specific script grew out of this; this runner is the reusable core.
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
    ap.add_argument("--steps", required=True)
    ap.add_argument("--port", type=int, default=8812)
    ap.add_argument("--out", default="runs/input_web")
    ap.add_argument("--query", default="", help="extra query string, e.g. '&sgtrace=1'")
    ap.add_argument("--ready", default="UE_RUN READY", help="console line to wait for before the first step")
    ap.add_argument("--viewport", default="1280x720")
    ap.add_argument("--headed", action="store_true", help="real window: can take pointer lock and focus. Not while someone uses the machine")
    a = ap.parse_args()
    steps = json.loads(Path(a.steps).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    server, base = webcommon.start_engine_server(a.stage, a.port, out / "serve.log")
    t0 = time.time()
    lines: list[str] = []
    console = open(out / "console.log", "w", buffering=1)

    def on_console(msg):
        console.write(f"[{time.time() - t0:7.2f}] {msg.text}\n")
        lines.append(msg.text)

    def wait_for(prefix, seconds, start=0):
        end = time.time() + seconds
        while time.time() < end:
            for l in lines[start:]:
                if prefix in l and l[l.index(prefix):].startswith(prefix):
                    return l
            page.wait_for_timeout(200)
        return None

    results = []
    vw, vh = (int(v) for v in a.viewport.split("x"))
    with sync_playwright() as pw:
        browser = webcommon.launch(pw, a.headed)
        page = browser.new_page(viewport={"width": vw, "height": vh})
        page.on("console", on_console)
        page.goto(f"{base}?harness=1{a.query}", wait_until="load", timeout=120000)
        ok = bool(wait_for(a.ready, 240))
        results.append({"name": "ready", "ok": ok})
        page.wait_for_timeout(3000)  # first frames / shaders
        for i, st in enumerate(steps if ok else []):
            name = st.get("name", f"step{i:02d}")
            start = len(lines) if st.get("new") else 0
            if "click" in st:
                page.mouse.click(*st["click"])
            elif "key" in st:
                page.keyboard.press(st["key"])
            elif "hold" in st:
                page.keyboard.down(st["hold"])
                page.wait_for_timeout(int(st.get("ms", 500)))
                page.keyboard.up(st["hold"])
            elif "drag" in st:
                (x0, y0), (x1, y1) = st["drag"]
                n = int(st.get("steps", 15))
                page.mouse.move(x0, y0)
                for k in range(1, n + 1):
                    page.mouse.move(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                    page.wait_for_timeout(30)
            elif "wait" in st:
                page.wait_for_timeout(int(st["wait"]))
            if "shot" in st:
                page.screenshot(path=str(out / f"{st['shot']}.png"))
            if "expect" in st:
                hit = wait_for(st["expect"], float(st.get("timeout", 10)), start)
                results.append({"name": name, "expect": st["expect"], "ok": bool(hit), "line": (hit or "")[:200]})
                print(f"[{time.time() - t0:6.1f}s] {'PASS' if hit else 'FAIL'} {name}: {st['expect']}", flush=True)
            if "after_ms" in st:
                page.wait_for_timeout(int(st["after_ms"]))
        page.screenshot(path=str(out / "final.png"))
        browser.close()
    server.kill()
    console.close()
    passed = all(r["ok"] for r in results)
    (out / "result.json").write_text(json.dumps({"pass": passed, "steps": results, "wall_s": round(time.time() - t0, 1)}, indent=2))
    print(f"pass={passed} ({sum(r['ok'] for r in results)}/{len(results)})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
