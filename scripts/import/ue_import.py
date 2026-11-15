"""Editor-Python helpers for importing assets and building materials headlessly (no editor UI).

Runs inside UnrealEditor's Python (module `unreal`), from a commandlet:

  $UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor MyGame.uproject \
      -run=pythonscript -script=<ABSOLUTE path to a script that imports this module> \
      -unattended -nopause -nosplash -nullrhi

Extracted from Starseal's import script (PNG / GLB / WAV through Interchange, ~20 materials built node by node).
What it knows (guides/headless-import.md):
- Under -nullrhi, MaterialEditingLibrary.recompile_material raises: skip it, the shaders compile when the game or
  the cook first loads the material.
- In a commandlet the asset registry has not scanned engine content: EditorAssetLibrary.load_asset does not find
  /Engine/... assets, unreal.load_asset does.
- Interchange GLB import: glTF (x, y, z) -> UE (x, z, y) x 100. A model facing glTF +Z faces UE +Y (yaw -90 to face
  +X). Pivots are kept. Each GLB makes <dest>/<name>/{StaticMeshes,Textures,Materials}.
- Rebuild a material IN PLACE (delete its expressions, keep the object): material instances parented to it keep
  working, so models need no re-import after a material change.
- A Masked material clips at 0.3333 by default: an opacity mask built as "noise - dissolve" eats ~30% of every model at
  dissolve 0. Offset it so that "parameter 0" keeps every pixel.
- World-projected textures (no meaningful mesh UV) should be never_stream: the streamer estimates mips from UVs and
  leaves them blurry.
"""
import os

import unreal

tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
MP = unreal.MaterialProperty
TC = unreal.TextureCompressionSettings

LOG_PREFIX = os.environ.get("UD_IMPORT_LOG_PREFIX", "UD_IMPORT")


def log(msg):
    # log_warning so the line shows in the commandlet's stdout even at default verbosity; grep the prefix
    unreal.log_warning(f"{LOG_PREFIX} {msg}")


def fresh_dir(path):
    if eal.does_directory_exist(path):
        eal.delete_directory(path)


def fresh(path):
    if eal.does_asset_exist(path):
        eal.delete_asset(path)


def import_file(filename, dest, name=None):
    """One file through the automated import task (Interchange handles PNG / GLB / WAV). Returns imported paths."""
    t = unreal.AssetImportTask()
    t.filename = filename
    t.destination_path = dest
    if name:
        t.destination_name = name
    t.automated = True
    t.replace_existing = True
    t.save = True
    tools.import_asset_tasks([t])
    return list(t.imported_object_paths)


# ---------------------------------------------------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------------------------------------------------
def import_texture(filename, dest, name, comp=TC.TC_DEFAULT, srgb=True, mips=True, ui=False, wrap=True,
                   never_stream=False, max_size=0, lod_bias=0):
    """ui=True: UI group, no mips (and consider comp=TC_EDITOR_ICON / uncompressed: block compression frays line art)."""
    if not os.path.exists(filename):
        log(f"missing {filename}")
        return None
    fresh(f"{dest}/{name}")
    import_file(filename, dest, name)
    tex = eal.load_asset(f"{dest}/{name}")
    if not tex:
        log(f"FAILED texture {filename}")
        return None
    tex.set_editor_property("compression_settings", comp)
    tex.set_editor_property("srgb", srgb)
    if ui:
        tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
    if not mips or ui:
        tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    if not wrap:
        tex.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
        tex.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
    if never_stream:
        tex.set_editor_property("never_stream", True)
    if lod_bias:
        tex.set_editor_property("lod_bias", lod_bias)
    if max_size:
        tex.set_editor_property("max_texture_size", max_size)
    eal.save_asset(f"{dest}/{name}", only_if_is_dirty=False)
    log(f"texture {dest}/{name}")
    return tex


# ---------------------------------------------------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------------------------------------------------
def import_sound(filename, dest, name=None, looping=None):
    """WAV -> SoundWave. looping=None: loop when the name ends in _loop."""
    name = name or os.path.splitext(os.path.basename(filename))[0]
    if not os.path.exists(filename):
        log(f"missing {filename}")
        return None
    fresh(f"{dest}/{name}")
    import_file(filename, dest, name)
    sw = eal.load_asset(f"{dest}/{name}")
    if not sw:
        log(f"FAILED sound {filename}")
        return None
    sw.set_editor_property("looping", name.endswith("_loop") if looping is None else looping)
    eal.save_asset(f"{dest}/{name}", only_if_is_dirty=False)
    log(f"sound {dest}/{name} dur={sw.get_editor_property('duration'):.1f}")
    return sw


