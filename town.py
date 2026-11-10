"""Town placement for ue-kit: put built designs on the lots of a layout file.

The layout is Docs/World/gatefall-layout.json (objects with type, ue{x,y} in cm, w/h in metres). Each chosen
lot gets one design, turned so its door faces the nearest road, set on the ground under it. Everything placed
carries the tag TOWN_TAG, and only actors with that tag are ever removed again. Test maps only.

Pure geometry (plan) is separate from the editor calls (ground, place, clear) so it can be tested offline.
"""
import json
import math
import os
import random

import kit
import ue_client as ue

LAYOUT = r"U:\ue\MyHeadLine\Docs\World\gatefall-layout.json"
PLAN = os.path.join(kit.HERE, "town_plan.json")
TOWN_TAG = "ue-kit-town"
WAYS = ("road", "plaza", "market")            # what a front door should face
FOUNDATION = "/Game/FantasyBundle/Meshes/SM_HouseBase01"      # stone block stretched under a house on a slope
S = "editor_toolset.toolsets.scene.SceneTools"
DIRS = {"+X": (1, 0), "-X": (-1, 0), "+Y": (0, 1), "-Y": (0, -1)}


# ---------------------------------------------------------------- layout and designs

def load_layout(path=None):
    with open(path or LAYOUT, encoding="utf-8") as f:
        return json.load(f)


def rect(o, origin=(0, 0)):
    """World rectangle of a layout object [minx, miny, maxx, maxy] in cm (rot is 0 or 90 in practice)."""
    w, h = o["w"] * 100.0, o["h"] * 100.0
    if round(o.get("rot", 0) / 90) % 2:
        w, h = h, w
    cx, cy = o["ue"]["x"] + origin[0], o["ue"]["y"] + origin[1]
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def footprint(name):
    """A design's plan box [minx, miny, maxx, maxy] in its own frame, its height, and the side its door is
    on ("+Y" when there is no door: the convention for a stall's front)."""
    d = kit.designs().get(name)
    if not d:
        raise ValueError(f"{name} is not a design on file (see get_design())")
    res = [p for p in kit.resolve(d["parts"]) if not p.get("light")]
    box = [min(p["box"][0] for p in res), min(p["box"][1] for p in res),
           max(p["box"][3] for p in res), max(p["box"][4] for p in res)]
    top = max(p["box"][5] for p in res)
    # the walls only: a wagon or fence beside the house must not decide where the house sits
    shells = [p for p in res if kit.is_shell(p)]
    if not shells:                  # a stall: its biggest piece (the canopy or table) is what occupies the lot
        shells = [max(res, key=lambda p: (p["box"][3] - p["box"][0]) * (p["box"][4] - p["box"][1]))]
    core = [min(p["box"][0] for p in shells), min(p["box"][1] for p in shells),
            max(p["box"][3] for p in shells), max(p["box"][4] for p in shells)]
    cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
    side = "+Y"
    doors = [p for p in res if "door" in p["name"].lower() and "frame" not in p["name"].lower()]
    if doors:
        b = doors[0]["box"]
        dx, dy = (b[0] + b[3]) / 2 - cx, (b[1] + b[4]) / 2 - cy
        # normalise by the half-size so a door on the long wall of a long house still reads as that wall
        nx, ny = dx / max(1.0, (core[2] - core[0]) / 2), dy / max(1.0, (core[3] - core[1]) / 2)
        side = ("+X" if nx > 0 else "-X") if abs(nx) > abs(ny) else ("+Y" if ny > 0 else "-Y")
    return {"box": box, "core": core, "top": top, "door": side,
            "walk_in": any(kit.WALK_IN.search(p["mesh"].rsplit("/", 1)[-1]) for p in res)}


def _rot(x, y, yaw):
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    return x * c - y * s, x * s + y * c


def _turned(box, yaw):
    pts = [_rot(x, y, yaw) for x in (box[0], box[2]) for y in (box[1], box[3])]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def _overlap(a, b, gap=0.0):
    return a[0] < b[2] - gap and b[0] < a[2] - gap and a[1] < b[3] - gap and b[1] < a[3] - gap


