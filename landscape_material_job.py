# Sandboxed editor script (ProgrammaticToolset): builds an auto landscape material - grass on flat ground,
# rocky soil on slopes, rock on cliffs, by world-space normal; world-aligned UVs; large-scale tint.
# DATA = {"folder", "name", "grass_d", "grass_n", "soil_d", "soil_n", "rock_d", "rock_n"}
M = "editor_toolset.toolsets.material.MaterialTools."
O = "editor_toolset.toolsets.object.ObjectTools."
AT = "editor_toolset.toolsets.asset.AssetTools."


def call(n, a):
    return execute_tool(n, json.dumps(a))


def run():
    path = DATA["folder"] + "/" + DATA["name"]
    if call(AT + "exists", {"path": path})["returnValue"]:
        call(AT + "delete", {"path": path})
    mat = call(M + "create_material", {"folder_path": DATA["folder"], "asset_name": DATA["name"]})["returnValue"]
    pos = [0]

    def node(cls, props=None):
        pos[0] += 1
        e = call(M + "add_expression", {"material_or_function": mat,
                 "expression_class": {"refPath": "/Script/Engine.MaterialExpression" + cls},
                 "x": -2000 + (pos[0] % 6) * 300, "y": (pos[0] // 6) * 220})["returnValue"]
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

    def tex(path, uv, normal=False):
        virt = "/MS/" in path or path in DATA.get("virtual", [])   # virtual textures need virtual samplers
        st = ("SAMPLERTYPE_Virtual" if virt else "SAMPLERTYPE_") + ("Normal" if normal else "Color")
        e = node("TextureSample", {"Texture": path, "SamplerType": st})
        link(uv, e, "UVs")
        return e

    wp = node("WorldPosition")
    xy = node("ComponentMask", {"R": True, "G": True, "B": False, "A": False})
    link(wp, xy)

    def uv(m):
        return op("Divide", xy, const(m * 100.0))

    uv_g, uv_s, uv_r, uv_m = uv(4.0), uv(3.0), uv(9.0), uv(160.0)
    nrm = node("VertexNormalWS")
    nz = node("ComponentMask", {"R": False, "G": False, "B": True, "A": False})   # new masks start as R+G: set all four
    link(nrm, nz)

    def slope(th, k):
        d = op("Subtract", const(th), nz)
        m = op("Multiply", d, const(k))
        s = node("Saturate")
        link(m, s)
        return s

    soil_a, rock_a = slope(0.95, 12.0), slope(0.80, 7.0)
    g_d = tex(DATA["grass_d"], uv_g)
    if DATA.get("grass_n"):
        g_n = tex(DATA["grass_n"], uv_g, True)
    else:                                   # no usable normal map: flat
        g_n = node("Constant3Vector", {"Constant": {"R": 0, "G": 0, "B": 1, "A": 1}})
    s_d, s_n = tex(DATA["soil_d"], uv_s), tex(DATA["soil_n"], uv_s, True)
    r_d, r_n = tex(DATA["rock_d"], uv_r), tex(DATA["rock_n"], uv_r, True)
    macro = tex(DATA["grass_d"], uv_m)
    mg = node("ComponentMask", {"R": False, "G": True, "B": False, "A": False})
    link(macro, mg)
    tint = lerp(const(0.8), const(1.15), mg)
    grass = op("Multiply", g_d, tint)
    base = lerp(lerp(grass, s_d, soil_a), r_d, rock_a)
    normal = lerp(lerp(g_n, s_n, soil_a), r_n, rock_a)
    call(M + "connect_to_output", {"expression": base, "output_name": "", "material_property": "MP_BaseColor"})
    call(M + "connect_to_output", {"expression": normal, "output_name": "", "material_property": "MP_Normal"})
    call(M + "connect_to_output", {"expression": const(0.88), "output_name": "", "material_property": "MP_Roughness"})
    call(M + "layout_expressions", {"material_or_function": mat})
    call(M + "recompile", {"material_or_function": mat})
    saved = call(AT + "save_assets", {"asset_paths": [path]})["returnValue"]
    return {"material": mat["refPath"], "nodes": pos[0], "saved": saved}
