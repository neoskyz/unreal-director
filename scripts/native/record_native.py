#!/usr/bin/env python3
"""Record one segment of an autoplay run as a 1920x1080 video with sound, fully unattended (no screen recording).

The game runs natively (editor -game, uncooked, off-screen) in its recording mode: fixed time step, one PNG per frame,
every audio event logged with its time (reference/cpp/RecordMode.cpp). Then scripts/qc/make_video.py muxes the frames
with an offline re-mix of the audio.

  export UE=/path/to/UnrealEngine UPROJECT=/path/to/MyGame.uproject
  python3 scripts/native/record_native.py --segment capture --out runs/video [--extra "-SGNoHud"]
  # sounds named in the event log are looked up in --sound-dirs (default env UD_SOUND_DIRS)

Writes <out>/seg_<segment>/{frames/, audio_events.jsonl, record.json, game.log} and <out>/seg_<segment>.mp4.
Frame PNGs are deleted after a successful render unless --keep-frames.
Segment names are whatever your game's recording mode defines (Starseal had full, garage_launch, explore, capture,
walk, boss, ending).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mouse_guard import MouseGuard  # noqa: E402
from autoplay_native import editor_binary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("UPROJECT", ""))
    ap.add_argument("--ue", default=os.environ.get("UE", ""))
    ap.add_argument("--segment", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default="runs/video")
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--seed", default="7")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--sound-dirs", default=os.environ.get("UD_SOUND_DIRS", ""), help=f"folders with <name>.wav, '{os.pathsep}' separated")
    ap.add_argument("--extra", default="", help="extra game switches, space separated, e.g. -SGNoHud (no HUD: for a trailer)")
    a = ap.parse_args()
    if not a.project or not a.ue:
        ap.error("--project and --ue (or env UPROJECT / UE) are required")
    out = Path(a.out).resolve()
    seg_dir = out / f"seg_{a.segment}"
    if seg_dir.exists():
        shutil.rmtree(seg_dir)
    (seg_dir / "frames").mkdir(parents=True)
    w, h = a.res.split("x")
    cmd = [str(editor_binary(Path(a.ue))), str(Path(a.project).resolve()), "-game", "-windowed", f"-ResX={w}", f"-ResY={h}",
           "-SGAutoPlay", f"-SGSeed={a.seed}", f"-SGRecord={seg_dir}", f"-SGSegment={a.segment}", f"-SGRecordFps={a.fps}",
           "-stdout", "-unattended", "-RenderOffscreen", "-SGNoMouse", "-nosound", "-NoVerifyGC"] + a.extra.split()
    print("RUN", " ".join(cmd), flush=True)
    t0 = time.time()
    ok = False
    # stdout goes to a file, polled while the game runs: a forked UnrealTraceServer can inherit a stdout pipe and keep
    # it open after the game exits, which would block a `for line in p.stdout` loop forever
    log_path = seg_dir / "game.log"
    with open(log_path, "w") as logf:
        p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    guard = MouseGuard(on_grab=p.kill)
    guard.start()
    seen = 0
    while True:
        alive = p.poll() is None
        with open(log_path, errors="replace") as f:
            lines = f.readlines()
        for line in lines[seen:]:
            if any(k in line for k in ("SG_RECORD", "SG_STATE", "SG_FAIL")) and "Log" not in line.split("SG_")[0]:  # skip the UE_LOG echo
                print(f"[{time.time() - t0:6.1f}s] {line.strip()[-160:]}", flush=True)
            if "SG_RECORD done" in line:
                ok = True
        seen = len(lines)
        if not alive:
            break
        if time.time() - t0 > a.timeout:
            print("TIMEOUT", flush=True)
            p.kill()
            break
        time.sleep(1.0)
    guard.stop()
    print(guard.summary(), flush=True)
    if guard.grabbed:
        print("FAIL: the game grabbed the system mouse", flush=True)
        return 2
    frames = len(list((seg_dir / "frames").glob("frame_*.png")))
    print(f"recorded={ok} frames={frames} wall={time.time() - t0:.0f}s", flush=True)
    if not ok or frames == 0:
        return 1
    mp4 = out / f"seg_{a.segment}.mp4"
    env = dict(os.environ, UD_SOUND_DIRS=a.sound_dirs)
    r = subprocess.run([sys.executable, str(HERE.parent / "qc" / "make_video.py"), "render", "--dir", str(seg_dir), "--out", str(mp4)], env=env)
    if r.returncode != 0:
        return r.returncode
    if not a.keep_frames:
        shutil.rmtree(seg_dir / "frames")
    print(f"wrote {mp4}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