def face_way(lot, ways):
    """The side (+X -X +Y -Y) of a lot that looks at the nearest road, plaza or market, and how far it is."""
    cx, cy = (lot[0] + lot[2]) / 2, (lot[1] + lot[3]) / 2
    best = None
    for w in ways:
        px, py = min(max(cx, w[0]), w[2]), min(max(cy, w[1]), w[3])       # nearest point of that rectangle
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy)
        if dist < 1:                      # the lot centre is on the way itself
            continue
        if best is None or dist < best[0]:
            side = ("+X" if dx > 0 else "-X") if abs(dx) > abs(dy) else ("+Y" if dy > 0 else "-Y")
            best = (dist, side)
    return (best[1], best[0]) if best else ("+Y", 0.0)


def plan(layout, assign=None, types=("house",), lots=None, origin=(0, 0), seed=1):
    """Decides, without touching the editor, which design goes on which lot, turned which way.
    assign = {lot id: design name} fixes some or all lots; the rest are filled from the designs on file that
    fit the lot, so that neighbours differ. Returns (rows, issues)."""
    objs = layout["objects"]
    ways = [rect(o, origin) for o in objs if o["type"] in WAYS]
    roads = [rect(o, origin) for o in objs if o["type"] == "road"]      # a stall belongs ON the market square
    chosen = [o for o in objs if o["type"] in types and (not lots or o["id"] in lots)]
    assign = {int(k): v for k, v in (assign or {}).items()}
    issues = []
    for k in assign:
        if k not in {o["id"] for o in chosen}:
            issues.append(f"lot {k} is not one of the selected lots (types {', '.join(types)})")
    fps = {}
    for n in sorted(kit.designs()):
        try:
            fps[n] = footprint(n)
        except ValueError:
            continue
    rng = random.Random(seed)
    rows, used = [], []
    for o in sorted(chosen, key=lambda o: o["id"]):
        lot = rect(o, origin)
        lw, lh = lot[2] - lot[0], lot[3] - lot[1]
        side, dist = face_way(lot, ways)
        want_house = o["type"] != "stall"

        def fits(n):
            f = fps[n]
            yaw = _yaw_for(f["door"], side)
            t = _turned(f["core"], yaw)
            return t[2] - t[0] <= lw + 1 and t[3] - t[1] <= lh + 1

        name = assign.get(o["id"])
        if name and name not in fps:
            issues.append(f"lot {o['id']}: {name} is not a design on file")
            name = None
        if not name:
            pool = [n for n in fps if fps[n]["walk_in"] == want_house and fits(n)
                    and (want_house or "stall" in n.lower())]
            if not pool:
                issues.append(f"lot {o['id']} ({o['type']}, {lw:.0f} x {lh:.0f} cm): no design on file fits it")
                continue
            near = [r["design"] for r in sorted(rows, key=lambda r: math.hypot(r["centre"][0] - (lot[0] + lot[2]) / 2,
                                                                                 r["centre"][1] - (lot[1] + lot[3]) / 2))[:2]]
            fresh = [n for n in pool if n not in used] or [n for n in pool if n not in near] or pool
            name = rng.choice(sorted(fresh))
        f = fps[name]
        yaw = _yaw_for(f["door"], side)
        t = _turned(f["core"], yaw)
        cx, cy = (lot[0] + lot[2]) / 2, (lot[1] + lot[3]) / 2
        tc = ((t[0] + t[2]) / 2, (t[1] + t[3]) / 2)
        loc = [round(cx - tc[0], 1), round(cy - tc[1], 1)]
        world = _turned(f["box"], yaw)
        world = [world[0] + loc[0], world[1] + loc[1], world[2] + loc[0], world[3] + loc[1]]
        walls = [t[0] + loc[0], t[1] + loc[1], t[2] + loc[0], t[3] + loc[1]]
        row = {"lot": o["id"], "type": o["type"], "design": name, "yaw": yaw, "loc": loc, "centre": [cx, cy],
               "faces": side, "way_cm": round(dist), "box": [round(v) for v in world],
               "walls": [round(v) for v in walls], "lot_box": [round(v) for v in lot], "top": f["top"]}
        if walls[2] - walls[0] > lw + 1 or walls[3] - walls[1] > lh + 1:
            issues.append(f"TOO BIG: {name} ({walls[2]-walls[0]:.0f} x {walls[3]-walls[1]:.0f} cm) does not fit lot "
                          f"{o['id']} ({lw:.0f} x {lh:.0f} cm) - choose a smaller design")
        for w in (ways if want_house else roads):
            if _overlap(walls, w, 20):
                issues.append(f"ON THE ROAD: {name} on lot {o['id']} stands on a road/plaza - the lot itself overlaps it")
                break
        for r in rows:
            if _overlap(walls, r["walls"], 20):
                issues.append(f"OVERLAP: {name} on lot {o['id']} runs into {r['design']} on lot {r['lot']}")
        rows.append(row)
        used.append(name)
    return rows, issues


