# Gotchas: UE 5.9, Wasm / WebGPU, and agent-driven development

Found while building Starseal (4 days, UE 5.9 built from source, Mac, Wasm Shipping). Each one cost real time.

## Web build

- **Inside itch.io's iframe, the service worker's page response needs CORP `cross-origin`**, not the engine template's
  `same-origin`. Details: [itch-deploy.md](itch-deploy.md).
- **itch.io needs "SharedArrayBuffer support" ticked**; the service-worker isolation trick does not cover iframes.
- **Text does not fade by alpha in the browser.** `FSlateDrawElement::MakeText` with alpha < 1 draws the text darker,
  not more transparent, on Wasm (images and boxes fade correctly). Damage numbers turned black before vanishing. Fade
  text by shrinking it in a few steps instead (few steps keep the font cache small). Not checked for `STextBlock`.
- **`FSlateDrawElement::MakeCustomVerts` works on WebGPU** (a picture drawn on a bending mesh: a swimming whale).
- **Keys pressed on the page cover leak into the game** once it starts. Do not bind a game action to Enter / Space on
  the first screen.
- Headless Chromium for tests: `channel="chromium"` + `--headless=new` (real GPU); the default headless shell only has
  SwiftShader and loses the WebGPU device.
- `serve.py` / `http.server` can hang ~35 s at start on a Mac (`socket.getfqdn()`).

## Rendering and Slate

- **Instanced meshes: local vs world.** `BatchUpdateInstancesTransforms(..., bWorldSpace=true)` with positions stored
  in the component's local space put every particle in the wrong place once the parent moved. Use `bWorldSpace=false`
  for local positions.
- **Slate tint cannot brighten.** `ColorAndOpacity` / brush tint above 1 is clamped (8-bit vertex colour). Highlight
  by drawing another layer (an outline), not by tinting up.
- **`OnPaint` drawing is always above child widgets**: skip it explicitly while a dialog is open.
- **Composite fonts:** `FSlateFontInfo::FontObject` is null with an `FCompositeFont`; rebuilding font info from it falls
  back to boxes. Copy the whole `FSlateFontInfo` and change only `OutlineSettings`.
- Auto-wrapped text in an auto-sized container wraps unpredictably; give it `WrapTextAt` a fixed width.
- `FString::Printf` needs a literal format string (a ternary choosing the format does not compile): call it twice.
- In `-game`, `UTexture2D::GetSizeX/Y` can return a placeholder size while the texture compiles (a logo came out
  square); use `GetImportedSize()` for aspect ratios.
- Only one directional light is used by forward shading; a second one prints yellow warnings on screen. Give the main
  one `SetForwardShadingPriority(1)`.
- `SetMaterial(0, NewMaterial)` drops the old dynamic instance: parameter sets afterwards silently do nothing until you
  create a new `UMaterialInstanceDynamic`. Do not wrap an existing MID in another MID either (the parameters stop working).
- Components set to absolute rotation: any `SetRelativeRotation` changes their world rotation. Loops that rotate
  "every component of an actor" will flatten billboards.
- A material that samples by world position slides when the object moves (a planet turning under the player).
  Sample in local space.
- Camera FOV in UE is horizontal: FOV 46 at 16:9 is only ~27 degrees vertically.
- Exponential height fog is computed on world Z: seen from space it darkens the lower half of a planet. Turn it off
  for space shots.
- Two points joined by a glowing cylinder read as a long line across the screen from an oblique camera.
- Anything that swaps textures on screen (walk cycles on painted sprites) should load and keep them resident before
  first use; a texture bound on the frame it is needed can draw as empty for that frame.

## Audio

- With `-nosound`, `CreateSound2D` returns null. Track whether a loop is "on" with a flag, not with the component
  pointer, or it restarts every frame.
- A sound looked up by a wrong name returns null silently. Log `SG_WARN missing` for every lookup, loops included.

## Engine tooling

- UBT's global lock: editor and Wasm targets cannot compile at the same time; queue them.
- `-SGShotDir` style paths passed to the game must be absolute (relative = relative to the engine binary).
- UnrealTraceServer inherits the stdout pipe of the game it was started by: never wait for EOF on a UE child process.
- `UnrealPak -List=` needs `<uproject> IoStore -List=<abs .utoc>` for IoStore containers.
- `DirectoriesToNeverCook` works per folder only. To drop one asset, move it into such a folder (if nothing references it).

## Video (trailers made from recordings and AI clips)

- ffmpeg `image2` input + filters can silently drop to 25 fps output: always pass `-r <fps>` on the output.
- AI image-to-video clips can have uneven frame timing (duplicated frames and double steps) that no fixed-pattern
  frame drop fixes. Measure with `qc_cadence.py`; retime by motion, or regenerate.

## Gameplay logic on a sphere

- On a small round planet, `FVector::Dist2D` is wrong: things on the far side project close to the origin and
  triggered battles from the back of the planet. Use 3D distance.
- After a lost battle the player must land outside the trigger radius, or "walk away first, then retry" rules can
  leave the player (and the bot) stuck forever.
