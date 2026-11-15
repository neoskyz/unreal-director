---
name: wasm-package-and-test
description: Package a UE 5.9 C++ project as a Wasm (WebGPU) Shipping build from the command line, run the browser test suite on it headlessly, check size and the itch.io service-worker header, and optionally push it to itch.io with butler. Use when the user asks to build, package, ship, upload or test the web version of an Unreal game.
---

# Package the web build and test it

Paths below are relative to the unreal-director checkout (`UD`). The game project must print the log lines in
`UD/guides/log-protocol.md` and understand the autoplay switches in `UD/reference/README.md`.

## Inputs to confirm (ask once if unknown, then reuse)

- `UE` (engine built from source), `WASM_EMSDK_ROOT` (emsdk with the exact emscripten version the engine's
  `Engine/Platforms/Wasm/Config/Wasm_SDK.json` names), the `.uproject`, the startup map path, an output folder.
- The states a full play-through must reach (for `--require`), e.g. `Title,Explore,Battle,Ending`.
- For upload: `ITCH_TARGET=<user>/<game>:html5`, and whether the human has created the itch page with
  "SharedArrayBuffer support" ticked (you cannot do that part).

## Steps

1. **Package** (~40 min first time, ~13 min later). Run in the foreground with a long timeout, or in the background
   and wait for it to exit; do not poll and do not edit `Source/` or rebuild the editor while it runs.
   `MAX_PAR=6 UD/scripts/build/package_wasm.sh <uproject> <map> <out>`
   On failure read the end of the UAT log; common causes are in `UD/guides/packaging-wasm.md`.
2. **Check the stage** and fix the itch header:
   `python3 UD/scripts/build/prepare_web_upload.py <out>/Wasm --patch-sw [--zip <dist>/<Game>_web.zip]`
3. **Play-through** (headless, never `--headed` while the user works on the machine):
   `python3 UD/scripts/web/autoplay_web.py --stage <out>/Wasm --out runs/web --speed 2 --require <states>`
4. **Plain-host start**: `python3 UD/scripts/web/isolation_test_web.py --stage <out>/Wasm`
5. **Real input** if the project has a steps file: `python3 UD/scripts/web/input_steps_web.py --stage <out>/Wasm --steps <file>`
6. **Look at the pictures** (the playtest-qa skill): contact sheet, then the important ones at full size.
7. **Upload** only when asked: `ITCH_TARGET=... UD/scripts/build/itch_push.sh <out>/Wasm`. Then ask the human to
   open the Draft page once (first push: mark the upload "played in the browser").

## Report

Package time, stage size without `.br` and the biggest file, the sw.js CORP status, each test's pass / fail with
its `result.json` path, fps per state, page errors, and the pictures that need a human's eye.
