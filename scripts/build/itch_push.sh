#!/usr/bin/env bash
# Upload a staged UE Wasm build to an EXISTING itch.io page with butler (itch has no API to create a page).
#
#   export ITCH_TARGET=<your-itch-user>/<game-slug>:html5     # e.g. a page you created by hand
#   scripts/build/itch_push.sh Builds/MyGame_Wasm_Shipping/Wasm
#
# One-time, by hand on itch.io (an agent cannot do these): create the project, Kind of project = HTML, tick
# Embed options > "SharedArrayBuffer support" (UE Wasm needs a cross-origin isolated page; without it the game stops at
# "not cross-origin isolated"), keep it Draft while testing. After the first push, mark the upload "This file will be
# played in the browser". butler needs `butler login` once (or BUTLER_API_KEY in the environment).
# Run scripts/build/prepare_web_upload.py --patch-sw first: inside itch's iframe the service worker's page response
# needs CORP cross-origin (guides/itch-deploy.md).
set -euo pipefail
STAGE="${1:?usage: itch_push.sh <staged Wasm folder>}"
: "${ITCH_TARGET:?set ITCH_TARGET=<user>/<game>:<channel>}"
BUTLER="${BUTLER:-butler}"
"$BUTLER" push "$STAGE" "$ITCH_TARGET" --ignore '*.br' --ignore '.DS_Store'
"$BUTLER" status "${ITCH_TARGET%%:*}"
