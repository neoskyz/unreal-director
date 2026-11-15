#!/usr/bin/env python3
"""Labelled contact sheet: many screenshots on one page, for a first look (never as the only look).

  python3 scripts/qc/contact_sheet.py out.png runs/web/*.png [--tile 480] [--cols 4]

A sheet is for spotting which pictures to open. Small tiles hide exactly the things that go wrong (a black word, a
1-pixel seam, a blurred texture, a particle in the wrong place): open every picture that matters at full size before
calling a build good (guides/screenshot-qa.md). Needs Pillow.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--tile", type=int, default=480, help="longest side of a tile, px")
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()
    files = sorted(a.images)
    cols = min(a.cols, len(files))
    rows = (len(files) + cols - 1) // cols
    label_h = 18
    sheet = Image.new("RGB", (cols * a.tile, rows * (a.tile + label_h)), (20, 20, 24))
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGBA")
        im.thumbnail((a.tile, a.tile))
        bg = Image.new("RGBA", im.size, (60, 60, 66, 255))  # transparent areas show as grey, not black
        bg.alpha_composite(im)
        x, y = (i % cols) * a.tile, (i // cols) * (a.tile + label_h)
        sheet.paste(bg.convert("RGB"), (x, y + label_h))
        draw.text((x + 4, y + 3), Path(f).stem, fill=(230, 230, 230))
    sheet.save(a.out)
    print(f"wrote {a.out} ({len(files)} pictures)")


if __name__ == "__main__":
    main()