# ---------------------------------------------------------------------------------------------------------------------
# models (GLB via Interchange)
# ---------------------------------------------------------------------------------------------------------------------
def configure_mesh(sm, collision=False, nanite=False):
    try:
        ns = sm.get_editor_property("nanite_settings")
        ns.set_editor_property("enabled", nanite)
        sm.set_editor_property("nanite_settings", ns)
    except Exception as e:  # property name differs between versions
        log(f"nanite setting skipped: {e}")
    if not collision:
        try:
            unreal.EditorStaticMeshLibrary.remove_collisions(sm)
        except Exception:
            pass


def _find_static_mesh(folder, preferred):
    sm = eal.load_asset(preferred) if eal.does_asset_exist(preferred) else None
    if sm:
        return sm
    # Interchange may name things after the file or the glTF node: take any static mesh in the folder
    for p in eal.list_assets(folder, recursive=True):
        a = eal.load_asset(p)
        if isinstance(a, unreal.StaticMesh):
            return a
    return None


def import_glb_model(glb, base, name, parent_material=None, params=None, scalar_params=None, collision=False, max_tex=0,
                     keep_textures=("diffuse", "basecolor", "albedo", "emissive", "normal")):
    """GLB -> <base>/<name>/StaticMeshes/<name> + a material instance MI_<name> of parent_material.

    params maps a texture parameter name to substrings of the imported texture names, e.g.
      {"BaseTex": ("diffuse", "basecolor", "albedo"), "EmissiveTex": ("emissive",), "NormalTex": ("normal",)}
    Textures whose names match none of keep_textures (ORM etc.) and the glTF material Interchange made are deleted.
    max_tex: cap texture size (props seen from afar: 512 keeps the download small).
    """
    d = f"{base}/{name}"
    fresh_dir(d)
    if not os.path.exists(glb):
        log(f"missing {glb}")
        return None
    import_file(glb, base)
    sm = _find_static_mesh(d, f"{d}/StaticMeshes/{name}")
    if not sm:
        log(f"FAILED model {glb}")
        return None
    configure_mesh(sm, collision=collision)
    texs = {p.split("/")[-1].split(".")[0].lower(): p for p in eal.list_assets(f"{d}/Textures", recursive=True)}
    if parent_material:
        parent = unreal.load_asset(parent_material)
        mi_path = f"{d}/MI_{name}"
        fresh(mi_path)
        mi = tools.create_asset(f"MI_{name}", d, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, parent)
        for param, keys in (params or {}).items():
            hit = next((p for k, p in sorted(texs.items()) if any(s in k for s in keys)), None)
            if hit:
                mel.set_material_instance_texture_parameter_value(mi, param, eal.load_asset(hit))
            else:
                log(f"WARNING {name}: no texture for {param} among {sorted(texs)}")
        for param, value in (scalar_params or {}).items():
            mel.set_material_instance_scalar_parameter_value(mi, param, value)
        eal.save_asset(mi_path, only_if_is_dirty=False)
        sm.set_material(0, mi)
        eal.save_asset(sm.get_path_name(), only_if_is_dirty=False)
        for key, p in texs.items():
            if not any(k in key for k in keep_textures):
                eal.delete_asset(p)
            elif max_tex:
                t = eal.load_asset(p)
                t.set_editor_property("max_texture_size", max_tex)
                eal.save_asset(p, only_if_is_dirty=False)
        if eal.does_directory_exist(f"{d}/Materials"):
            eal.delete_directory(f"{d}/Materials")
    b = sm.get_bounding_box()
    log(f"model {sm.get_path_name()} min=({b.min.x:.1f},{b.min.y:.1f},{b.min.z:.1f}) max=({b.max.x:.1f},{b.max.y:.1f},{b.max.z:.1f}) tex={sorted(texs)}")
    return sm


