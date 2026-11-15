# Importing assets and building materials without the editor UI

Everything in Starseal's `Content/` was created by scripts: an empty map, ~20 materials, textures, GLB models, WAV
sounds. The game spawns the world from C++ at runtime, so the binary assets are few and all reproducible.

## How to run editor Python headlessly

```bash
UD_MANIFEST=/abs/assets.json \
$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor /abs/MyGame.uproject \
  -run=pythonscript -script=/abs/scripts/import/import_manifest.py -unattended -nopause -nosplash -nullrhi
```

- `-script=` needs an **absolute** path. Pass arguments through environment variables.
- Do not trust the exit code alone (a failed import is just a log line): grep the output for `UD_IMPORT FAILED` / `UD_IMPORT missing`.
- The project needs the Python Editor Script Plugin (`PythonScriptPlugin`) enabled.
- Starseal's full import (textures, materials, models, audio) took ~2.5 minutes. Split it into steps
  (`UD_IMPORT_ONLY=materials,textures`) so a material change does not re-import models (smaller Git LFS churn too).

`scripts/import/ue_import.py` is the helper library (`import_texture`, `import_sound`, `import_glb_model`, the `G`
material-graph builder, `model_material`, `flat_material`, `empty_map`); `import_manifest.py` drives it from a JSON file
(`assets.example.json`). For anything the manifest cannot express, write a script that imports `ue_import` and builds
the graph with `G` (`g.tex`, `g.mul`, `g.lerp`, `g.out(..., MP.MP_EMISSIVE_COLOR)`).

## Things that are not obvious

- **`-nullrhi` cannot compile materials.** `MaterialEditingLibrary.recompile_material` raises; skip it. Shaders compile
  when the game or the cook first loads the material (first native `-game` start: ~5-12 min of Metal shaders).
- **Engine assets in a commandlet:** `EditorAssetLibrary.load_asset("/Engine/...")` returns nothing (the asset registry
  has not scanned engine content). Use `unreal.load_asset`.
- **Rebuild materials in place.** Delete the expressions of the existing material and rebuild them, rather than
  deleting the asset: every material instance parented to it keeps working, so models need no re-import.
- **GLB through Interchange:** glTF (x, y, z) becomes UE (x, z, y) x 100. A model facing glTF +Z faces UE +Y, so it needs
  yaw -90 to face +X. Pivots are kept. Each GLB lands in `<dest>/<name>/{StaticMeshes,Textures,Materials}`; texture
  names differ between generators (diffuse / baseColor / albedo), so match by substring.
- **Masked materials clip at 0.3333 by default.** A dissolve mask built as `noise - Dissolve` removed ~30% of every
  model at Dissolve = 0 (holes, floating fins). Make "parameter 0" keep every pixel (`+0.345`).
- **AI-generated meshes have single-layer fins:** two-sided materials, or back-face culling turns them into holes.
  Weld (`remove_doubles`) **before** decimating, or the decimation tears open the UV seams.
- **Textures sampled by world position** (a circle projected on the ground) cannot be streamed well: the streamer
  estimates the needed mip from mesh UVs and leaves them blurry. Set `never_stream`, and `lod_bias -1` at grazing angles.
- **UI textures:** UI group, no mips, `TC_EDITOR_ICON` (uncompressed). Block compression frays line art. It is the
  biggest part of the download for a 2D-heavy game, on purpose.
- **Transparent PNG edges go dark** after scaling / filtering / mips when the transparent pixels are black (the
  material is not premultiplied). Bleed the nearest opaque colour into the transparent area before import.
- **Things that move must not sample textures in world space** (they slide). Transform to local space in the material
  (`to_local_pos` in `ue_import.py`).
- In `-game` (uncooked), freshly re-imported textures show as blank for a few frames while they compile ("Preparing
  Textures"). Judge visuals on the cooked Wasm build.
