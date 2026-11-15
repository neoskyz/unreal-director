#!/usr/bin/env python3
"""Native autoplay regression run, off-screen, without ever touching your mouse.

Launches the uncooked game (UnrealEditor <project> -game) with the game's own autoplay switch, reads its log lines
(see guides/log-protocol.md), and waits for <prefix>DONE / <prefix>FAIL / exit. Screenshots that the game requests
with <prefix>SHOT land in --shots (the game must honour -SGShotDir=<abs dir>; see reference/cpp/AutoplaySwitches.cpp).

  export UE=/path/to/UnrealEngine            # engine built from source
  python3 scripts/native/autoplay_native.py --project /path/to/MyGame.uproject \
      --require Title,Explore,Battle,Ending --speed 2 --shots runs/native

Exit 0 = <prefix>DONE seen, no <prefix>FAIL / <prefix>WARN, every --require state reached, mouse never grabbed.
Exit 2 = the game grabbed the system mouse (MouseGuard killed it). Exit 1 = anything else.

The switches -SGAutoPlay / -SGAutoPlayExit / -SGSpeed= / -SGShotDir= / -SGNoMouse / -SGAgainCheck are the ones the
Starseal game code understood (reference/cpp). Rename them with --autoplay-args if your game uses other names.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mouse_guard import MouseGuard  # noqa: E402


def editor_binary(ue: Path) -> Path:
    if sys.platform == "darwin":
        return ue / "Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
    if sys.platform.startswith("win"):
        return ue / "Engine/Binaries/Win64/UnrealEditor.exe"
    return ue / "Engine/Binaries/Linux/UnrealEditor"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("UPROJECT", ""), help="the .uproject (or env UPROJECT)")
    ap.add_argument("--ue", default=os.environ.get("UE", ""), help="engine root (or env UE)")
    ap.add_argument("--speed", default="1")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--shots", default="runs/native")
    ap.add_argument("--res", default="1280x720", help="keep it at or below your screen size (a bigger window was seen taking focus)")
    ap.add_argument("--log", default="", help="raw game output (default <shots>/autoplay_native.log)")
    ap.add_argument("--prefix", default="SG_", help="log line prefix the game prints (default SG_)")
    ap.add_argument("--require", default="", help="comma list of states that must appear in <prefix>STATE lines")
    ap.add_argument("--sound", action="store_true", help="run with the audio device (default -nosound)")
    ap.add_argument("--again", action="store_true", help="also require <prefix>AGAIN_OK (a second run after Play Again)")
    ap.add_argument("--until", default="", help="quick look: stop once this <prefix>SHOT name was taken (exit 0)")
    ap.add_argument("--autoplay-args", default="-SGAutoPlay -SGAutoPlayExit -SGNoMouse",
                    help="the game's own switches that turn autoplay on and quit at the end")
    ap.add_argument("--extra", default="", help="extra command-line switches, space separated")
    a = ap.parse_args()
    if not a.project or not a.ue:
        ap.error("--project and --ue (or env UPROJECT / UE) are required")
    P = a.prefix
    shots = Path(a.shots).resolve()  # the game resolves a relative path against its binary's folder, not yours
    shots.mkdir(parents=True, exist_ok=True)
    log_path = Path(a.log) if a.log else shots / "autoplay_native.log"
    w, h = a.res.split("x")
    # -RenderOffscreen: no window on your screen. With the game's no-mouse mode it never captures the cursor;
    # MouseGuard below kills the run if that ever regresses.
    cmd = [str(editor_binary(Path(a.ue))), str(Path(a.project).resolve()), "-game", "-windowed", f"-ResX={w}", f"-ResY={h}",
           f"-SGSpeed={a.speed}", f"-SGShotDir={shots}", "-stdout", "-unattended", "-RenderOffscreen", "-NoVerifyGC"]
    cmd += a.autoplay_args.split() + ([] if a.sound else ["-nosound"]) + (["-SGAgainCheck"] if a.again else []) + a.extra.split()
    print("RUN", " ".join(cmd), flush=True)
    needed = [s for s in a.require.split(",") if s]
    t0 = time.time()
    states, lines = [], []
    done = fail = False
    pat = re.compile(rf"({re.escape(P)}[A-Z_]+.*)$")
    with open(log_path, "w") as logf:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        guard = MouseGuard(on_grab=p.kill)
        guard.start()
        try:
            for line in p.stdout:
                logf.write(line)
                m = pat.search(line.rstrip())
                # (UE_LOG echoes the same line with a category prefix: count the plain stdout copy only)
                if m and "Log" not in line.split(P)[0]:
                    s = m.group(1)
                    if not s.startswith(P + "EVT"):
                        print(f"[{time.time() - t0:6.1f}s] {s}", flush=True)
                    lines.append(s)
                    if s.startswith(P + "STATE"):
                        states.append(s.split()[1])
                    if s.startswith(P + "DONE"):
                        done = True
                    if s.startswith(P + "FAIL") or s.startswith(P + "WARN"):
                        fail = True
                    # stop reading once the run is over: a forked UnrealTraceServer can keep the stdout pipe open
                    # after the game exits, so waiting for EOF may hang forever
                    if (s.startswith(P + "DONE") and not a.again) or s.startswith(P + "AGAIN_OK") or s.startswith(P + "FAIL"):
                        break
                    if a.until and s.startswith(P + "SHOT") and s.split()[1] == a.until:
                        time.sleep(2.0)  # the PNG is written a frame or two later
                        p.kill()
                        print(f"UNTIL {a.until} reached", flush=True)
                        p.wait(timeout=60)
                        return 2 if guard.grabbed else 0
                if time.time() - t0 > a.timeout:
                    print("TIMEOUT", flush=True)
                    p.kill()
                    break
        finally:
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
            guard.stop()
            print(guard.summary(), flush=True)
    if guard.grabbed:
        print("FAIL: the game grabbed the system mouse", flush=True)
        return 2
    missing = [s for s in needed if s not in states]
    again_ok = (not a.again) or any(l.startswith(P + "AGAIN_OK") for l in lines)
    print(f"states={states}")
    print(f"done={done} fail={fail} missing={missing} again_ok={again_ok} rc={p.returncode} wall={time.time() - t0:.0f}s")
    return 0 if done and not fail and not missing and again_ok else 1


if __name__ == "__main__":
    sys.exit(main())
