#!/usr/bin/env python3
"""What takes the space in a packaged build: list the IoStore container and sum by folder.

  export UE=/path/to/UnrealEngine
  python3 scripts/qc/pkg_size.py --project MyGame.uproject \
      --utoc Builds/MyGame_Wasm/Wasm/MyGame/Content/Paks/MyGame-Wasm.utoc [--depth 3] [--csv runs/size/list.csv]

Runs `UnrealPak <uproject> IoStore -List=<abs .utoc> -csv=<abs csv>` (plain `UnrealPak -List=` does not work on
IoStore containers: it needs the project and the IoStore sub-command), then groups the chunks by their first --depth
path parts. Also prints the staged folder's biggest files when --stage is given (web hosts limit single files).

Caveats: cook can only exclude whole folders (DirectoriesToNeverCook), not single assets; move an unused asset into a
never-cooked folder instead (only if nothing references it). UI textures without block compression are big on purpose
(compression frays line art).
"""
import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def unrealpak(ue: Path) -> Path:
    sub = {"darwin": "Mac", "win32": "Win64"}.get(sys.platform, "Linux")
    exe = "UnrealPak.exe" if sys.platform == "win32" else "UnrealPak"
    return ue / "Engine/Binaries" / sub / exe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("UPROJECT", ""))
    ap.add_argument("--ue", default=os.environ.get("UE", ""))
    ap.add_argument("--utoc", required=True)
    ap.add_argument("--csv", default="runs/size/ucas_list.csv")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--stage", default="", help="staged folder: also list its 10 biggest files")
    a = ap.parse_args()
    if not a.project or not a.ue:
        ap.error("--project and --ue (or env UPROJECT / UE) are required")
    out = Path(a.csv).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(unrealpak(Path(a.ue))), str(Path(a.project).resolve()), "IoStore", f"-List={Path(a.utoc).resolve()}", f"-csv={out}"]
    print("RUN", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(r.stdout[-3000:], r.stderr[-3000:])
        return 1
    sums = defaultdict(lambda: [0, 0, 0])  # compressed, uncompressed, chunks
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    # columns (UE 5.9): OrderInContainer, ChunkId, PackageId, PackageName, Filename, ContainerName, Offset,
    # OffsetOnDisk, Size, CompressedSize, Hash, ChunkType, ...  (", " separated)
    head = [h.strip() for h in rows[0]]
    i_name, i_size, i_comp = head.index("Filename"), head.index("Size"), head.index("CompressedSize")
    for row in rows[1:]:
        try:
            name = row[i_name].strip()
            while name.startswith("../"):
                name = name[3:]
            comp = int(row[i_comp])
            size = int(row[i_size])
        except (IndexError, ValueError):
            continue
        key = "/".join(name.strip("/").split("/")[:a.depth])
        s = sums[key]
        s[0] += comp
        s[1] += size
        s[2] += 1
    print(f"{'compressed MB':>14} {'raw MB':>8} {'chunks':>7}  folder")
    for key, (c, u, n) in sorted(sums.items(), key=lambda kv: -kv[1][0])[:40]:
        print(f"{c / 1e6:14.1f} {u / 1e6:8.1f} {n:7d}  {key}")
    if a.stage:
        files = sorted((p for p in Path(a.stage).rglob("*") if p.is_file() and p.suffix != ".br"), key=lambda p: -p.stat().st_size)
        total = sum(p.stat().st_size for p in files)
        print(f"\nstage (without .br): {total / 1e6:.1f} MB in {len(files)} files")
        for p in files[:10]:
            print(f"{p.stat().st_size / 1e6:10.1f} MB  {p.relative_to(a.stage)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
