#!/usr/bin/env python3
"""Measure stutter in a video: frozen frames, uneven frame steps, one-frame jumps. Light: 320x180 grey via ffmpeg.

  nice -n 15 python3 scripts/qc/qc_cadence.py <video> [--from s] [--to s] [--cuts timeline.json] [--json out.json]

Per frame pair: d = mean |grey[t] - grey[t-1]|. Reported:
  frozen     d < 0.3 x both neighbours inside motion (local median > 0.6): a repeated / held frame = a visible hitch
  runs       consecutive frozen pairs (2+ = a hold that reads as a freeze)
  uneven     log(d[t] / median of d[t-3..t+3]) spread inside moving stretches: ~0.1 even, > 0.5 visible stutter
  jumps      d > 4x the local median (outside cuts): a skipped step
With --cuts (a timeline.json: {"cuts": [seconds of each shot start], "shots": [{"note": ...}]}) everything is grouped per shot and pairs across a cut are ignored.
"""
import argparse, json, subprocess, sys
import numpy as np


def grey_frames(path, t0=None, t1=None):
    a = ["ffmpeg", "-v", "error", "-threads", "2"]
    if t0 is not None:
        a += ["-ss", str(t0)]
    a += ["-i", str(path)]
    if t1 is not None:
        a += ["-t", str(t1 - (t0 or 0))]
    a += ["-vf", "scale=320:180,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(a, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 180, 320).astype(np.float32)


def analyse(d, fps=30.0, skip=()):
    n = len(d)
    frozen, jumps, logs = [], [], []
    for i in range(1, n - 1):
        if i in skip or i + 1 in skip or i - 1 in skip:
            continue
        loc = np.median(d[max(0, i - 3):i + 4])
        # a step much smaller than both neighbours inside motion = a repeated / held frame (also under a slow push-in, where
        # a held frame still differs a little because of the zoom)
        if loc > 0.6 and d[i] < 0.3 * min(d[i - 1], d[i + 1]):
            frozen.append(i)
        if loc > 0.6:
            logs.append(np.log((d[i] + 0.05) / (loc + 0.05)))
            if d[i] > 4 * loc:
                jumps.append(i)
    frozen = sorted(set(frozen))
    runs, k = [], 0
    while k < len(frozen):
        j = k
        while j + 1 < len(frozen) and frozen[j + 1] == frozen[j] + 1:
            j += 1
        runs.append((frozen[k], frozen[j] - frozen[k] + 1))
        k = j + 1
    spread = float(np.std(logs)) if logs else 0.0
    return {"frozen_in_motion": len(frozen), "freeze_runs": [(round(a / fps, 2), l) for a, l in runs], "uneven_spread": round(spread, 3),
            "jumps": [round(i / fps, 2) for i in jumps], "moving_pairs": len(logs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--from", dest="t0", type=float); ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--cuts"); ap.add_argument("--json")
    a = ap.parse_args()
    g = grey_frames(a.video, a.t0, a.t1)
    d = np.concatenate([[0.0], np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))])
    out = {"video": a.video, "frames": len(g)}
    if a.cuts:
        t = json.loads(open(a.cuts).read())
        cf = [round(c * 30) for c in t["cuts"]] + [len(g)]
        out["whole"] = analyse(d, skip=set(cf))
        out["shots"] = []
        for i, s in enumerate(t["shots"]):
            seg = d[cf[i]:cf[i + 1]].copy(); seg[0] = seg[1] if len(seg) > 1 else 0
            r = analyse(seg)
            r.update({"i": i, "note": s["note"][:34], "at": round(cf[i] / 30, 2)})
            out["shots"].append(r)
    else:
        out["whole"] = analyse(d)
    print(json.dumps(out["whole"]))
    for s in out.get("shots", []):
        if s["frozen_in_motion"] or s["uneven_spread"] > 0.45 or s["jumps"]:
            print(f'  shot {s["i"]:2d} @{s["at"]:5.2f} {s["note"]:34s} frozen={s["frozen_in_motion"]:2d} runs={s["freeze_runs"][:4]} spread={s["uneven_spread"]} jumps={s["jumps"][:4]}')
    if a.json:
        open(a.json, "w").write(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
