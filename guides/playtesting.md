# Automated playtesting: web and native, without touching your machine

The agent cannot play the game by hand, and you are using the same computer while it tests. Two rules follow:
the game must play itself (an autoplay bot behind a switch, see `reference/`), and no test may take your mouse,
keyboard focus or screen.

## Web (the packaged build, what players get)

| Script | Answers |
|---|---|
| `scripts/web/autoplay_web.py` | Does the Shipping build play start to end? Pictures of every named moment, fps per state, page errors |
| `scripts/web/input_steps_web.py` | Do real clicks and keys do what they should? (JSON list of steps, each waits for its log line) |
| `scripts/web/isolation_test_web.py` | Does it start on a host that sends no COOP / COEP headers? |
| `scripts/web/cover_test_web.py` | The real first-time flow: cover, click, game starts |
| `scripts/web/gpu_message_test_web.py` | No GPU: does the player get a clear message, before a 100 MB download? |

How they run Chromium (all in `scripts/web/webcommon.py`):

- **`channel="chromium"` + `--headless=new`.** Playwright's default headless mode is the "headless shell" with only
  SwiftShader: its WebGPU limits are below UE's mobile tier, and the device is lost at the first screenshot. The full
  browser in new headless mode gets the real GPU adapter (Metal on a Mac). Starseal ran at 60 fps headless.
- **Headless by default, always.** Headless cannot reach the system mouse or focus. `--headed` parks a real window
  off-screen, but it can still take pointer lock and keyboard focus: only when nobody is using the machine.
- **`?harness=1`** (the engine page's own switch) hides the cover and skips click-to-start, so screenshots show the
  game. Behind the cover the engine already runs. `--cover` keeps the real player flow.
- The first `page.screenshot` in new headless mode can take ~1 minute; later ones are fast.
- Console lines arrive only while Playwright runs: wait with `page.wait_for_timeout`, not `time.sleep`.
- The game prints `SG_SHOT <name>`; the script takes the page screenshot. For continuous action use
  `--speed 1 --after "SG_ACT 2=0.3,0.6,0.9"`: pictures at fixed delays after an event. One picture per action proved
  nothing on Starseal: particles drawn in the wrong place only showed up in such bursts.

## Native (uncooked `-game`, faster to iterate)

`scripts/native/autoplay_native.py` and `record_native.py` launch `UnrealEditor <uproject> -game -RenderOffscreen`
with the game's no-mouse switch, and run **`mouse_guard.py`** alongside:

- It samples the system cursor 5 times a second (CoreGraphics, no permissions). A cursor sitting on the exact centre
  of a display for 3 samples is a program pinning it there: the guard kills the game and the run fails (exit 2).
- It also records whether the game became the frontmost app (focus stolen). Reported, not fatal.
- The end of every run prints evidence, e.g. `MOUSE_GUARD samples=367 centre_hits=0 grabbed=False ... front_app_hits=0/37`.

Why both a guard and game code: an off-screen game with "capture mouse on launch" and a game-only input mode warped
the user's cursor to the screen centre every frame (macOS high-precision mouse mode). `-RenderOffscreen` hides the
window but not the capture. The game now turns capture off in unattended runs (`reference/cpp/NoMouse.cpp`), and the
guard catches any regression. Keep native test windows at or below the screen size (a 1920x1080 window on a smaller
screen was seen becoming the front app).

Other native lessons:

- `-SGShotDir` must be absolute: a relative path resolves against the engine binary's folder.
- A busy machine makes a full native play-through take 10+ minutes; give timeouts room.
- Uncooked runs show freshly imported textures blank for a few frames. Visual verdicts come from the Wasm build.

## Recording video without screen capture

`record_native.py` runs the game's recording mode: fixed time step (exactly one frame per screenshot, however slow
the PNG write), one PNG per frame, every sound logged as a JSON line. `scripts/qc/make_video.py` re-mixes the audio
offline from those events and muxes an MP4 (and `cut` assembles a rough cut with crossfades and -16 LUFS). The game
runs with `-nosound`. Starseal's trailer was cut from such segments, without the HUD (`-SGNoHud`).

Then check the result: `scripts/qc/qc_cadence.py` (frozen / uneven / skipped frames), and
`scripts/qc/presence_check.py` when something might vanish for a frame.
