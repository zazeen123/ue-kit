# Sandboxed editor script: temporary water for the Vocaris world until the Water plugin replaces it -
# one sea plane, a disc per lake, plane segments along each river. Everything tagged WorldWaterTemp
# (removed and rebuilt on every run), folder Water/Temp, material M_TempWater (made by temp_river_job.py).
# DATA = {"sea": {"x","y","z","size"}, "lakes": [{x,y,z,radius_cm}], "rivers": [{"width_cm", "points": [{x,y,z}]}]}
import math

S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
O = "editor_toolset.toolsets.object.ObjectTools."
MAT = "/Game/ARPG/Environment/Terrain/M_TempWater.M_TempWater"
TAG = "WorldWaterTemp"


def call(n, a):
    return execute_tool(n, json.dumps(a))


def spawn(mesh, name, loc, yaw, scale):
    a = call(S + "add_to_scene_from_asset", {"asset_path": mesh, "name": name,
             "xform": {"location": {"x": loc[0], "y": loc[1], "z": loc[2]},
                       "rotation": {"pitch": 0, "yaw": yaw, "roll": 0},
                       "scale": {"x": scale[0], "y": scale[1], "z": scale[2]}}})["returnValue"]
    call(A + "add_tag", {"actor": a, "tag": TAG})
    call(S + "set_actor_folder", {"actor": a, "folder_path": "Water/Temp"})
    for c in call(A + "get_components", {"actor": a})["returnValue"]:
        if "StaticMeshComponent" in c["refPath"]:
            call(O + "set_properties", {"instance": c, "values": json.dumps(
                {"OverrideMaterials": [MAT], "CastShadow": False})})
    return a


def run():
    removed = 0
    for a in call(S + "find_actors", {"name": "", "tag": TAG, "collision_channels": []})["returnValue"]:
        call(S + "remove_from_scene", {"actor": a})
        removed += 1
    sea = DATA["sea"]
    spawn("/Engine/BasicShapes/Plane", "Sea_Temp", (sea["x"], sea["y"], sea["z"]), 0, (sea["size"] / 100.0,) * 2 + (1,))
    made = 1
    for i, lk in enumerate(DATA["lakes"]):
        d = lk["radius_cm"] * 2 / 100.0 + 0.6
        spawn("/Engine/BasicShapes/Cylinder", f"Lake_Temp_{i}", (lk["x"], lk["y"], lk["z"] - 1), 0, (d, d, 0.02))
        made += 1
    for r_i, rv in enumerate(DATA["rivers"]):
        pts = rv["points"]
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            dx, dy = q["x"] - p["x"], q["y"] - p["y"]
            spawn("/Engine/BasicShapes/Plane", f"River_Temp_{r_i}_{i:02d}",
                  ((p["x"] + q["x"]) / 2, (p["y"] + q["y"]) / 2, (p["z"] + q["z"]) / 2),
                  math.degrees(math.atan2(dy, dx)),
                  ((math.hypot(dx, dy) + 400) / 100.0, (rv["width_cm"] + 600) / 100.0, 1))
            made += 1
    return {"removed": removed, "made": made}
