# reference/

C++ excerpts from **Starseal**'s game module, kept as reference. They are not a library and will not compile as-is:
they are slices of one game's code, with the `SG` prefix it used. Copy the ideas (and the code) into your own module.

The scripts in `scripts/` talk to a game through two channels only, so this is what your game needs to provide:

1. **Switches** that work both as a command-line flag (native runs) and as a URL query parameter (the packaged Wasm
   build in a browser). See `cpp/AutoplaySwitches.cpp` (`UrlOrCmd`).
2. **Log lines** with fixed prefixes printed to stdout and the browser console, also in Shipping builds
   (`SG::Log`). The format is in [guides/log-protocol.md](../guides/log-protocol.md).

| Switch (native / Wasm URL) | What it did in Starseal | Used by |
|---|---|---|
| `-SGAutoPlay` / `?sgautoplay` | a bot plays the whole game, printing `SG_STATE`, `SG_SHOT`, `SG_DONE` | `autoplay_native.py`, `autoplay_web.py` |
| `-SGAutoPlayExit` | quit after the ending (native) | `autoplay_native.py` |
| `-SGSpeed=2` / `?sgspeed=2` | bot and battle animations run 2x | both autoplay scripts |
| `-SGShotDir=<abs>` | where native screenshots go (absolute path!) | `autoplay_native.py` |
| `-SGNoMouse`, `-RenderOffscreen` | never capture / hide / move the system cursor | all native scripts |
| `-SGRecord=<abs> -SGSegment=<name>` | fixed-step frame recording + audio event log | `record_native.py` |
| `-SGNoHud` / `?sgnohud` | no HUD (trailer recording) | `record_native.py --extra` |
| `-SGPatrol` / `?sgpatrol` | walk every path, picture every 3.5 m, report props on paths | `autoplay_web.py --extra "&sgpatrol=1"` |
| `-SGLayout` / `?sglayout` | show every UI card / button with its longest text, one picture each | `autoplay_web.py --extra "&sglayout=1"` |
| `-SGFrameLog` | per-frame diagnostics to hunt one-frame glitches | `record_native.py --extra` |
| `?sgtrace`, `?sgbattle` | position / yaw lines; start a battle early | `input_steps_web.py` |
| `?sgstillcam` | camera does not drift, so pixel diffs show what really moves | screenshot checks |
| `?sgfakelowfps` | the frame-rate guard sees 30 fps (tests dynamic resolution) | input test |
| `-SGPkgDump` / `?sgpkgdump` | list every package the run loaded (`SG_PKG`) | package-size work |

Files:

- `cpp/AutoplaySwitches.cpp`: `Log`, `UrlOrCmd`, `IsAutoPlay`, `NoMouse`, `Speed`, `Shot`, and the debug switches.
- `cpp/NoMouse.cpp`: what "never touch the mouse" turns off, at module startup and in the input-mode code.
- `cpp/AutoplayLoop.cpp`: `SG_STATE` / `SG_FPS` on state change, named screenshots, check modes, the stuck watchdog.
- `cpp/RecordMode.cpp`: the recording mode (fixed time step, one PNG per frame, audio events as JSON lines).
