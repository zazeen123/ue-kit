# Sandboxed editor script (ProgrammaticToolset): Vocaris landscape material v2 - the v1 auto material
# (grass flats / rocky soil slopes / rock cliffs by world normal, world-aligned UVs) plus per-island themes
# read from a biome mask texture laid over the landscape extent:
#   R = Drakoria: volcanic ash instead of grass, darker rock     G = Arcanis: snow above the snow line
#   B = lush green (Solara, Island of Solitude)                   (else) temperate green
# DATA = {"folder", "name", "grass_d", "soil_d", "soil_n", "rock_d", "rock_n", "virtual": [...],
#         "biome": texture path, "biome_origin": [x, y] cm, "biome_extent": cm, "snow_z": cm, "snow_blend": cm}
M = "editor_toolset.toolsets.material.MaterialTools."
O = "editor_toolset.toolsets.object.ObjectTools."
AT = "editor_toolset.toolsets.asset.AssetTools."


def call(n, a):
    return execute_tool(n, json.dumps(a))


def run():
    path = DATA["folder"] + "/" + DATA["name"]
    if call(AT + "exists", {"path": path})["returnValue"]:
        return {"error": path + " exists - pick a new name (deleting an assigned material can open a modal dialog)"}
    mat = call(M + "create_material", {"folder_path": DATA["folder"], "asset_name": DATA["name"]})["returnValue"]
    pos = [0]

    def node(cls, props=None):
        pos[0] += 1
        e = call(M + "add_expression", {"material_or_function": mat,
                 "expression_class": {"refPath": "/Script/Engine.MaterialExpression" + cls},
                 "x": -2400 + (pos[0] % 8) * 300, "y": (pos[0] // 8) * 220})["returnValue"]
        if props:
            call(O + "set_properties", {"instance": e, "values": json.dumps(props)})
        return e

    def first_input(e):
        names = call(M + "get_expression_input_names", {"expression": e})["returnValue"]
        return names[0] if names else ""

    def link(a, b, pin=None, out=""):
        call(M + "connect_expressions", {"from_expression": a, "from_output_name": out,
                                         "to_expression": b, "to_input_name": pin if pin is not None else first_input(b)})

    def const(v):
        return node("Constant", {"R": v})

    def color(r, g, b):
        return node("Constant3Vector", {"Constant": {"R": r, "G": g, "B": b, "A": 1}})

    def op(cls, a, b):
        e = node(cls)
        link(a, e, "A")
        link(b, e, "B")
        return e

    def lerp(a, b, alpha):
        e = node("LinearInterpolate")
        link(a, e, "A")
        link(b, e, "B")
        link(alpha, e, "Alpha")
        return e

    def mask(src, r, g, b, a):     # new ComponentMask nodes default to R+G: always set all four
        e = node("ComponentMask", {"R": r, "G": g, "B": b, "A": a})
        link(src, e)
        return e

    def sat(x):
        e = node("Saturate")
        link(x, e)
        return e

    def tex(path, uv, normal=False, linear=False):
        virt = "/MS/" in path or path in DATA.get("virtual", [])
        if linear:
            st = "SAMPLERTYPE_LinearColor"     # uncompressed RGBA, sRGB off
        else:
            st = ("SAMPLERTYPE_Virtual" if virt else "SAMPLERTYPE_") + ("Normal" if normal else "Color")
        e = node("TextureSample", {"Texture": path, "SamplerType": st})
        link(uv, e, "UVs")
        return e

    wp = node("WorldPosition")
    xy = mask(wp, True, True, False, False)
    wz = mask(wp, False, False, True, False)

    def uv(m):
        return op("Divide", xy, const(m * 100.0))

    uv_g, uv_s, uv_r, uv_m = uv(4.0), uv(3.0), uv(9.0), uv(160.0)
    nrm = node("VertexNormalWS")
    nz = mask(nrm, False, False, True, False)

    def slope(th, k):
        return sat(op("Multiply", op("Subtract", const(th), nz), const(k)))

    soil_a, rock_a = slope(0.95, 12.0), slope(0.80, 7.0)

    # biome masks: UV = (world xy - origin) / extent
    org = node("Constant2Vector", {"R": DATA["biome_origin"][0], "G": DATA["biome_origin"][1]})
    buv = op("Divide", op("Subtract", xy, org), const(DATA["biome_extent"]))
    bio = tex(DATA["biome"], buv, linear=True)
    b_ash = mask(bio, True, False, False, False)
    b_snow = mask(bio, False, True, False, False)
    b_lush = mask(bio, False, False, True, False)

    g_d = tex(DATA["grass_d"], uv_g)
    s_d, s_n = tex(DATA["soil_d"], uv_s), tex(DATA["soil_n"], uv_s, True)
    r_d, r_n = tex(DATA["rock_d"], uv_r), tex(DATA["rock_n"], uv_r, True)
    macro = mask(tex(DATA["grass_d"], uv_m), False, True, False, False)
    vary = lerp(const(0.8), const(1.15), macro)

    # grass: desaturate the brownish moss, then tint green (lush islands greener)
    gray = node("Desaturation")
    link(g_d, gray)
    call(O + "set_properties", {"instance": gray, "values": json.dumps({"LuminanceFactors": {"R": 0.3, "G": 0.59, "B": 0.11, "A": 0}})})
    tint = lerp(color(0.62, 0.95, 0.38), color(0.48, 1.05, 0.30), b_lush)
    grass = op("Multiply", op("Multiply", op("Multiply", gray, tint), vary), const(1.25))
    # volcanic ash ground on Drakoria: dark grey-brown soil
    ash = op("Multiply", s_d, color(0.42, 0.36, 0.33))
    flat = lerp(grass, ash, b_ash)
    soil = lerp(s_d, op("Multiply", s_d, color(0.55, 0.48, 0.45)), b_ash)
    rock = lerp(r_d, op("Multiply", r_d, color(0.45, 0.40, 0.40)), b_ash)
    base = lerp(lerp(flat, soil, soil_a), rock, rock_a)
    # snow on Arcanis above the snow line, thinner on steep rock
    above = sat(op("Divide", op("Subtract", wz, const(DATA["snow_z"])), const(DATA["snow_blend"])))
    snow_a = op("Multiply", op("Multiply", above, b_snow), sat(op("Multiply", nz, const(1.4))))
    base = lerp(base, color(0.86, 0.89, 0.93), snow_a)

    flat_n = node("Constant3Vector", {"Constant": {"R": 0, "G": 0, "B": 1, "A": 1}})
    normal = lerp(lerp(flat_n, s_n, soil_a), r_n, rock_a)
    rough = lerp(const(0.88), const(0.6), snow_a)
    call(M + "connect_to_output", {"expression": base, "output_name": "", "material_property": "MP_BaseColor"})
    call(M + "connect_to_output", {"expression": normal, "output_name": "", "material_property": "MP_Normal"})
    call(M + "connect_to_output", {"expression": rough, "output_name": "", "material_property": "MP_Roughness"})
    call(M + "layout_expressions", {"material_or_function": mat})
    call(M + "recompile", {"material_or_function": mat})
    saved = call(AT + "save_assets", {"asset_paths": [path]})["returnValue"]
    return {"material": mat["refPath"], "nodes": pos[0], "saved": saved}
