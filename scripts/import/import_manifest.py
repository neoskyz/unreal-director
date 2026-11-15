"""Editor Python: import everything a JSON manifest lists, headlessly. Safe to re-run (re-creates what it owns).

  UD_MANIFEST=/abs/path/assets.json \
  $UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor /abs/MyGame.uproject \
      -run=pythonscript -script=/abs/path/scripts/import/import_manifest.py -unattended -nopause -nosplash -nullrhi

Only some steps: UD_IMPORT_ONLY=materials,textures (keys of the manifest). Check the output for "UD_IMPORT FAILED"
and "UD_IMPORT missing" lines: a failed import is only a log line, not an exit code.

Manifest (see assets.example.json; relative file paths are relative to the manifest's folder):
  {
    "maps":      [{"folder": "/Game/MyGame/Maps", "name": "Main"}],
    "materials": [{"kind": "model" | "flat" | "flat_unlit" | "flat_additive", "folder": "/Game/MyGame/Materials", "name": "M_Model"}],
    "textures":  [{"file": "art/T_Logo.png", "dest": "/Game/MyGame/UI", "name": "T_Logo", "ui": true, "never_stream": false, ...}],
    "models":    [{"file": "models/hero.glb", "base": "/Game/MyGame/Models", "name": "hero",
                   "parent": "/Game/MyGame/Materials/M_Model", "scalars": {"EmissiveBoost": 3.0}, "max_tex": 0}],
    "sounds":    [{"dir": "audio/sfx", "dest": "/Game/MyGame/Audio/SFX"}, {"file": "audio/music/theme_loop.wav", "dest": "/Game/MyGame/Audio/Music"}]
  }
Materials run before models (model instances need their parent). For anything the manifest cannot express, write
your own script that imports ue_import and calls G(...) directly (Starseal built ~20 materials that way).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_import as ui  # noqa: E402

MODEL_PARAMS = {"BaseTex": ("diffuse", "basecolor", "albedo"), "EmissiveTex": ("emissive",), "NormalTex": ("normal",)}


def main():
    path = os.environ.get("UD_MANIFEST", "")
    if not path or not os.path.exists(path):
        ui.log(f"FAILED no manifest: set UD_MANIFEST to an absolute path (got {path!r})")
        return
    root = os.path.dirname(os.path.abspath(path))
    m = json.load(open(path))
    only = [x for x in os.environ.get("UD_IMPORT_ONLY", "").split(",") if x]

    def want(key):
        return key in m and (not only or key in only)

    def f(rel):
        return rel if os.path.isabs(rel) else os.path.join(root, rel)

    if want("maps"):
        for e in m["maps"]:
            ui.empty_map(e["folder"], e["name"])
    if want("materials"):
        for e in m["materials"]:
            k = e.get("kind", "flat")
            if k == "model":
                ui.model_material(e["folder"], e["name"])
            else:
                ui.flat_material(e["folder"], e["name"], unlit=k == "flat_unlit", additive=k == "flat_additive")
    if want("textures"):
        TC = ui.TC
        for e in m["textures"]:
            comp = getattr(TC, e["compression"]) if "compression" in e else TC.TC_DEFAULT
            ui.import_texture(f(e["file"]), e["dest"], e["name"], comp=comp, srgb=e.get("srgb", True), mips=e.get("mips", True),
                              ui=e.get("ui", False), wrap=e.get("wrap", True), never_stream=e.get("never_stream", False),
                              max_size=e.get("max_size", 0), lod_bias=e.get("lod_bias", 0))
    if want("models"):
        for e in m["models"]:
            ui.import_glb_model(f(e["file"]), e["base"], e["name"], parent_material=e.get("parent"),
                                params=e.get("params", MODEL_PARAMS), scalar_params=e.get("scalars"),
                                collision=e.get("collision", False), max_tex=e.get("max_tex", 0))
    if want("sounds"):
        for e in m["sounds"]:
            if "dir" in e:
                d = f(e["dir"])
                for name in sorted(os.listdir(d)):
                    if name.lower().endswith(".wav"):
                        ui.import_sound(os.path.join(d, name), e["dest"])
            else:
                ui.import_sound(f(e["file"]), e["dest"], e.get("name"), e.get("looping"))
    ui.log("done")


main()