# ---------------------------------------------------------------------------------------------------------------------
# materials, node by node
# ---------------------------------------------------------------------------------------------------------------------
class G:
    """Tiny material-graph builder.

        g = G("/Game/MyGame/Materials", "M_Glow", shading="unlit", blend="additive")
        col = g.mul(g.vector("Color", (1, 1, 1, 1)), g.scalar("Strength", 4.0))
        g.out(col, MP.MP_EMISSIVE_COLOR)
        g.save()

    Numbers passed where a node is expected become Constant nodes. oa / ob / src_out name an output pin ("RGB", "R", ...).
    Rebuilds an existing material in place (instances parented to it keep working).
    """

    def __init__(self, folder, name, shading="lit", blend="opaque", two_sided=False, ism=False):
        path = f"{folder}/{name}"
        self.path = path
        old = eal.load_asset(path) if eal.does_asset_exist(path) else None
        if isinstance(old, unreal.Material) and hasattr(mel, "delete_all_material_expressions"):
            mel.delete_all_material_expressions(old)
            self.m = old
        else:
            fresh(path)
            self.m = tools.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
        m = self.m
        if shading == "unlit":
            m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        m.set_editor_property("blend_mode", {
            "opaque": unreal.BlendMode.BLEND_OPAQUE, "masked": unreal.BlendMode.BLEND_MASKED,
            "additive": unreal.BlendMode.BLEND_ADDITIVE, "translucent": unreal.BlendMode.BLEND_TRANSLUCENT}[blend])
        m.set_editor_property("two_sided", two_sided)
        if ism:
            m.set_editor_property("used_with_instanced_static_meshes", True)
        self.x = -1600
        self.y = 0

    def node(self, cls, **props):
        self.y += 90
        if self.y > 1800:
            self.y = 0
            self.x += 260
        e = mel.create_material_expression(self.m, cls, self.x, self.y)
        for k, v in props.items():
            e.set_editor_property(k, v)
        return e

    def scalar(self, name, default):
        return self.node(unreal.MaterialExpressionScalarParameter, parameter_name=name, default_value=default)

    def vector(self, name, rgba):
        return self.node(unreal.MaterialExpressionVectorParameter, parameter_name=name, default_value=unreal.LinearColor(*rgba))

    def const(self, v):
        return self.node(unreal.MaterialExpressionConstant, r=v)

    def tex(self, name, path, uv=None, sampler=None):
        t = unreal.load_asset(path) if path else None  # (engine content is not in the commandlet's asset registry)
        if path and not t:
            log(f"WARNING texture not found {path}")
        e = self.node(unreal.MaterialExpressionTextureSampleParameter2D, parameter_name=name)
        if t:
            e.set_editor_property("texture", t)
            if sampler is None:
                cs = t.get_editor_property("compression_settings")
                if cs == TC.TC_NORMALMAP:
                    sampler = unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
                elif cs == TC.TC_GRAYSCALE:
                    sampler = unreal.MaterialSamplerType.SAMPLERTYPE_GRAYSCALE if t.get_editor_property("srgb") else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE
                elif not t.get_editor_property("srgb"):
                    sampler = unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR
            if sampler is not None:
                e.set_editor_property("sampler_type", sampler)
        if uv is not None:
            self.link(uv, e, "UVs")
        return e

    def op(self, cls, a, b=None, ia="A", ib="B", oa="", ob="", **props):
        e = self.node(cls, **props)
        self.link(a, e, ia, oa)
        if b is not None:
            self.link(b, e, ib, ob)
        return e

    def mul(self, a, b, oa="", ob=""):
        return self.op(unreal.MaterialExpressionMultiply, a, b, oa=oa, ob=ob)

    def add(self, a, b, oa="", ob=""):
        return self.op(unreal.MaterialExpressionAdd, a, b, oa=oa, ob=ob)

    def sub(self, a, b, oa="", ob=""):
        return self.op(unreal.MaterialExpressionSubtract, a, b, oa=oa, ob=ob)

    def lerp(self, a, b, alpha, oa="", ob="", oc=""):
        e = self.node(unreal.MaterialExpressionLinearInterpolate)
        self.link(a, e, "A", oa)
        self.link(b, e, "B", ob)
        self.link(alpha, e, "Alpha", oc)
        return e

    def sat(self, a, oa=""):
        return self.op(unreal.MaterialExpressionSaturate, a, ia="", oa=oa)

    def power(self, a, b, oa=""):
        e = self.node(unreal.MaterialExpressionPower)
        self.link(a, e, "Base", oa)
        self.link(b, e, "Exponent")
        return e

    def one_minus(self, a, oa=""):
        return self.op(unreal.MaterialExpressionOneMinus, a, ia="", oa=oa)

    def mask(self, a, r=False, g=False, b=False, al=False, src=""):
        e = self.node(unreal.MaterialExpressionComponentMask, r=r, g=g, b=b, a=al)
        self.link(a, e, "", src)
        return e

    def length(self, a):
        return self.fn1(unreal.MaterialExpressionSquareRoot, self.op(unreal.MaterialExpressionDotProduct, a, a))

    def append(self, a, b, oa="", ob=""):
        return self.op(unreal.MaterialExpressionAppendVector, a, b, oa=oa, ob=ob)

    def fn1(self, cls, a, oa="", **props):
        e = self.node(cls, **props)
        self.link(a, e, "", oa)
        return e

    def link(self, src, dst, dst_in="", src_out=""):
        if isinstance(src, (int, float)):
            src = self.const(float(src))
        mel.connect_material_expressions(src, src_out, dst, dst_in)

    def out(self, src, prop, src_out=""):
        if isinstance(src, (int, float)):
            src = self.const(float(src))
        mel.connect_material_property(src, src_out, prop)

    def save(self):
        try:
            mel.layout_material_expressions(self.m)
        except Exception:
            pass
        try:
            mel.recompile_material(self.m)
        except RuntimeError:
            pass  # -nullrhi: shaders compile when the game / cook loads the material
        eal.save_asset(self.path, only_if_is_dirty=False)
        log(f"material {self.path}")
        return self.m


