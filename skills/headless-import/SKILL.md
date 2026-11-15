---
name: headless-import
description: Import PNG textures, GLB models and WAV sounds into an Unreal Engine 5.9 project and build materials node by node, without opening the editor, by running editor Python in a commandlet. Use when new art or audio has to get into an Unreal project, or a material has to be created or changed, and nobody should click in the editor.
---

# Import assets and build materials headlessly

Library: `UD/scripts/import/ue_import.py`. Driver: `UD/scripts/import/import_manifest.py` with a JSON manifest
(example: `UD/scripts/import/assets.example.json`). Background and pitfalls: `UD/guides/headless-import.md`.

## Steps

1. **Write or update the manifest** in the game repo (not in UD): maps, materials, textures, models, sounds. Relative
   file paths are relative to the manifest. Keep one manifest per asset family if re-imports should stay small.
   - UI pictures: `"ui": true, "compression": "TC_EDITOR_ICON"` (no mips, uncompressed: compression frays line art).
   - Textures projected by world position: `"never_stream": true` (and `"lod_bias": -1` for grazing views).
   - Props seen from afar: `"max_tex": 512` on the model.
2. **Materials need to exist before models** that use them as parent (the driver runs materials first). For a
   material the manifest cannot express, write a small editor-Python script in the game repo that does
   `sys.path.insert(0, "<UD>/scripts/import"); from ue_import import G, MP` and builds the graph; run it the same way.
3. **Run** (absolute paths only; the editor must not be open on the same project):
   ```bash
   UD_MANIFEST=/abs/assets.json [UD_IMPORT_ONLY=materials,textures] \
   "$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" /abs/Game.uproject \
     -run=pythonscript -script=/abs/UD/scripts/import/import_manifest.py -unattended -nopause -nosplash -nullrhi
   ```
4. **Verify from the log**, not the exit code: every expected `UD_IMPORT texture|model|sound|material ...` line is
   there, and there is no `UD_IMPORT FAILED` / `missing`. Model lines print bounding boxes: check the orientation
   (glTF +Z forward becomes UE +Y; the game may need yaw -90) and the scale (x100).
5. **Look at it**: run the game's lineup / autoplay shot that shows the new asset (native `-game` shows freshly imported
   textures blank for a few frames; judge on a cooked build when in doubt).
6. Commit the generated `.uasset` files (Git LFS) together with the manifest and the source files.
