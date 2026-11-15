#!/usr/bin/env python3
"""Check a staged UE Wasm build before it goes to a host (itch.io or a jam), fix the itch iframe header, zip it.

  python3 scripts/build/prepare_web_upload.py Builds/MyGame_Wasm_Shipping/Wasm \
      [--patch-sw] [--zip dist/MyGame_web.zip] [--max-total-mb 500] [--max-file-mb 200]

Checks:
- index.html at the top of the folder.
- Total size and the biggest single file, WITHOUT the .br files. The .br copies are optional pre-compressed twins for
  hosts that serve them through _headers (Cloudflare Pages style); the loader never asks for them, and itch.io gzips
  html / js / wasm itself. Leaving them out took Starseal's upload from ~227 MB to under 200 MB.
- sw.js (the service worker that makes the page cross-origin isolated, bInjectIsolationHeaders=True): the response it
  builds for the game page's own navigation must carry Cross-Origin-Resource-Policy: cross-origin. With the engine's
  default same-origin, the page cannot be embedded by a cross-origin parent that requires CORP, which is exactly
  itch.io's case (the game runs in an iframe on another origin). --patch-sw rewrites that one header in the staged
  copy; better, patch the engine template (Engine/Platforms/Wasm/Build/Template/sw.js, function isolated()) once.
  A patched sw.js makes sw.js.br stale: it is left out of the zip anyway; delete it if your host serves .br.

--zip writes a zip with index.html at its top level and no .br files (the jam rule: index.html at the zip's top).
Exit 1 when a check fails (the zip is still written so you can look at it).
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

NAV_FN = re.compile(r"function isolated\(response, request\)\s*\{(.*?)\n\}", re.S)
CORP = re.compile(r"h\.set\('Cross-Origin-Resource-Policy',\s*'([a-z-]+)'\);?")


def check_sw(stage: Path, patch: bool) -> tuple[bool, str]:
    sw = stage / "sw.js"
    if not sw.exists():
        return True, "no sw.js (bInjectIsolationHeaders off?): the host must send COOP / COEP itself; itch.io does when 'SharedArrayBuffer support' is ticked"
    text = sw.read_text()
    m = NAV_FN.search(text)
    if not m:
        return False, "sw.js: function isolated(response, request) not found; check the navigation response's CORP header by hand"
    body = m.group(1)
    c = CORP.search(body)
    if not c:
        return False, "sw.js isolated(): no Cross-Origin-Resource-Policy header found; check by hand"
    if c.group(1) == "cross-origin":
        return True, "sw.js: navigation response CORP = cross-origin (embeddable by itch.io)"
    if not patch:
        return False, f"sw.js: navigation response CORP = {c.group(1)}: the game will not load inside itch.io's iframe. Re-run with --patch-sw"
    new_body = body[:c.start()] + "h.set('Cross-Origin-Resource-Policy', 'cross-origin');  // embeddable by a cross-origin parent (itch.io)" + body[c.end():]
    sw.write_text(text[:m.start(1)] + new_body + text[m.end(1):])
    return True, f"sw.js: navigation response CORP {c.group(1)} -> cross-origin (patched; sw.js.br is now stale)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage")
    ap.add_argument("--patch-sw", action="store_true")
    ap.add_argument("--zip", default="")
    ap.add_argument("--max-total-mb", type=float, default=500)
    ap.add_argument("--max-file-mb", type=float, default=200)
    a = ap.parse_args()
    stage = Path(a.stage)
    ok = True
    if not (stage / "index.html").exists():
        print("FAIL no index.html at the top of the stage")
        ok = False
    files = sorted((p for p in stage.rglob("*") if p.is_file() and p.suffix != ".br" and p.name != ".DS_Store"), key=lambda p: -p.stat().st_size)
    total = sum(p.stat().st_size for p in files) / 1e6
    biggest = files[0] if files else None
    print(f"{len(files)} files, {total:.1f} MB without .br")
    for p in files[:5]:
        print(f"  {p.stat().st_size / 1e6:8.1f} MB  {p.relative_to(stage)}")
    if total > a.max_total_mb:
        print(f"FAIL total {total:.1f} MB > {a.max_total_mb} MB")
        ok = False
    if biggest and biggest.stat().st_size / 1e6 > a.max_file_mb:
        print(f"FAIL {biggest.name} {biggest.stat().st_size / 1e6:.1f} MB > {a.max_file_mb} MB per file")
        ok = False
    sw_ok, msg = check_sw(stage, a.patch_sw)
    print(("OK   " if sw_ok else "FAIL ") + msg)
    ok = ok and sw_ok
    if a.zip:
        zp = Path(a.zip)
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(files):
                z.write(p, p.relative_to(stage).as_posix())
        print(f"wrote {zp} ({zp.stat().st_size / 1e6:.1f} MB, index.html at the top, no .br)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