def to_local_pos(g, p, scale):
    """World position -> the primitive's local frame (x its uniform scale). Sample textures in local space when the
    object moves or rotates (a planet turning under the player): world-space sampling makes textures slide."""
    t = g.fn1(unreal.MaterialExpressionTransformPosition, p,
              transform_source_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD,
              transform_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL)
    return g.mul(t, scale)


def model_material(folder, name="M_Model"):
    """The textured, lit model material Starseal used for imported GLBs: base colour x Tint, normal map, emissive map
    x EmissiveBoost, Fresnel rim light, a Flash parameter and a noise Dissolve (Masked, two-sided: AI-generated meshes
    often have single-layer fins that back-face culling turns into holes). NoiseTex defaults to an engine texture;
    point it at your own noise texture."""
    g = G(folder, name, blend="masked", two_sided=True)
    uv = g.node(unreal.MaterialExpressionTextureCoordinate)
    base = g.tex("BaseTex", "/Engine/EngineResources/WhiteSquareTexture", uv)
    emi = g.tex("EmissiveTex", "/Engine/EngineResources/Black", uv)
    nrm = g.tex("NormalTex", "/Engine/EngineMaterials/DefaultNormal", uv, sampler=unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tint = g.vector("Tint", (1, 1, 1, 1))
    glow_col = g.vector("GlowColor", (1, 1, 1, 1))
    boost = g.scalar("EmissiveBoost", 4.0)
    rim_col = g.vector("RimColor", (0.3, 0.8, 1.0, 1))
    rim_str = g.scalar("RimStrength", 1.5)
    flash_col = g.vector("FlashColor", (1, 1, 1, 1))
    flash = g.scalar("Flash", 0.0)
    dissolve = g.scalar("Dissolve", 0.0)
    g.out(g.mul(base, tint, oa="RGB"), MP.MP_BASE_COLOR)
    g.out(nrm, MP.MP_NORMAL, "RGB")
    g.out(0.0, MP.MP_METALLIC)
    g.out(0.6, MP.MP_ROUGHNESS)
    e_main = g.mul(g.mul(emi, glow_col, oa="RGB"), boost)
    fr = g.node(unreal.MaterialExpressionFresnel, exponent=3.0, base_reflect_fraction=0.0)
    rim = g.mul(g.mul(fr, rim_col), rim_str)
    fl = g.mul(g.mul(flash_col, flash), g.add(g.mul(base, 0.6, oa="RGB"), 0.4))
    noise = g.tex("NoiseTex", "/Engine/EngineMaterials/Good64x64TilingNoiseHighFreq", uv)
    # the mask clips below 0.3333 (UE default): +0.345 keeps every pixel at Dissolve = 0, Dissolve = 1 removes all
    thr = g.mul(dissolve, 1.05)
    edge_d = g.sub(g.mask(noise, r=True), thr)
    g.out(g.add(edge_d, 0.345), MP.MP_OPACITY_MASK)
    edge = g.mul(g.sat(g.sub(1.0, g.mul(g.fn1(unreal.MaterialExpressionAbs, edge_d), 14.0))), g.sat(g.mul(dissolve, 20.0)))
    edge_e = g.mul(g.mul(edge, glow_col), 30.0)
    g.out(g.add(g.add(g.add(e_main, rim), fl), edge_e), MP.MP_EMISSIVE_COLOR)
    return g.save()


def flat_material(folder, name, unlit=False, additive=False, ism=True):
    """Color x Emissive parameters; lit / unlit / additive glow. Enough for a grey-box game spawned from C++."""
    g = G(folder, name, shading="unlit" if (unlit or additive) else "lit", blend="additive" if additive else "opaque", ism=ism)
    color = g.vector("Color", (1, 1, 1, 1))
    glow = g.mul(color, g.scalar("Emissive", 1.0))
    g.out(glow, MP.MP_EMISSIVE_COLOR)
    if not (unlit or additive):
        g.out(color, MP.MP_BASE_COLOR)
        g.out(0.65, MP.MP_ROUGHNESS)
    return g.save()


def empty_map(folder, name):
    """An empty level: the game mode spawns the world from C++."""
    path = f"{folder}/{name}"
    fresh(path)
    tools.create_asset(name, folder, unreal.World, unreal.WorldFactory())
    eal.save_asset(path, only_if_is_dirty=False)
    log(f"map {path}")
