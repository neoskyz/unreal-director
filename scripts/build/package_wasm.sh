#!/usr/bin/env bash
# Wasm (WebGPU) Shipping package of a UE 5.9 C++ project, from the command line. No editor UI.
#
#   export UE=/path/to/UnrealEngine            # built from source (the Wasm platform is not in the launcher build)
#   export WASM_EMSDK_ROOT=/path/to/emsdk      # emscripten exactly as Engine/Platforms/Wasm/Config/Wasm_SDK.json says (6.0.10 for 5.9)
#   scripts/build/package_wasm.sh /abs/MyGame.uproject /Game/MyGame/Maps/Main /abs/Builds/MyGame_Wasm_Shipping
#
# Env: MAX_PAR (default 6): parallel compile actions. 24 GB RAM with other work running swaps hard at 8.
#      CONFIG (default Shipping).
# Takes ~40 min the first time (engine modules for Wasm), ~13 min after. The staged game is <out>/Wasm (index.html at
# its top). Before uploading: scripts/build/prepare_web_upload.py <out>/Wasm.
# Do not edit Source/ during the first ~10 minutes (compile phase), and do not rebuild the editor while it cooks
# (the cook runs the editor binaries). UBT has a global lock: an editor build and this build cannot run at once.
set -euo pipefail
if [[ $# -lt 3 ]]; then
  sed -n '2,13p' "$0"
  exit 2
fi
PROJECT="$1"
MAP="$2"
OUT="$3"
: "${UE:?set UE to the engine root}"
: "${WASM_EMSDK_ROOT:?set WASM_EMSDK_ROOT to your emsdk folder}"
unset EMSDK  # an emsdk activated in the shell overrides WASM_EMSDK_ROOT with the wrong version
MAX_PAR="${MAX_PAR:-6}"
CONFIG="${CONFIG:-Shipping}"

"$UE/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun \
  -project="$PROJECT" -platform=Wasm -clientconfig="$CONFIG" \
  -build -cook -stage -pak -iostore -package -archive -archivedirectory="$OUT" \
  -map="$MAP" \
  -unattended -utf8output -nocompileeditor \
  -UbtArgs="-MaxParallelActions=$MAX_PAR" \
  -AdditionalCookerOptions="-unattended -nopause -nosplash -nullrhi"

echo "staged: $OUT/Wasm"
du -sh "$OUT/Wasm"
