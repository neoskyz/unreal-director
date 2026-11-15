# Packaging UE 5.9 for the web (Wasm + WebGPU) from the command line

Tested on a Mac (Apple Silicon, 24 GB) with UE 5.9 built from source. Script: `scripts/build/package_wasm.sh`.

## One-time setup

- **Engine from source.** The Wasm platform lives in `Engine/Platforms/Wasm/` (its own `Docs/` and an agent skill in
  `Skills/web-deploy/SKILL.md` are worth reading). Shallow clone of the `5.9` branch, `Setup.sh` (~32 GB of
  dependencies), `GenerateProjectFiles.sh`, then build the editor:
  `Build.sh <Project>Editor Mac Development -Project=<uproject> -MaxParallelActions=6` (hours the first time).
  The engine folder ends up ~190 GB; `.git/ue-gitdeps` (~31 GB download cache) can be deleted afterwards.
- **emscripten exactly as `Engine/Platforms/Wasm/Config/Wasm_SDK.json` says** (6.0.10 for 5.9). Install emsdk anywhere,
  `export WASM_EMSDK_ROOT=<emsdk>` and `unset EMSDK` (an activated emsdk in the shell wins otherwise).
- **C++ project.** Create it from a template with the engine's `new_template_project.py --web-ready` rather than
  copying template folders by hand (shared content goes missing, Blueprint parents break). `--web-ready` adds
  `PlatformDenyList: ["Wasm"]` to plugins that do not build for Wasm.
- **Mac native runs need the Metal toolchain**: `xcodebuild -downloadComponent MetalToolchain` (Xcode 27 does not ship
  it). The Wasm package does not need it (WGSL goes through Tint).
- Keep Spotlight out of the engine folder (`touch <engine>/.metadata_never_index`).

## The command

```bash
export UE=/path/to/UnrealEngine WASM_EMSDK_ROOT=/path/to/emsdk
scripts/build/package_wasm.sh /abs/MyGame.uproject /Game/MyGame/Maps/Main /abs/Builds/MyGame_Wasm_Shipping
```

It is `RunUAT.sh BuildCookRun -platform=Wasm -clientconfig=Shipping -build -cook -stage -pak -iostore -package -archive
-nocompileeditor -UbtArgs="-MaxParallelActions=6" -AdditionalCookerOptions="-unattended -nopause -nosplash -nullrhi"`.

- **`-MaxParallelActions=6` on 24 GB.** With 8 and other work running, swap reached 23 GB and compiling crawled at
  ~4 actions/min; with 6 it ran at 18-35 actions/min.
- First package ~40 min (729 compile actions, ~10 min link), later ones ~13 min.
- UBT has a global lock: the editor target and the Wasm target cannot compile at the same time. Do not edit `Source/`
  during the compile phase (it gets half-compiled in) and do not rebuild the editor during the cook (the cook runs the
  editor binaries).
- The 5.9 branch turns the AI / MCP toolsets on by default; the Wasm docs say the AI toolset plugins can crash the Wasm
  cook. Starseal turned `AllToolsets` / `AIAssistant` off in the `.uproject`. (Not tested with them on.)

## What comes out

`<out>/Wasm/` with `index.html` at its top, `sw.js`, the loader scripts, `<Project>-Wasm-Shipping.wasm` (~133-140 MB
for a small C++ game: that is the engine) and the IoStore container. Every file also has a `.br` twin.

- **The `.br` files are optional.** They are pre-compressed copies for hosts that serve them through `_headers`
  (Cloudflare Pages style). The loader never asks for them; itch.io gzips html / js / wasm itself. Leave them out of
  uploads: Starseal went from ~227 MB to under 200 MB.
- **Size:** a jam limit of 500 MB total / 200 MB per file was easy; the .wasm is the biggest single file. To see what
  is in the container: `scripts/qc/pkg_size.py` (needs `UnrealPak <uproject> IoStore -List=<abs .utoc> -csv=<abs>`;
  plain `UnrealPak -List=` does not work on IoStore). Cook can only exclude whole folders (`DirectoriesToNeverCook`).
- **Rendering tiers:** both web tiers are mobile renderers (forward / mobile deferred) on WebGPU. Starseal ran at
  the 60 fps vsync cap in Chrome on an M-series Mac, READY in ~3-5 s from a local server.
- **Isolation:** with `bInjectIsolationHeaders=True` the page works on hosts that send no COOP / COEP headers (the
  service worker adds them and reloads once): test with `scripts/web/isolation_test_web.py`. For itch.io see
  [itch-deploy.md](itch-deploy.md).
- The Shipping page drops `?args=`; to see frame times use a Development package or the page's `?debug=1` overlay.

## Serving it locally

`python3 $UE/Engine/Platforms/Wasm/Build/Tools/web/serve.py --root <out>/Wasm --port 8800`, then
`http://127.0.0.1:8800/index.html`. On some Macs `serve.py` (and Python's `http.server`) take ~35 s to start because
`socket.getfqdn()` hangs; the test scripts wait for it or bind without it (`scripts/web/webcommon.py`).
