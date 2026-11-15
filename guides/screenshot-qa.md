# Screenshot QA: how an agent signs off a build

The test passing means the game reached the end. It does not mean the game looks right. On Starseal the bugs the
player saw (a black damage number, particles floating in empty space, a texture gone blurry, a prop standing on the
path, the hero missing for one frame) all passed the autoplay. Looking found them.

## The routine

1. **Run the play-through on the packaged Wasm build** (`autoplay_web.py`), not only native. Cooked and uncooked builds
   differ (texture streaming, text rendering, shader tiers).
2. **Contact sheet first** (`scripts/qc/contact_sheet.py out.png runs/web/*.png`): which pictures need a closer look.
3. **Then every picture that matters at full size, one by one.** Small tiles hide exactly the defects above. Read
   every word on screen. Check the edges of the screen: stray light blobs there were a symptom of a coordinate bug.
4. **Continuous action at normal speed, in bursts** (`--speed 1 --after "<event>=0.3,0.6,0.9"`). One picture per
   action proves nothing about the frames between.
5. **Coverage modes for "anywhere" questions.** A play-through visits a few places. Starseal added a path patrol (a
   picture every 3.5 m along every path, both ways) and a layout check (every card and button with its longest text).
6. **Motion questions with the other motion turned off.** To prove "this creature sways, that one does not", fix the
   camera (`?sgstillcam`), take pictures 0.4 s apart and diff them. With a drifting camera everything differs.
7. **Recordings frame by frame** for one-frame glitches: `presence_check.py` on the frames, `qc_cadence.py` on the MP4.
8. Fix, rebuild, re-run the same pictures, compare before / after side by side. Only then show the build to a human.

## Lessons that became rules

- **When one effect is in the wrong place, check whether all of them are.** Particles were attached to a rotating
  planet but their local positions were submitted as world positions; every effect was off by however far the planet
  had turned. It was "fixed" three times per effect before the root cause was found.
- **Keep old comparison pictures** when making new ones (copy them aside with a timestamp). Decisions were made from
  them, and the history is the evidence.
- **The agent does the technical checks itself.** The human's time goes to taste: "is this fun, does this look good",
  not "is the texture loaded".
