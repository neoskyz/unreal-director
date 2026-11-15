#!/usr/bin/env python3
"""Wasm autoplay regression: serve a staged build, open it in headless Chromium with the game's autoplay switch, take
a page screenshot on every <prefix>SHOT console line (plus timed extra shots), and wait for <prefix>DONE.

  export UE=/path/to/UnrealEngine
  python3 scripts/web/autoplay_web.py --stage Builds/MyGame_Wasm_Shipping/Wasm --out runs/web \
      [--require Title,Explore,Battle,Ending] [--speed 2] [--cover] [--extra "&sgpatrol=1"] \
      [--after "SG_ACT 2=0.3,0.6,0.9;SG_PHASE 2=0.5,1.0"]

The page is opened with ?sgautoplay=1&sgspeed=<speed>&harness=1. harness=1 is the engine page's own switch: it hides
the cover and skips click-to-start, so screenshots show the game. --cover keeps the real player flow and clicks the
cover away (the engine runs behind the cover anyway).

--after takes extra pictures a few seconds after a console line (several specs separated by ';'). Use it at --speed 1
to check continuous action (a hit spark, a throw trail): one screenshot per action proves nothing about the frames
between. Names: x_after<tag><n>_<delay>s.png.

Exit 0 = every --require state reached, <prefix>DONE seen, no <prefix>FAIL / <prefix>WARN. result.json, console.log
and the screenshots go to --out.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcommon  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, help="the staged Wasm folder (index.html at its top)")
    ap.add_argument("--url", default="", help="use an already running server instead of starting serve.py")
    ap.add_argument("--port", type=int, default=8810)
    ap.add_argument("--out", default="runs/web")
    ap.add_argument("--speed", default="2")
    ap.add_argument("--prefix", default="SG_")
    ap.add_argument("--require", default="", help="comma list of states that must appear in <prefix>STATE lines")
    ap.add_argument("--headed", action="store_true", help="real (off-screen) window: can take pointer lock and focus. "
                    "Never while someone uses the machine. Default headless cannot touch the system mouse")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--viewport", default="1280x720")
    ap.add_argument("--cover", action="store_true", help="keep the page cover (real player flow) and click it away")
    ap.add_argument("--autoplay-query", default="sgautoplay=1", help="the game's own URL switch for autoplay")
    ap.add_argument("--extra", default="", help="extra query string, e.g. '&sgpatrol=1'")
    ap.add_argument("--after", default="", help="extra pictures some seconds after a console line, e.g. 'SG_ACT 2=1.2,2.0'")
    a = ap.parse_args()
    P = a.prefix
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    server = None
    base = a.url
    if not base:
        server, base = webcommon.start_engine_server(a.stage, a.port, out / "serve.log")
    url = f"{base}?{a.autoplay_query}&sgspeed={a.speed}" + ("" if a.cover else "&harness=1") + a.extra
    vw, vh = (int(x) for x in a.viewport.split("x"))

    t0 = time.time()
    marks = {}
    states, shots, fps, errors = [], [], [], []
    done = {"ok": False, "fail": False}
    pending_shots: list[str] = []
    timed_shots: list[tuple[float, str]] = []
    after_specs = []
    for k, spec in enumerate([x for x in a.after.split(";") if x.strip()]):
        pre, _, delays = spec.partition("=")
        after_specs.append({"prefix": pre.strip(), "delays": [d for d in delays.split(",") if d.strip()],
                            "tag": "" if k == 0 else "bcdefghijklmnop"[k - 1], "n": 0})
    console = open(out / "console.log", "w", buffering=1)
    pat = re.compile(rf"({re.escape(P)}[A-Z_]+.*)$")

    def on_console(msg):
        text = msg.text
        console.write(f"[{time.time() - t0:7.2f}] {text}\n")
        if "UE_RUN READY" in text and "ready" not in marks:  # the engine page's ready marker
            marks["ready"] = round(time.time() - t0, 1)
            print(f"[{time.time() - t0:6.1f}s] UE_RUN READY", flush=True)
        if "UE_RUN ERROR" in text:
            errors.append(text[:300])
        m = pat.search(text)
        if not m:
            return
        s = m.group(1)
        for sp in after_specs:
            if s.startswith(sp["prefix"]):
                sp["n"] += 1
                for d in sp["delays"]:
                    timed_shots.append((time.time() + float(d), f"x_after{sp['tag']}{sp['n']:02d}_{d.replace('.', 'p')}s"))
        if not s.startswith(P + "EVT"):
            print(f"[{time.time() - t0:6.1f}s] {s}", flush=True)
        if s.startswith(P + "STATE"):
            states.append(s.split()[1])
            marks.setdefault(s.split()[1], round(time.time() - t0, 1))
        elif s.startswith(P + "SHOT"):
            pending_shots.append(s.split()[1])
        elif s.startswith(P + "FPS"):
            fps.append(s)
        elif s.startswith(P + "DONE"):
            done["ok"] = True
        elif s.startswith(P + "FAIL") or s.startswith(P + "WARN"):
            done["fail"] = True

    def flush_shots():
        while pending_shots:
            name = pending_shots.pop(0)
            page.screenshot(path=str(out / f"{name}.png"))
            shots.append(name)

    with sync_playwright() as pw:
        browser = webcommon.launch(pw, a.headed, ["--enable-features=SharedArrayBuffer"])
        page = browser.new_page(viewport={"width": vw, "height": vh})
        page.on("console", on_console)
        page.on("pageerror", lambda e: errors.append(f"pageerror {e}"[:300]))
        page.goto(url, wait_until="load", timeout=120000)
        clicks, next_click = 0, 0.0
        while time.time() - t0 < a.timeout:
            # StartMode=Click: after READY the cover waits for a click. Click until it lifts.
            if a.cover and "ready" in marks and clicks < 15 and time.time() - t0 > next_click:
                try:
                    if page.evaluate("() => document.body.dataset.cover") == "lifted":
                        clicks = 99
                        marks.setdefault("cover_lifted", round(time.time() - t0, 1))
                except Exception:
                    pass
                if clicks < 15:
                    try:
                        page.mouse.click(vw // 2, vh // 3)
                        page.evaluate("() => { if (window.uePage && window.uePage.gesture) window.uePage.gesture(); }")
                        clicks += 1
                        marks.setdefault("clicked", round(time.time() - t0, 1))
                    except Exception as e:
                        errors.append(f"click {e}"[:200])
                    next_click = time.time() - t0 + 2.0
            flush_shots()
            for item in [t for t in timed_shots if t[0] <= time.time()]:
                timed_shots.remove(item)
                page.screenshot(path=str(out / f"{item[1]}.png"))
            if done["ok"] or done["fail"]:
                time.sleep(1.0)
                flush_shots()
                break
            page.wait_for_timeout(100 if timed_shots else 200)
        browser.close()
    if server:
        server.kill()
    console.close()
    needed = [s for s in a.require.split(",") if s]
    missing = [s for s in needed if s not in states]
    result = {"pass": done["ok"] and not done["fail"] and not missing, "marks_s": marks, "states": states, "missing": missing,
              "shots": shots, "fps": fps, "errors": errors[:20], "wall_s": round(time.time() - t0, 1), "headed": a.headed}
    (out / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
