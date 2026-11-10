# Sandboxed editor script: a temporary river made of water-coloured planes along the river line, until the
# Water plugin river replaces it. DATA = {"points": [{x,y,z,width}...] (cm, z relative to base), "base_z": cm}
M = "editor_toolset.toolsets.material.MaterialTools."
O = "editor_toolset.toolsets.object.ObjectTools."
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
AT = "editor_toolset.toolsets.asset.AssetTools."
MAT_DIR, MAT = "/Game/ARPG/Environment/Terrain", "M_TempWater"


def call(n, a):
    return execute_tool(n, json.dumps(a))


def water_material():
    path = MAT_DIR + "/" + MAT
    if call(AT + "exists", {"path": path})["returnValue"]:
        return {"refPath": path + "." + MAT}
    mat = call(M + "create_material", {"folder_path": MAT_DIR, "asset_name": MAT})["returnValue"]

    def node(cls, props):
        e = call(M + "add_expression", {"material_or_function": mat,
                 "expression_class": {"refPath": "/Script/Engine.MaterialExpression" + cls}, "x": -400, "y": 0})["returnValue"]
        call(O + "set_properties", {"instance": e, "values": json.dumps(props)})
        return e
    col = node("Constant3Vector", {"Constant": {"R": 0.02, "G": 0.07, "B": 0.09, "A": 1}})
    rough = node("Constant", {"R": 0.04})
    spec = node("Constant", {"R": 0.9})
    call(M + "connect_to_output", {"expression": col, "output_name": "", "material_property": "MP_BaseColor"})
    call(M + "connect_to_output", {"expression": rough, "output_name": "", "material_property": "MP_Roughness"})
    call(M + "connect_to_output", {"expression": spec, "output_name": "", "material_property": "MP_Specular"})
    call(M + "recompile", {"material_or_function": mat})
    call(AT + "save_assets", {"asset_paths": [path]})
    return mat


def run():
    mat = water_material()
    for a in call(S + "find_actors", {"name": "", "tag": "RiverTemp", "collision_channels": []})["returnValue"]:
        call(S + "remove_from_scene", {"actor": a})
    pts = DATA["points"]
    made = 0
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        dx, dy = q["x"] - p["x"], q["y"] - p["y"]
        length = math.hypot(dx, dy) + 300            # overlap neighbours so the bends have no gaps
        yaw = math.degrees(math.atan2(dy, dx))
        z = DATA["base_z"] + (p["z"] + q["z"]) / 2
        a = call(S + "add_to_scene_from_asset", {"asset_path": "/Engine/BasicShapes/Plane", "name": f"RiverTemp_{i:02d}",
                 "xform": {"location": {"x": (p["x"] + q["x"]) / 2, "y": (p["y"] + q["y"]) / 2, "z": z},
                           "rotation": {"pitch": 0, "yaw": yaw, "roll": 0},
                           "scale": {"x": length / 100.0, "y": (p["width"] + 400) / 100.0, "z": 1}}})["returnValue"]
        call(A + "add_tag", {"actor": a, "tag": "RiverTemp"})
        call(S + "set_actor_folder", {"actor": a, "folder_path": "Water/RiverTemp"})
        for c in call(A + "get_components", {"actor": a})["returnValue"]:
            if "StaticMeshComponent" in c["refPath"]:
                call(O + "set_properties", {"instance": c, "values": json.dumps(
                    {"OverrideMaterials": [mat["refPath"]], "CastShadow": False})})
        made += 1
    return {"segments": made, "material": mat["refPath"]}