def _yaw_for(door_side, face_side):
    a = math.degrees(math.atan2(DIRS[face_side][1], DIRS[face_side][0]))
    b = math.degrees(math.atan2(DIRS[door_side][1], DIRS[door_side][0]))
    return float(round((a - b) % 360 / 90) % 4 * 90)


def table(rows):
    lines = ["lot | type | design | yaw | door faces | pivot x, y | walls min -> max (cm)"]
    for r in rows:
        w = r["walls"]
        z = f" | z {r['z']:.0f}" + (f" (ground {r['ground'][0]:.0f}..{r['ground'][1]:.0f})" if "ground" in r else "") if "z" in r else ""
        lines.append(f"{r['lot']} | {r['type']} | {r['design']} | {r['yaw']:.0f} | {r['faces']} ({r['way_cm']} cm to the "
                     f"road) | {r['loc'][0]:.0f}, {r['loc'][1]:.0f}{z} | ({w[0]}, {w[1]}) -> ({w[2]}, {w[3]})")
    return "\n".join(lines)


# ---------------------------------------------------------------- the ground under a lot

_GROUND_JOB = """
def run():
    out = []
    for q in DATA:
        d = execute_tool("editor_toolset.toolsets.scene.SceneTools.trace_world", json.dumps(
            {"start": {"x": q[0], "y": q[1], "z": 60000}, "end": {"x": q[0], "y": q[1], "z": -60000}}))["returnValue"]
        out.append(None if d is None else 60000 - d)
    return {"z": out}
"""


def ground(points):
    """Height of whatever a ray from the sky hits first at each (x, y): the ground, or a roof."""
    return ue.batch(_GROUND_JOB, [[float(x), float(y)] for x, y in points])["z"]


_OWN_JOB = """
A = "editor_toolset.toolsets.actor.ActorTools."
def run():
    found = execute_tool("editor_toolset.toolsets.scene.SceneTools.find_actors",
                         json.dumps({"name": "", "tag": DATA, "collision_channels": []}))["returnValue"]
    return {"labels": [execute_tool(A + "get_label", json.dumps({"actor": a}))["returnValue"] for a in found
                       if execute_tool(A + "has_tag", json.dumps({"actor": a, "tag": DATA}))["returnValue"]]}
"""


def own_lots():
    """Lot ids that already carry something ue-kit placed (labels Town_<lot>_...)."""
    out = set()
    for lab in ue.batch(_OWN_JOB, TOWN_TAG)["labels"]:
        parts = lab.split("_")
        if len(parts) > 2 and parts[0] == "Town" and parts[1].isdigit():
            out.add(int(parts[1]))
    return out


