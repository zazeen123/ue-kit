"""Print what a test copy is really made of (component, mesh, relative location, scale).
python bp_parts.py BP_HouseInn BP_HouseDouble ..."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_client as ue  # noqa: E402

JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
O = "editor_toolset.toolsets.object.ObjectTools."
def call(n, a):
    return execute_tool(n, json.dumps(a))
def run():
    out = {}
    for label in DATA:
        found = call(S + "find_actors", {"name": label, "tag": "", "collision_channels": []})["returnValue"]
        if not found:
            out[label] = "missing"
            continue
        comps = call(A + "get_components", {"actor": found[0],
                     "component_type": {"refPath": "/Script/Engine.StaticMeshComponent"}})["returnValue"]
        rows = []
        for c in comps:
            v = json.loads(call(O + "get_properties", {"instance": c, "properties":
                    ["StaticMesh", "RelativeLocation", "RelativeRotation", "RelativeScale3D"]})["returnValue"])
            rows.append([c["refPath"].rsplit(".", 1)[-1], (v.get("StaticMesh") or {}).get("refPath", "").rsplit(".", 1)[-1],
                         [round(v["RelativeLocation"][k]) for k in "xyz"], round(v["RelativeRotation"]["yaw"]),
                         [round(v["RelativeScale3D"][k], 2) for k in "xyz"]])
        out[label] = rows
    return out
"""

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    res = ue.batch(JOB, [n + "_Test" for n in sys.argv[1:]])
    for k, rows in res.items():
        print("==", k)
        for r in (rows if isinstance(rows, list) else [rows]):
            print("  ", r)
