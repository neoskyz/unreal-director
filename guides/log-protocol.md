# The log protocol: how an agent sees the game

An agent cannot watch the screen while the game runs. It reads two things: **log lines** and **screenshots**. So the
game prints one-line facts with fixed prefixes, the same way on every platform, and every test script is a parser of
those lines. Starseal used the prefix `SG_`; every script takes `--prefix` if you pick another.

Print through one function that writes to stdout (native, flushed) and to the browser console (Wasm), in Shipping too
(`reference/cpp/AutoplaySwitches.cpp`, `SG::Log`).

| Line | Meaning | Who reads it |
|---|---|---|
| `SG_STATE <Name> [detail] t=<s>` | the game state machine entered a state | all tests (`--require`) |
| `SG_SHOT <name>` | "take a picture now, call it `<name>`" (native writes it itself to `-SGShotDir`) | `autoplay_web.py` screenshots the page |
| `SG_FPS <State> avg=.. worst=.. frames=..` | frame-rate summary of the state that just ended | regression reports |
| `SG_EVT <text>` | gameplay events (battle log); noisy, not echoed | `--after` triggers, debugging |
| `SG_WARN <text>` | something is missing (a sound, a texture). Fails the run | all tests |
| `SG_FAIL <why>` | the bot is stuck / timed out. Fails the run | all tests |
| `SG_DONE <summary>` | the run is complete. Anything the scripts need must be printed **before** it | all tests |
| `SG_POS x y z yaw pitch` | position / camera, twice a second with `?sgtrace` | input tests (did W move us? did the mouse turn us?) |
| `SG_RECORD init/start/done` | recording mode progress | `record_native.py` |
| `UE_RUN READY` / `UE_RUN ERROR` | printed by the engine's Wasm page, not by the game | web tests |

Rules that paid off:

- **Every user-visible reaction gets a line.** Opening a menu (`SG_HELP 1`), closing a dialog (`SG_NOTICE closed`),
  fitting a part (`SG_FITTED step=2`). Then an input test can click and assert, instead of comparing pixels.
- **Missing assets are loud.** A lookup that returns null should print `SG_WARN missing <name>`, or a sound that never
  plays stays unnoticed for days (it happened: a looping sound had the wrong name and was silent from day one).
- **A watchdog in the bot.** No state change and no event for N seconds: picture `stuck`, `SG_FAIL stuck`, exit 3.
  Without it a stuck bot looks like a slow one until the script's timeout.
- **Don't wait for EOF on a UE child process.** UnrealTraceServer can inherit the stdout pipe and keep it open after
  the game exits. Stop reading at `SG_DONE` / `SG_FAIL`, or write stdout to a file and poll the process.
- On Mac native runs the game log is in `~/Library/Logs/<Project>/<Project>.log`, not `Saved/Logs`.