def survey(rows):
    """Adds z (where to put the pivot), the ground range under the walls, and flags: OCCUPIED when something
    already stands on the lot, STEEP when the ground falls more than a foundation can hide.
    Read-only: line traces."""
    issues = []
    pts, index = [], []
    for i, r in enumerate(rows):
        w, lot = r["walls"], r["lot_box"]
        inside = [(w[0] + 30, w[1] + 30), (w[2] - 30, w[1] + 30), (w[0] + 30, w[3] - 30), (w[2] - 30, w[3] - 30),
                  ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)]
        m = 150
        outside = [(lot[0] - m, lot[1] - m), (lot[2] + m, lot[1] - m), (lot[0] - m, lot[3] + m), (lot[2] + m, lot[3] + m)]
        for kind, group in (("in", inside), ("out", outside)):
            for p in group:
                pts.append(p)
                index.append((i, kind))
    zs = ground(pts)
    mine = own_lots()
    for i, r in enumerate(rows):
        zin = [z for z, (j, k) in zip(zs, index) if j == i and k == "in" and z is not None]
        zout = sorted(z for z, (j, k) in zip(zs, index) if j == i and k == "out" and z is not None)
        if not zin:
            r["z"], r["flag"] = 0.0, "NO GROUND"
            issues.append(f"NO GROUND: nothing under lot {r['lot']} - is this the right map?")
            continue
        base = zout[len(zout) // 2] if zout else min(zin)
        lo, hi = min(zin), max(zin)
        # taller than ALL the ground around the lot: a building, not a slope
        if hi > (max(zout) if zout else lo) + 120 and r["lot"] in mine:
            # ue-kit's own earlier placement stands there and will be replaced: the ground under it cannot be
            # seen, so take the ground around the lot
            r["z"], r["ground"], r["fill"] = round(base, 1), (round(min(zout), 1), round(max(zout), 1)), 0.0
            continue
        if hi > (max(zout) if zout else lo) + 120:
            r["z"], r["flag"], r["ground"] = round(base, 1), "OCCUPIED", (base, base)
            issues.append(f"LOT OCCUPIED: something {hi - base:.0f} cm tall already stands on lot {r['lot']} (ue-kit "
                          f"did not put it there and will not remove it) - skipped; clear the lot or leave it out")
            continue
        r["ground"] = (round(lo, 1), round(hi, 1))
        r["z"] = round(hi, 1)                      # nothing may be buried: sit on the highest corner ...
        r["fill"] = round(hi - lo, 1)              # ... and fill the gap below with a foundation
        if 40 <= hi - lo <= 150:
            issues.append(f"RAISED: lot {r['lot']} slopes {hi - lo:.0f} cm - {r['design']} gets a stone foundation and "
                          f"its floor is up to {hi - lo:.0f} cm above the ground on the low side; if its door is "
                          f"there it needs steps (or choose a flatter lot)")
        if hi - lo > 150:
            r["flag"] = "STEEP"
            issues.append(f"STEEP LOT: the ground under {r['design']} on lot {r['lot']} falls {hi - lo:.0f} cm - too "
                          f"much for a foundation; move the lot or level the ground there")
    return issues


# ---------------------------------------------------------------- placing and clearing (test maps only)

_PLACE_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
def call(name, args):
    return execute_tool(name, json.dumps(args))
def run():
    placed = []
    for r in DATA["rows"]:
        a = call(S + "add_to_scene_from_asset", {"asset_path": r["asset"], "name": r["label"],
                 "xform": {"location": {"x": r["x"], "y": r["y"], "z": r["z"]},
                           "rotation": {"pitch": 0, "yaw": r["yaw"], "roll": 0},
                           "scale": {"x": r.get("sx", 1), "y": r.get("sy", 1), "z": r.get("sz", 1)}}})["returnValue"]
        for t in DATA["tags"]:
            call(A + "add_tag", {"actor": a, "tag": t})
        call(S + "set_actor_folder", {"actor": a, "folder_path": DATA["folder"]})
        placed.append(a["refPath"])
    return {"placed": placed}
"""


def _guard():
    level = kit.current_level()
    if not kit.in_test_map(level):
        return level, (f"NOT PLACED: the open level is {level}, not a test map - ue-kit only places a town in a "
                       f"test map (e.g. L_GatefallTown_Preview). Nothing was changed.")
    return level, None


def remove_own():
    """Before a real placement: checks the level and removes ue-kit's earlier town, so that the survey sees
    the bare ground. Returns (error text or None, number removed)."""
    level, err = _guard()
    if err:
        return err, 0
    n = ue.batch(_CLEAR_JOB, TOWN_TAG)["removed"]
    if n:
        kit.log_action("clear_town", level=level, removed=n, why="before placing again")
    return None, n


def place(rows, dry_run=True, foundation=True, removed=None):
    """Puts the planned designs into the open test map - or, with dry_run, only says what it would do.
    removed = how many of ue-kit's own actors remove_own() already took out (None: do it here)."""
    todo = [r for r in rows if r.get("flag") not in ("OCCUPIED", "NO GROUND", "STEEP")]
    d = kit.designs()
    jobs = []
    for r in todo:
        e = d[r["design"]]
        jobs.append({"asset": f"{e['folder'].rstrip('/')}/{r['design']}", "label": f"Town_{r['lot']:02d}_{r['design']}",
                     "x": r["loc"][0], "y": r["loc"][1], "z": r["z"], "yaw": r["yaw"]})
        if foundation and r.get("fill", 0) >= 15:
            w = r["walls"]
            b = kit.bounds([FOUNDATION])[kit.full_path(FOUNDATION)]
            height = r["fill"] + 20
            jobs.append({"asset": FOUNDATION, "label": f"Town_{r['lot']:02d}_Foundation",
                         "x": (w[0] + w[2]) / 2, "y": (w[1] + w[3]) / 2, "z": r["z"] - height, "yaw": 0,
                         "sx": (w[2] - w[0] + 30) / (b[3] - b[0]), "sy": (w[3] - w[1] + 30) / (b[4] - b[1]),
                         "sz": height / (b[5] - b[2])})
    if dry_run:
        return {"dry": True, "jobs": jobs}
    level, err = _guard()
    if err:
        return {"error": err}
    # removal and placement as separate editor calls, like kit.build()
    if removed is None:
        removed = ue.batch(_CLEAR_JOB, TOWN_TAG)["removed"]
    ue.batch(_PLACE_JOB, {"tags": [kit.KIT_TAG, TOWN_TAG], "folder": "ue-kit/Town", "rows": jobs})
    there = ue.batch(_COUNT_JOB, TOWN_TAG)["n"]
    kit.log_action("place_town", level=level, removed=removed, placed=[j["label"] for j in jobs], in_level=there)
    kit._write_json(PLAN, {"level": level, "rows": rows})
    return {"removed": removed, "placed": there, "wanted": len(jobs), "jobs": jobs}


_CLEAR_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
def call(name, args):
    return execute_tool(name, json.dumps(args))
def run():
    n = 0
    for a in call(S + "find_actors", {"name": "", "tag": DATA, "collision_channels": []})["returnValue"]:
        if call(A + "has_tag", {"actor": a, "tag": DATA})["returnValue"]:
            call(S + "remove_from_scene", {"actor": a})
            n += 1
    return {"removed": n}
"""


_COUNT_JOB = """
A = "editor_toolset.toolsets.actor.ActorTools."
def run():
    found = execute_tool("editor_toolset.toolsets.scene.SceneTools.find_actors",
                         json.dumps({"name": "", "tag": DATA, "collision_channels": []}))["returnValue"]
    return {"n": sum(1 for a in found if execute_tool(A + "has_tag", json.dumps({"actor": a, "tag": DATA}))["returnValue"])}
"""


def clear():
    """Removes everything place() put into the open test map (found by tag, nothing else)."""
    level, err = _guard()
    if err:
        return err.replace("NOT PLACED", "NOT CLEARED")
    n = ue.batch(_CLEAR_JOB, TOWN_TAG)["removed"]
    kit.log_action("clear_town", level=level, removed=n)
    return f"removed {n} actor(s) that ue-kit had placed as a town"
