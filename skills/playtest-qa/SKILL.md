---
name: playtest-qa
description: Play an Unreal game automatically (native off-screen or the Wasm build in headless Chromium), collect named screenshots and log lines, and sign it off by looking at every important picture at full size, without ever touching the user's mouse or screen. Use after any gameplay, visual or UI change, before showing a build to a human, or when asked to playtest, verify or check a build.
---

# Playtest and screenshot QA

The user is working on this machine. Never use `--headed`, never launch the game without the native scripts (they add
`-RenderOffscreen -SGNoMouse` and the mouse guard), never open windows or play sound. Background:
`UD/guides/playtesting.md`, `UD/guides/screenshot-qa.md`.

## Steps

1. **Pick the build.**
   - Quick iteration: native, uncooked:
     `UE=... UPROJECT=... python3 UD/scripts/native/autoplay_native.py --speed 2 --shots runs/native --require <states>`
     (`--until <shot>` stops at one picture; `--extra "-SGQuick"` style switches jump ahead if the game has them).
     The last line must show `MOUSE_GUARD ... grabbed=False`; exit 2 means the game grabbed the mouse: stop and fix that first.
   - Verdicts: the packaged Wasm build: `python3 UD/scripts/web/autoplay_web.py --stage <Wasm> --out runs/web --require <states>`
2. **Read `result.json`**: pass, missing states, `SG_FAIL` / `SG_WARN`, page errors, fps per state (flag any state
   averaging under ~50 fps or with very bad worst frames).
3. **Contact sheet**: `python3 UD/scripts/qc/contact_sheet.py runs/web/sheet.png runs/web/*.png`, to choose what to open.
4. **Open every picture that shows the change, at full size**, and read every word. Look for: dark or black text, wrong
   or missing pictures, blur, things in the wrong place (also at the screen edges), overlap, clipped text.
5. **Continuous action** (effects, animation): re-run at `--speed 1` with `--after "<log prefix>=0.3,0.6,0.9"` and look
   at the bursts. For "does X move": fixed camera switch + pictures 0.4 s apart + a pixel diff.
6. **Video / one-frame glitches** (when relevant): `record_native.py --segment <name> --keep-frames`, then
   `UD/scripts/qc/presence_check.py <frames> --box ...` and `UD/scripts/qc/qc_cadence.py <mp4>`.
7. If a defect appears in one effect, check whether every similar effect has it before fixing one.
8. Fix, re-run the same pictures, compare before / after. Keep the old pictures (copy aside with a timestamp).

## Report

Pass / fail per run with the `result.json` paths, the defects found (picture path + what is wrong), what was fixed and
re-verified, and only the questions of taste for the human.
