#!/usr/bin/env python3
"""Does a character ever vanish for a frame? Counts dark pixels in a box over a frame sequence and flags 1-2 frame dips.

Found on Starseal: the painted hero was missing for exactly one frame at each change of walking pose (a texture bound
on the frame it was first needed was not ready yet). Nobody sees that in screenshots; a fixed-step recording plus this
check finds it, and proves the fix (0 missing frames).

  python3 scripts/qc/presence_check.py runs/video/seg_walk/frames --box 860,560,1060,760 [--dark 45] [--out result.json]

--box is x0,y0,x1,y1 at 1920x1080 (scaled for other widths): where the character stands while the camera follows it.
--dark is the luminance below which a pixel counts (pick something only the character has: hair, outline, clothes).
A dip is 1-2 frames below 0.3x their neighbours while the neighbours are above half the median (a dialog over the
picture is a long stretch, not a dip, and does not count). In a dark scene (space), the dip is shallower: tune --ratio.
Exit 0 = no frame without the character. Needs numpy and Pillow.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames", help="folder with frame_*.png")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 at 1920x1080")
    ap.add_argument("--dark", type=float, default=45.0)
    ap.add_argument("--ratio", type=float, default=0.3, help="a dip is below this share of its neighbours")
    ap.add_argument("--glob", default="frame_*.png")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    files = sorted(Path(a.frames).glob(a.glob))
    if not files:
        print("no frames")
        return 2
    x0, y0, x1, y1 = (int(v) for v in a.box.split(","))
    counts = []
    for f in files:
        im = np.asarray(Image.open(f).convert("RGB"), dtype=np.int16)
        k = im.shape[1] / 1920.0
        box = (int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k))
        r = im[box[1]:box[3], box[0]:box[2]]
        lum = 0.299 * r[..., 0] + 0.587 * r[..., 1] + 0.114 * r[..., 2]
        counts.append(int((lum < a.dark).sum()))
    med = float(np.median(counts))
    missing = []
    for i in range(1, len(counts) - 1):
        for span in (1, 2):
            j = i + span
            if j >= len(counts):
                continue
            ref = min(counts[i - 1], counts[j])
            if ref > 0.5 * med and max(counts[i:j]) < a.ratio * ref:
                missing += [files[k].name for k in range(i, j) if files[k].name not in missing]
    res = {"frames": len(files), "median_dark_px": med, "min_dark_px": min(counts), "missing": missing, "pass": not missing}
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k != "missing"} | {"missing_count": len(missing), "missing_first": missing[:10]}, indent=2))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
