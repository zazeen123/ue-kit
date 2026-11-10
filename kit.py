"""Geometry for ue-kit: mesh bounds (cached), relative placement -> transforms, and sanity checks.

Units are centimetres, Z up, yaw in degrees (Unreal conventions). No Unreal import: bounds come from the
editor through ue_client and are cached in bounds_cache.json next to this file.
"""
import json
import math
import os
import re
import time

import ue_client as ue

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "bounds_cache.json")
CONTENT = r"U:\ue\MyHeadLine\Content"
SIDES = ("+X", "-X", "+Y", "-Y")
OUT = r"C:\UE\logs\ue-kit"
ACTIONS = os.path.join(OUT, "actions.log")

# Where ue-kit may change things. Test copies, probes and deletions only ever happen in a test map; a
# Blueprint may only be created under SANDBOX, or rebuilt where ue-kit itself built that name before.
TEST_MAPS = ("L_GatefallTown_Preview", "/_Sandbox/", "L_TownDressTest")
SANDBOX = "/Game/ARPG/_Sandbox"
TEST_SUFFIX = "_Test"
KIT_TAG = "ue-kit"
S_ = "editor_toolset.toolsets.scene.SceneTools"


class NotMeasured(ValueError):
    """Doorway data for a mesh is not in the cache and may not be measured right now."""


# ---------------------------------------------------------------- state files, log, guards

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    """Write through a temp file: two servers (Hermes + Claude) may share these files."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=0, ensure_ascii=False)
    os.replace(tmp, path)


def log_action(action, **info):
    """One JSON line per thing ue-kit changed in the editor (built, deleted, measured)."""
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(ACTIONS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **info},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def current_level():
    return ue.call(S_, "get_current_level", {}).get("returnValue") or ""


def in_test_map(level):
    return any(k in level for k in TEST_MAPS)


def _mesh_mtime(path):
    """Modification time of the mesh's .uasset (None if it is not a file under CONTENT)."""
    rel = path.split(".")[0]
    if not rel.startswith("/Game/"):
        return None
    try:
        return int(os.path.getmtime(os.path.join(CONTENT, rel[6:].replace("/", os.sep) + ".uasset")))
    except OSError:
        return None


def _fresh_entries(cache, paths):
    """Drops cache entries whose .uasset changed since they were measured. Entries from before mtimes were
    recorded are trusted once and stamped. Returns True if the cache dict was modified."""
    mt = cache.setdefault("__mtime__", {})
    dirty = False
    for p in dict.fromkeys(paths):
        now = _mesh_mtime(p)
        if p not in cache or now is None:
            continue
        if p not in mt:
            mt[p] = now
            dirty = True
        elif mt[p] != now:
            del cache[p]
            del mt[p]
            dirty = True
    return dirty


# ---------------------------------------------------------------- bounds

def _load_cache():
    return _read_json(CACHE)


def full_path(mesh):
    """'/Game/A/SM_X' or '/Game/A/SM_X.SM_X' or 'SM_X' (FantasyBundle) -> '/Game/A/SM_X.SM_X'."""
    if not mesh.startswith("/"):
        mesh = "/Game/FantasyBundle/Meshes/" + mesh
    if "." not in mesh.rsplit("/", 1)[-1]:
        mesh = mesh + "." + mesh.rsplit("/", 1)[-1]
    return mesh


_BOUNDS_JOB = """
def run():
    out = {}
    for p in DATA:
        try:
            r = execute_tool("editor_toolset.toolsets.static_mesh.StaticMeshTools.get_bounds",
                             json.dumps({"mesh": {"refPath": p}}))["returnValue"]
            out[p] = [r["min"]["x"], r["min"]["y"], r["min"]["z"], r["max"]["x"], r["max"]["y"], r["max"]["z"]]
        except Exception as e:
            out[p] = "ERROR " + str(e)[:120]
    return out
"""


def bounds(meshes):
    """{full_path: [minx,miny,minz,maxx,maxy,maxz]} for every mesh, measuring the unknown ones in the editor."""
    cache = _load_cache()
    paths = [full_path(m) for m in meshes]
    dirty = _fresh_entries(cache, paths)
    missing = [p for p in dict.fromkeys(paths) if p not in cache]
    if missing:
        try:
            got = ue.batch(_BOUNDS_JOB, missing)       # read-only in the editor
        except ue.UEError as e:
            raise ValueError("cannot measure " + ", ".join(p.rsplit("/", 1)[-1].split(".")[0] for p in missing)
                             + f" - check the mesh name with kit_parts ({str(e)[:160]})")
        bad = {k: v for k, v in got.items() if isinstance(v, str)}
        if bad:
            raise ValueError("cannot measure: " + "; ".join(f"{k}: {v}" for k, v in bad.items()))
        cache.update({k: [round(x, 1) for x in v] for k, v in got.items()})
        for k in got:
            t = _mesh_mtime(k)
            if t is not None:
                cache["__mtime__"][k] = t
        dirty = True
    if dirty:
        _write_json(CACHE, cache)
    return {p: cache[p] for p in paths}


def list_meshes(folder="/Game/FantasyBundle/Meshes", query=""):
    """Static-mesh-looking assets (SM_*) under a content folder whose name matches query (regex, any case)."""
    root = os.path.join(CONTENT, folder.replace("/Game/", "").replace("/", os.sep))
    rx = re.compile(query or ".", re.I)
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.startswith("SM_") and f.endswith(".uasset") and rx.search(f[:-7]):
                rel = os.path.relpath(os.path.join(dirpath, f[:-7]), CONTENT).replace(os.sep, "/")
                out.append(full_path("/Game/" + rel))
    return sorted(out)


def pivot_note(b):
    """Where the pivot sits in the mesh, in words (the usual source of placement mistakes)."""
    def axis(lo, hi, name):
        if abs(lo) < 2:
            return f"{name}: pivot at min side (0..{hi:.0f})"
        if abs(hi) < 2:
            return f"{name}: pivot at max side ({lo:.0f}..0)"
        if abs(lo + hi) < 0.1 * (hi - lo) + 2:
            return f"{name}: centred"
        return f"{name}: {lo:.0f}..{hi:.0f}"
    return "; ".join(axis(b[i], b[i + 3], n) for i, n in enumerate("XYZ"))


# ---------------------------------------------------------------- openings (doorways) by line traces

OPEN_CACHE = os.path.join(HERE, "openings_cache.json")

_OPEN_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
def call(name, args):
    return execute_tool(name, json.dumps(args))
def run():
    X, Y, Z = 45000, 45000, DATA["z"]     # far from everything and high above any ground
    # the spot must be empty, or whatever stands there would be recorded as walls
    if call(S + "trace_world", {"start": {"x": X, "y": Y, "z": Z + 6000},
                                "end": {"x": X, "y": Y, "z": Z - 1000}})["returnValue"] is not None:
        return {"error": "the probe spot is not empty"}
    out = {}
    for mesh, b in DATA["meshes"].items():
        a = call(S + "add_to_scene_from_asset", {"asset_path": mesh.split(".")[0], "name": "UEKitProbe",
                "xform": {"location": {"x": X, "y": Y, "z": Z}, "rotation": {"pitch": 0, "yaw": 0, "roll": 0},
                          "scale": {"x": 1, "y": 1, "z": 1}}})["returnValue"]
        res = {}
        try:
            for side in ("+X", "-X", "+Y", "-Y"):
                ax = 0 if side[1] == "X" else 1
                sgn = 1 if side[0] == "+" else -1
                face = b[3 + ax] if sgn > 0 else b[ax]
                mid = (b[ax] + b[3 + ax]) / 2
                o = 1 - ax                       # the axis along the face
                lo, hi = b[o], b[3 + o]
                z = Z + b[2] + 110
                free = []
                t = lo + 10
                while t <= hi - 10:
                    st = [0, 0, z]; en = [0, 0, z]
                    st[ax] = face + sgn * 100; en[ax] = mid
                    st[o] = t; en[o] = t
                    d = call(S + "trace_world", {"start": {"x": X + st[0], "y": Y + st[1], "z": st[2]},
                                                 "end": {"x": X + en[0], "y": Y + en[1], "z": en[2]}})["returnValue"]
                    # passes the wall: no hit, or first hit well inside the face
                    free.append(d is None or d > 100 + 60)
                    t += 10
                spans, start = [], None
                for i, f in enumerate(free + [False]):
                    tt = lo + 10 + i * 10
                    if f and start is None:
                        start = tt
                    if not f and start is not None:
                        if tt - 10 - start >= 60:          # at least 70 cm wide
                            spans.append([start - 5, tt - 5])
                        start = None
                res[side] = spans
        finally:
            call(S + "remove_from_scene", {"actor": a})
        out[mesh] = res
    return out
"""


PROBE_Z = 100000.0      # 1 km up: nothing of the level is there, whatever map is open


def openings(meshes, measure=False):
    """{mesh: {side: [[from, to], ...]}} - door-height (110 cm above the mesh bottom) gaps through each face,
    in the mesh's own frame, found with line traces in the editor (cached).

    Measuring spawns a probe actor for a moment, so it only happens with measure=True AND a test map open;
    otherwise a mesh that is not in the cache raises NotMeasured (a dry run never touches the level)."""
    cache = _read_json(OPEN_CACHE)
    paths = [full_path(m) for m in meshes]
    dirty = _fresh_entries(cache, paths)
    missing = [p for p in dict.fromkeys(paths) if p not in cache]
    if missing:
        names = ", ".join(p.rsplit("/", 1)[-1].split(".")[0] for p in missing)
        if dirty:
            _write_json(OPEN_CACHE, cache)
        if not measure:
            raise NotMeasured(f"doorway data for {names} is not measured yet")
        level = current_level()
        if not in_test_map(level):
            raise NotMeasured(f"doorway data for {names} is not measured yet and the open level ({level}) is not a "
                              f"test map, so it cannot be measured now")
        bm = bounds(missing)
        got = ue.batch(_OPEN_JOB, {"meshes": {p: bm[p] for p in missing}, "z": PROBE_Z})
        if "error" in got:
            raise NotMeasured(f"doorway data for {names} could not be measured: {got['error']}")
        cache.update(got)
        for p in got:
            t = _mesh_mtime(p)
            if t is not None:
                cache["__mtime__"][p] = t
        _write_json(OPEN_CACHE, cache)
        log_action("probe", level=level, meshes=sorted(got))
    elif dirty:
        _write_json(OPEN_CACHE, cache)
    return {p: cache[p] for p in paths}


def opening_note(o):
    parts = [f"{s} {', '.join(f'{a:.0f}..{b:.0f}' for a, b in spans)}" for s, spans in o.items() if spans]
    return "doorways: " + ("; ".join(parts) if parts else "none")


# ---------------------------------------------------------------- placement

def _rot_matrix(pitch, yaw, roll):
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    # Unreal FRotationMatrix rows = world directions of local X, Y, Z
    return ((cp * cy, cp * sy, sp),
            (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
            (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp))


def local_box(b, scale, rot):
    """Axis-aligned box (relative to the pivot) of a mesh with bounds b after scale and rotation."""
    m = _rot_matrix(*rot)
    xs, ys, zs = [], [], []
    for x in (b[0], b[3]):
        for y in (b[1], b[4]):
            for z in (b[2], b[5]):
                lx, ly, lz = x * scale[0], y * scale[1], z * scale[2]
                xs.append(lx * m[0][0] + ly * m[1][0] + lz * m[2][0])
                ys.append(lx * m[0][1] + ly * m[1][1] + lz * m[2][1])
                zs.append(lx * m[0][2] + ly * m[1][2] + lz * m[2][2])
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def _vec(v, default):
    if v is None:
        return list(default)
    if isinstance(v, (int, float)):
        return [float(v)] * 3
    return [float(x) for x in v] + [default[i] for i in range(len(v), 3)]


def _ref(done, ref_name, who):
    """An earlier part, or several joined with '+' (their combined box)."""
    names = [n.strip() for n in ref_name.split("+")]
    missing = [n for n in names if n not in done]
    if missing:
        raise ValueError(f"{who}: refers to {', '.join(missing)}, which is not an earlier part")
    boxes = [done[n]["box"] for n in names]
    return {"box": [min(b[i] for b in boxes) for i in range(3)] + [max(b[i] for b in boxes) for i in range(3, 6)]}


def resolve(parts):
    """Turns relative part specs into transforms. Returns a list of dicts with
    name, mesh, loc, rot (pitch,yaw,roll), scale and box (world AABB [minx,miny,minz,maxx,maxy,maxz]).
    A reference may name several earlier parts joined with '+' ("on:WingA+WingB", "cover": "WingA+WingB")."""
    bmap = bounds([p["mesh"] for p in parts if not p.get("light")])
    done = {}
    out = []
    for p in parts:
        name = p["name"]
        if name in done:
            raise ValueError(f"duplicate part name {name}")
        if p.get("light"):            # a point light: a small box so it can be placed like a part
            mesh, b = "", [-10.0, -10.0, -10.0, 10.0, 10.0, 10.0]
        else:
            mesh = full_path(p["mesh"])
            b = bmap[mesh]
        rot = (float(p.get("pitch", 0)), float(p.get("yaw", 0)), float(p.get("roll", 0)))
        scale = _vec(p.get("scale"), (1, 1, 1))
        off = _vec(p.get("offset"), (0, 0, 0))

        cover = p.get("cover")
        if cover:
            ref_name, _, margin = cover.partition(":")
            ref = _ref(done, ref_name, f"{name} cover")
            margin = float(margin or 40)
            lb = local_box(b, (1, 1, 1), rot)
            need_x = (ref["box"][3] - ref["box"][0]) + 2 * margin
            need_y = (ref["box"][4] - ref["box"][1]) + 2 * margin
            fx, fy = need_x / (lb[3] - lb[0]), need_y / (lb[4] - lb[1])
            # express the world-axis factors in the mesh's own axes (yaw multiples of 90 only)
            if round(rot[1] / 90) % 2:
                fx, fy = fy, fx
            if p.get("scale") is None:
                scale = [fx, fy, max(0.7, min(1.6, (fx + fy) / 2))]
            else:
                scale = [fx, fy, scale[2]]

        box = local_box(b, scale, rot)
        cx, cy = (box[0] + box[3]) / 2, (box[1] + box[4]) / 2
        place = p.get("place", "ground")
        kind, _, rest = place.partition(":")
        if kind == "at":
            loc = off
        elif kind == "ground":
            loc = [off[0] - cx, off[1] - cy, -box[2] + off[2]]
        else:
            ref_name, _, side = rest.partition(":")
            r = _ref(done, ref_name, f"{name} '{place}'")["box"]
            rcx, rcy = (r[0] + r[3]) / 2, (r[1] + r[4]) / 2
            if kind == "on":
                loc = [rcx - cx + off[0], rcy - cy + off[1], r[5] - box[2] + off[2]]
            elif kind == "inside":
                # on the floor of a module's interior, centred unless offset (a counter, shelf, crate, lamp)
                loc = [rcx - cx + off[0], rcy - cy + off[1], r[2] - box[2] + off[2]]
            elif kind in ("against", "flush"):
                if side not in SIDES:
                    raise ValueError(f"{name}: side must be one of {SIDES}, got {side!r}")
                loc = [rcx - cx + off[0], rcy - cy + off[1], r[2] - box[2] + off[2]]
                ax = 0 if side[1] == "X" else 1
                if side[0] == "+":
                    face = r[3 + ax]
                    loc[ax] = (face - box[ax] if kind == "against" else face - box[3 + ax]) + off[ax]
                else:
                    face = r[ax]
                    loc[ax] = (face - box[3 + ax] if kind == "against" else face - box[ax]) + off[ax]
            else:
                raise ValueError(f"{name}: unknown place {place!r} (ground | at | on:P | inside:P | against:P:side | flush:P:side)")
        world = [box[i] + loc[i % 3] for i in range(6)]
        d = dict(name=name, mesh=mesh, loc=[round(v, 1) for v in loc], rot=list(rot),
                 scale=[round(v, 4) for v in scale], box=[round(v, 1) for v in world], place=place)
        if p.get("light"):
            d["light"] = p["light"]
        done[name] = d
        out.append(d)
    return out


# ---------------------------------------------------------------- checks

def _overlap_xy(a, b, tol=1.0):
    return a[0] < b[3] - tol and b[0] < a[3] - tol and a[1] < b[4] - tol and b[1] < a[4] - tol


SHELL = re.compile(r"floor|wall|storey|base|plinth|body", re.I)
SHELL_MESH = re.compile(r"Floor|Wall|Base|Storey", re.I)
SMALL = re.compile(r"door|window|chimney|bracket|step|stair|sign|lamp|torch|post|beam|frame|gate", re.I)


def is_shell(p):
    """A wall/floor module - by the part's name or by its mesh name (a module stays a module whatever it is
    called). Roofs and small attachments are not."""
    mesh = p["mesh"].rsplit("/", 1)[-1].split(".")[0]
    if "roof" in p["name"].lower() or "Roof" in mesh or SMALL.search(p["name"]):
        return False
    return bool(SHELL.search(p["name"]) or SHELL_MESH.search(mesh.replace("SM_", "")))


WALK_IN = re.compile(r"House\w*Floor", re.I)      # modules a player walks into: these need a door


class Issues(list):
    """The issue texts, plus .fixes for the ones with a single mechanical remedy (see autofix)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.fixes = []


def autofix(parts, rounds=4):
    """Applies the fixes that have only one answer - a roof that does not cover its walls gets `cover`, a part
    a little above its support is set down, a sunk part is raised, steps are shortened to the door sill or
    removed when the sill is at ground level - and re-checks, up to `rounds` times.
    Returns (new parts, notes). Everything else (overlaps, overhangs, doors in solid walls, stretching) needs
    a design decision and is left alone."""
    parts = json.loads(json.dumps(parts))
    notes = []
    for _ in range(rounds):
        fixes = check(resolve(parts)).fixes
        if not fixes:
            break
        by = {p["name"]: p for p in parts}
        done = set()
        for op, name, val in fixes:
            p = by.get(name)
            if p is None or (op, name) in done:
                continue
            done.add((op, name))
            if op in ("raise", "lower"):
                off = _vec(p.get("offset"), (0, 0, 0))
                off[2] = round(off[2] + (val if op == "raise" else -val), 1)
                p["offset"] = off
                notes.append(f"{name}: moved {'up' if op == 'raise' else 'down'} {val:.0f} cm (offset z = {off[2]:.0f})")
            elif op == "cover":
                order = [q["name"] for q in parts]
                if order.index(val) > order.index(name):
                    continue                        # a part can only refer to an earlier one
                old, _, margin = (p.get("cover") or "").partition(":")
                names = [n for n in old.split("+") if n]
                for _op, _n, v in fixes:            # every wall this roof misses, in one go
                    if _op == "cover" and _n == name and v not in names and order.index(v) < order.index(name):
                        names.append(v)
                p["cover"] = "+".join(sorted(names, key=order.index)) + ":" + (margin or "40")
                if isinstance(p.get("scale"), (int, float)):
                    p.pop("scale")
                notes.append(f"{name}: cover = \"{p['cover']}\" (scaled to overhang the walls)")
            elif op == "scale_z":
                sc = _vec(p.get("scale"), (1, 1, 1))
                sc[2] = round(sc[2] * val, 3)
                p["scale"] = sc
                notes.append(f"{name}: scale z = {sc[2]} (top now meets the door sill)")
            elif op == "remove":
                if any(name in re.split(r"[:+]", str(q.get(k, ""))) for q in parts for k in ("place", "cover")):
                    continue
                parts.remove(p)
                notes.append(f"{name}: removed (the door sill is at ground level)")
    return parts, notes


def check(resolved, measure=False):
    """Problems a human would see in a picture, found from the boxes. Returns a list of strings.
    measure=True lets the doorway checks measure a mesh that is not cached yet (test map only); otherwise
    such a mesh gives one note saying how to get it measured."""
    resolved = [p for p in resolved if not p.get("light")]
    issues = Issues()
    fix = issues.fixes.append        # (op, part, value): the problems that have exactly one remedy
    unmeasured = []

    def _openings(mesh):
        try:
            return openings([mesh], measure)[mesh]
        except NotMeasured:
            n = mesh.rsplit("/", 1)[-1].split(".")[0]
            if n not in unmeasured:
                unmeasured.append(n)
            return None
    for p in resolved:
        b = p["box"]
        bottom = b[2]
        if bottom < -10:
            issues.append(f"SUNK: {p['name']} goes {-bottom:.0f} cm below the ground")
            fix(("raise", p["name"], -bottom))
            continue
        if bottom <= 5:
            continue
        supported = [q["name"] for q in resolved if q is not p and _overlap_xy(b, q["box"], -3)
                     and q["box"][2] - 5 <= bottom <= q["box"][5] + 5]
        if not supported:
            below = [q for q in resolved if q is not p and _overlap_xy(b, q["box"]) and q["box"][5] < bottom]
            top = max([q["box"][5] for q in below], default=0.0)
            what = max(below, key=lambda q: q["box"][5])["name"] if below else "the ground"
            issues.append(f"FLOATING: {p['name']} bottom is {bottom - top:.0f} cm above {what}")
            if below and bottom - top <= 60:          # a small gap over a real support: set it down
                fix(("lower", p["name"], bottom - top))
    shells = [p for p in resolved if is_shell(p)]
    side_roof = re.compile(r"porch|awning|canopy|lean", re.I)
    for r in (p for p in resolved if "roof" in p["name"].lower() and not side_roof.search(p["name"])):
        rb = r["box"]
        # the walls this roof sits on: overlapping it in plan, with their top close to the roof's bottom
        under = [s for s in shells if _overlap_xy(rb, s["box"], 20) and abs(s["box"][5] - rb[2]) <= 60]
        for s in under:
            sb = s["box"]
            short = []
            for i, side in ((0, "-X"), (1, "-Y")):
                if rb[i] > sb[i] + 5:
                    short.append(f"{side} by {rb[i] - sb[i]:.0f} cm")
            for i, side in ((3, "+X"), (4, "+Y")):
                if rb[i] < sb[i] - 5:
                    short.append(f"{side} by {sb[i] - rb[i]:.0f} cm")
            if short:
                issues.append(f"ROOF TOO SMALL: {r['name']} does not cover {s['name']} on " + ", ".join(short)
                              + " (use cover:" + s["name"] + ")")
                fix(("cover", r["name"], s["name"]))
        below = [s for s in shells if _overlap_xy(rb, s["box"], 20) and s["box"][5] <= rb[2] + 60]
        if below:
            top = max(s["box"][5] for s in below)
            if rb[2] > top + 15:
                issues.append(f"FLOATING ROOF: {r['name']} starts {rb[2] - top:.0f} cm above the walls under it")
                fix(("lower", r["name"], rb[2] - top))
        elif shells:
            issues.append(f"FLOATING ROOF: {r['name']} has no walls/floors under it (name wall parts *Floor/*Wall)")
    # Two big parts filling the same space (e.g. an "upper" module left on the ground inside the ground floor).
    big = [p for p in resolved if is_shell(p)]
    for i, a in enumerate(big):
        for c in big[i + 1:]:
            A, C = a["box"], c["box"]
            ix = [max(0.0, min(A[3 + k], C[3 + k]) - max(A[k], C[k])) for k in range(3)]
            inter = ix[0] * ix[1] * ix[2]
            va = (A[3] - A[0]) * (A[4] - A[1]) * (A[5] - A[2])
            vc = (C[3] - C[0]) * (C[4] - C[1]) * (C[5] - C[2])
            if inter > 0.25 * min(va, vc):
                issues.append(f"OVERLAP: {a['name']} and {c['name']} fill the same space "
                              f"({100 * inter / min(va, vc):.0f}% of the smaller) - one of them needs a place "
                              f"(on:/against:) so it sits next to or on top of the other")
    # Props through walls (a fence across the house) and small parts on top of each other (a sign on the door).
    attach = re.compile(r"door|window|frame|gate|chimney|bracket|beam|post|support|step|stair", re.I)
    def vol(b):
        return max(0.0, b[3] - b[0]) * max(0.0, b[4] - b[1]) * max(0.0, b[5] - b[2])
    def inter(a, c):
        return vol([max(a[0], c[0]), max(a[1], c[1]), max(a[2], c[2]), min(a[3], c[3]), min(a[4], c[4]), min(a[5], c[5])])
    props = [p for p in resolved if not is_shell(p) and "roof" not in p["name"].lower()]
    for p in props:
        if attach.search(p["name"]):
            continue
        pb = p["box"]
        for sh in big:
            sb = sh["box"]
            if not inter(pb, sb):
                continue                      # fully outside: fine
            core = [sb[0] + 25, sb[1] + 25, sb[2] - 5, sb[3] - 25, sb[4] - 25, sb[5] + 5]
            inside = all(pb[k] >= core[k] for k in range(3)) and all(pb[3 + k] <= core[3 + k] for k in range(3))
            if inside:
                continue                      # an interior prop: fine
            # crosses a wall line: in XY it is partly within the module and partly beyond it
            if inter(pb, sb) > 0.15 * vol(pb):
                issues.append(f"THROUGH WALL: {p['name']} crosses a wall of {sh['name']} - put it fully inside "
                              f"(inside:{sh['name']}) or fully outside (against:{sh['name']}:<side>)")
                break
    # A canopy's box is the whole space under it: goods standing there do not clash with it.
    hollow = re.compile(r"canopy|awning|tent|pavilion|shelter|parasol|umbrella|pergola", re.I)
    for i, a in enumerate(props):
        for c in props[i + 1:]:
            if any(hollow.search(q["name"]) or hollow.search(q["mesh"].rsplit("/", 1)[-1]) for q in (a, c)):
                continue
            m = min(vol(a["box"]), vol(c["box"]))
            if m and inter(a["box"], c["box"]) > 0.5 * m:
                issues.append(f"CLASH: {a['name']} and {c['name']} occupy the same spot - move one of them")
    # Stretched modules: textures and timber frames smear when a wall/floor is scaled far from 1.
    for p in resolved:
        if is_shell(p):
            sx, sy, sz = p["scale"]
            bad = [f"{a} {v:.2f}" for a, v in (("X", sx), ("Y", sy), ("Z", sz)) if not 0.85 <= abs(v) <= 1.2]
            if bad:
                issues.append(f"STRETCHED: {p['name']} is scaled {', '.join(bad)} - its texture and timber frame "
                              f"will smear; keep walls/floors at 0.85-1.2 and put two modules side by side instead")
    # Overhangs and ledges between a part and what it rests on.
    for p in resolved:
        b = p["box"]
        low = p["name"].lower()
        if b[2] <= 5 or any(k in low for k in ("roof", "chimney", "bracket", "door", "window", "step", "sign")):
            continue
        sup = [q for q in resolved if q is not p and _overlap_xy(b, q["box"]) and abs(q["box"][5] - b[2]) <= 15
               and not any(k in q["name"].lower() for k in ("roof", "door", "window", "step"))]
        if not sup:
            continue
        s = [min(q["box"][0] for q in sup), min(q["box"][1] for q in sup),
             max(q["box"][3] for q in sup), max(q["box"][4] for q in sup)]
        names = "+".join(q["name"] for q in sup)
        out = {"-X": s[0] - b[0], "-Y": s[1] - b[1], "+X": b[3] - s[2], "+Y": b[4] - s[3]}
        big = {k: v for k, v in out.items() if v > 75}
        if big:
            issues.append(f"OVERHANG: {p['name']} sticks out past {names} by "
                          + ", ".join(f"{v:.0f} cm on {k}" for k, v in big.items())
                          + " - it hangs in the air there; use a wider support or a narrower part")
        if is_shell(p):
            # siblings resting on the same support at the same height count together (two modules side by side)
            sib = [q for q in resolved if is_shell(q) and abs(q["box"][2] - b[2]) <= 15
                   and any(_overlap_xy(q["box"], t["box"]) for t in sup)]
            u = [min(q["box"][0] for q in sib), min(q["box"][1] for q in sib),
                 max(q["box"][3] for q in sib), max(q["box"][4] for q in sib)]
            uo = {"-X": s[0] - u[0], "-Y": s[1] - u[1], "+X": u[2] - s[2], "+Y": u[3] - s[3]}
            ledge = {k: -v for k, v in uo.items() if -v > 75}
            if ledge:
                issues.append(f"LEDGE: {names} is wider than {'+'.join(q['name'] for q in sib)} by "
                              + ", ".join(f"{v:.0f} cm on {k}" for k, v in ledge.items())
                              + " - its top is left bare; use matching sizes (or two modules side by side)")
    doors = [p for p in resolved if "door" in p["name"].lower() and "frame" not in p["name"].lower()]
    rooms = [p["name"] for p in resolved if WALK_IN.search(p["mesh"].rsplit("/", 1)[-1])]
    if not doors and rooms:         # a stall, a wall section or a prop group needs no door
        issues.append(f"NO DOOR: {rooms[0]} is a walk-in module but no part is named *door* (a house needs a way in)")
    # Steps must end at a door sill, not run up the wall past it.
    for st in (p for p in resolved if "step" in p["name"].lower() or "stair" in p["name"].lower()):
        near = sorted(doors, key=lambda d: math.dist(((d["box"][0] + d["box"][3]) / 2, (d["box"][1] + d["box"][4]) / 2),
                                                    ((st["box"][0] + st["box"][3]) / 2, (st["box"][1] + st["box"][4]) / 2)))
        if near:
            sill = near[0]["box"][2]
            if sill <= 5:
                issues.append(f"STEPS NOT NEEDED: {st['name']} leads to {near[0]['name']}, whose sill is at ground "
                              f"level - remove the steps (they only block the doorway)")
                fix(("remove", st["name"], 0))
            elif st["box"][5] > sill + 30:
                issues.append(f"STEPS TOO TALL: {st['name']} rises to {st['box'][5]:.0f} cm but {near[0]['name']}'s "
                              f"sill is at {sill:.0f} cm - scale its Z so the top meets the sill")
                if st["box"][5] - st["box"][2] > 1 and sill - st["box"][2] > 5:
                    fix(("scale_z", st["name"], (sill - st["box"][2]) / (st["box"][5] - st["box"][2])))
    # Doorways on upper storeys open into thin air.
    for p in resolved:
        if not is_shell(p) or p["box"][2] < 150:
            continue
        try:
            op = _openings(p["mesh"])
        except Exception:
            continue
        if op is None:
            continue
        for lside, spans in op.items():
            if not spans:
                continue
            nx, ny = {"+X": (1, 0), "-X": (-1, 0), "+Y": (0, 1), "-Y": (0, -1)}[lside]
            yaw = math.radians(p["rot"][1])
            wx, wy = nx * math.cos(yaw) - ny * math.sin(yaw), nx * math.sin(yaw) + ny * math.cos(yaw)
            wside = ("+X" if wx > 0 else "-X") if abs(wx) > abs(wy) else ("+Y" if wy > 0 else "-Y")
            issues.append(f"DOORWAY IN THE AIR: {p['name']} ({p['mesh'].rsplit('/', 1)[-1].split('.')[0]}) has a "
                          f"doorway on its {wside} face {p['box'][2]:.0f} cm up - use a module without doorways for "
                          f"upper storeys (kit_parts doorways=True shows which have none)")
    for d in doors:
        kind, _, rest = d.get("place", "").partition(":")
        host_name, _, side = rest.partition(":")
        host = next((q for q in resolved if q["name"] == host_name), None)
        if kind not in ("flush", "against") or not host:
            continue
        try:
            op = _openings(host["mesh"])
        except Exception as e:      # editor busy / not open: skip this check, say so
            issues.append(f"(door check skipped: {e})")
            continue
        if op is None:
            continue
        # door centre in the host's own frame (undo the host's yaw, location and scale)
        cx, cy = (d["box"][0] + d["box"][3]) / 2, (d["box"][1] + d["box"][4]) / 2
        yaw = math.radians(host["rot"][1])
        dx, dy = cx - host["loc"][0], cy - host["loc"][1]
        lx = (dx * math.cos(-yaw) - dy * math.sin(-yaw)) / host["scale"][0]
        ly = (dx * math.sin(-yaw) + dy * math.cos(-yaw)) / host["scale"][1]
        hb = bounds([host["mesh"]])[host["mesh"]]
        dist = {"+X": abs(lx - hb[3]), "-X": abs(lx - hb[0]), "+Y": abs(ly - hb[4]), "-Y": abs(ly - hb[1])}
        lside = min(dist, key=dist.get)
        along = ly if lside[1] == "X" else lx
        spans = op.get(lside, [])
        if not any(a - 15 <= along <= b + 15 for a, b in spans):
            where = opening_note(op)
            issues.append(f"DOOR IN SOLID WALL: {d['name']} is on {host_name}'s own {lside} face at {along:.0f}, "
                          f"but {host_name} ({host['mesh'].rsplit('/', 1)[-1].split('.')[0]}) has {where}. "
                          f"Put the door on a doorway side, or turn {host_name} with yaw so its doorway faces {side}.")
    if unmeasured:
        issues.append("DOORWAYS NOT MEASURED: " + ", ".join(unmeasured) + " - the door checks were skipped for "
                      "these. With a test map open call kit_parts(\"" + "|".join(unmeasured) + "\", doorways=True), "
                      "then check again")
    return issues


def table(resolved):
    lines = ["part | mesh | location | yaw | scale | world box min -> max (cm)"]
    for p in resolved:
        b = p["box"]
        lines.append(f"{p['name']} | {p['mesh'].rsplit('/', 1)[-1].split('.')[0]} | "
                     f"({p['loc'][0]:.0f}, {p['loc'][1]:.0f}, {p['loc'][2]:.0f}) | {p['rot'][1]:.0f} | "
                     f"{'/'.join(f'{s:.2f}' for s in p['scale'])} | "
                     f"({b[0]:.0f}, {b[1]:.0f}, {b[2]:.0f}) -> ({b[3]:.0f}, {b[4]:.0f}, {b[5]:.0f})")
    return "\n".join(lines)


# ---------------------------------------------------------------- test spots

SPOTS = os.path.join(HERE, "test_spots.json")


def test_spot(name, given=None):
    """A fixed spot per Blueprint name on a grid south of the town (12 per row, 18 m apart), unless given."""
    if given:
        return [float(v) for v in given]
    spots = _read_json(SPOTS)
    if name not in spots:
        spots[name] = max(spots.values(), default=-1) + 1
        _write_json(SPOTS, spots)
    i = spots[name]
    return [-12000.0 + (i % 12) * 1800.0, -22000.0 - (i // 12) * 2200.0, 0.0]


# ---------------------------------------------------------------- traced checks on the built copy

_TRACE_JOB = """
def run():
    out = []
    for q in DATA:
        d = execute_tool("editor_toolset.toolsets.scene.SceneTools.trace_world", json.dumps(
            {"start": {"x": q[0], "y": q[1], "z": q[2]}, "end": {"x": q[0], "y": q[1], "z": q[3]}}))["returnValue"]
        out.append(d)
    return {"d": out}
"""


_SEG_JOB = """
def run():
    out = []
    for q in DATA:
        out.append(execute_tool("editor_toolset.toolsets.scene.SceneTools.trace_world", json.dumps(
            {"start": {"x": q[0], "y": q[1], "z": q[2]}, "end": {"x": q[3], "y": q[4], "z": q[5]}}))["returnValue"])
    return {"d": out}
"""


def post_build(resolved, at):
    """Small parts set on top of something (chimneys, vents, signs on roofs): trace the real surface just
    beside them on four sides; if the part's bottom is above the lowest of those surfaces, it visibly hovers."""
    resolved = [p for p in resolved if not p.get("light")]
    issues = []
    jobs = []
    for p in resolved:
        b = p["box"]
        kind, _, rest = p.get("place", "").partition(":")
        if kind != "on" or b[2] < 50:
            continue
        sup = _ref({q["name"]: q for q in resolved}, rest.split(":")[0], p["name"])["box"]
        # only parts clearly inside their support's footprint (a chimney on a roof, not a floor on a floor)
        if not (b[0] > sup[0] + 15 and b[1] > sup[1] + 15 and b[3] < sup[3] - 15 and b[4] < sup[4] - 15):
            continue
        cx, cy = (b[0] + b[3]) / 2 + at[0], (b[1] + b[4]) / 2 + at[1]
        hx, hy = (b[3] - b[0]) / 2 + 20, (b[4] - b[1]) / 2 + 20
        top = max(q["box"][5] for q in resolved) + at[2] + 300   # above everything, roofs included
        for dx, dy in ((hx, 0), (-hx, 0), (0, hy), (0, -hy)):
            jobs.append((p["name"], b[2] + at[2], [cx + dx, cy + dy, top, b[2] + at[2] - 2000]))
    # A door must be reachable: trace from 1.5 m outside straight at its middle; anything hit well before the
    # door's own face means a wall or prop stands in front of it.
    door_jobs = []
    for d in resolved:
        if "door" not in d["name"].lower() and "gate" not in d["mesh"].lower():
            continue
        kind, _, rest = d.get("place", "").partition(":")
        side = rest.rpartition(":")[2]
        if kind not in ("flush", "against") or side not in SIDES:
            continue
        b = d["box"]
        ax = 0 if side[1] == "X" else 1
        sgn = 1 if side[0] == "+" else -1
        face = b[3 + ax] if sgn > 0 else b[ax]
        mid = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[2] + min(150.0, (b[5] - b[2]) / 2)]
        start = list(mid); start[ax] = face + sgn * 150
        end = list(mid); end[ax] = face - sgn * 5
        door_jobs.append((d["name"], start, end))
    if door_jobs:
        got = ue.batch(_SEG_JOB, [[s0[0] + at[0], s0[1] + at[1], s0[2] + at[2], e[0] + at[0], e[1] + at[1], e[2] + at[2]]
                                  for _, s0, e in door_jobs])["d"]
        for (dn, _, _), dist in zip(door_jobs, got):
            if dist is not None and dist < 120:
                issues.append(f"DOOR BLOCKED: something stands {150 - dist:.0f} cm in front of {dn} - "
                              f"remove the wall piece/prop in front of it, or move the door to an open side")
    # WALK-IN: a player (about 70 cm wide, 180 tall) must get through the doorway and 1.2 m into the room.
    walk = []
    for d in resolved:
        if "door" not in d["name"].lower() and "entrance" not in d["name"].lower():
            continue
        kind, _, rest = d.get("place", "").partition(":")
        host_name = rest.split(":")[0]
        host = next((q for q in resolved if q["name"] == host_name), None)
        if kind not in ("flush", "against") or not host:
            continue
        try:
            op = openings([host["mesh"]])[host["mesh"]]
        except Exception:
            continue
        hb = bounds([host["mesh"]])[host["mesh"]]
        yaw = math.radians(host["rot"][1])
        sx, sy = host["scale"][0], host["scale"][1]

        def to_world(lx, ly, _h=host, _y=yaw, _sx=sx, _sy=sy):
            lx, ly = lx * _sx, ly * _sy
            return (_h["loc"][0] + lx * math.cos(_y) - ly * math.sin(_y),
                    _h["loc"][1] + lx * math.sin(_y) + ly * math.cos(_y))
        cx, cy = (d["box"][0] + d["box"][3]) / 2, (d["box"][1] + d["box"][4]) / 2
        best = None
        for lside, spans in op.items():
            for a, b in spans:
                mid = (a + b) / 2
                if lside[1] == "X":
                    fx = hb[3] if lside[0] == "+" else hb[0]
                    wx, wy = to_world(fx, mid)
                else:
                    fy = hb[4] if lside[0] == "+" else hb[1]
                    wx, wy = to_world(mid, fy)
                dist = math.hypot(wx - cx, wy - cy)
                if best is None or dist < best[0]:
                    best = (dist, lside, a, b)
        if not best or best[0] > 150:
            continue
        _, lside, a, b = best
        nx, ny = {"+X": (1, 0), "-X": (-1, 0), "+Y": (0, 1), "-Y": (0, -1)}[lside]
        face = (hb[3] if lside == "+X" else hb[0] if lside == "-X" else hb[4] if lside == "+Y" else hb[1])
        for lat in (-30, 0, 30):
            along = (a + b) / 2 + lat
            pt_out = (face + nx * 200 if lside[1] == "X" else along, face + ny * 200 if lside[1] == "Y" else along)
            pt_in = (face - nx * 120 if lside[1] == "X" else along, face - ny * 120 if lside[1] == "Y" else along)
            wo, wi = to_world(*pt_out), to_world(*pt_in)
            for hz in (40, 100, 170):
                z = host["box"][2] + hz
                walk.append((d["name"], [wo[0] + at[0], wo[1] + at[1], z + at[2], wi[0] + at[0], wi[1] + at[1], z + at[2]]))
    if walk:
        got = ue.batch(_SEG_JOB, [w[1] for w in walk])["d"]
        blocked = {}
        for (dn, q), dist in zip(walk, got):
            if dist is not None and dist < 300:       # 200 outside + must reach >= 1 m inside
                blocked.setdefault(dn, []).append(dist - 200)
        for dn, ds in blocked.items():
            issues.append(f"CAN'T WALK IN: through {dn}'s doorway {len(ds)} of 9 player-sized traces stop "
                          f"{min(ds):.0f} cm past the wall line (a closed door, a counter or a prop blocks it) - "
                          f"leave the doorway open (no door mesh, or turn the door open with yaw 90) and keep 1.2 m "
                          f"clear behind it")
    nm = name_at(at)
    if nm:
        issues += similar(nm, signature([(p["mesh"], p["loc"], p["rot"][1]) for p in resolved]))
    if not jobs:
        return issues
    dists = ue.batch(_TRACE_JOB, [j[2] for j in jobs])["d"]
    surf = {}
    for (name, bottom, q), d in zip(jobs, dists):
        if d is not None:
            surf.setdefault(name, (bottom, []))[1].append(q[2] - d)
    for name, (bottom, zs) in surf.items():
        gap = bottom - min(zs)
        if gap > 10:
            issues.append(f"FLOATING (traced): {name} bottom is {gap:.0f} cm above the surface right beside it "
                          f"(a sloped roof is lower there) - move it down with offset z by about {gap + 15:.0f}")
    return issues


# ---------------------------------------------------------------- design registry (no near-duplicates)

REGISTRY = os.path.join(HERE, "designs_registry.json")


def signature(rows):
    """rows: (mesh, loc, yaw) -> set of coarse tokens: which mesh, roughly where, which way."""
    return sorted({f"{m.rsplit('/', 1)[-1].split('.')[0]}@{round(l[0] / 150)},{round(l[1] / 150)},{round(l[2] / 150)}"
                   f"r{round(y / 90) % 4}" for m, l, y in rows})


def similar(name, sig):
    reg = _read_json(REGISTRY)
    out = []
    a = set(sig)
    for other, osig in reg.items():
        if other == name:
            continue
        b = set(osig)
        j = len(a & b) / max(1, len(a | b))
        if j >= 0.6:
            out.append(f"TOO SIMILAR: {name} shares {len(a & b)} of {len(a | b)} placed parts with {other} - "
                       f"a new design needs a different shape (other modules, layout, storeys or roof)")
    reg[name] = sig
    _write_json(REGISTRY, reg)
    return out


def name_at(at):
    spots = _read_json(SPOTS)
    for n in spots:
        if test_spot(n) == [float(v) for v in at]:
            return n
    return None


# ---------------------------------------------------------------- what ue-kit built (the designs on file)

DESIGNS = os.path.join(HERE, "designs.json")
NAME_RX = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,63}")


def designs():
    """{name: {"folder", "parts", "built", "issues", "source"}} - the parts of the last real build of each
    Blueprint, exactly as they were sent."""
    return _read_json(DESIGNS)


def save_design(name, folder, parts, issues, source="build_blueprint"):
    d = designs()
    d[name] = {"folder": folder, "parts": parts, "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "issues": list(issues), "source": source}
    _write_json(DESIGNS, d)


def validate_parts(parts):
    """Says in plain words what is wrong with a parts list, or returns None."""
    if not isinstance(parts, list) or not parts:
        return "parts must be a non-empty list of part dicts, e.g. [{\"name\": \"GroundFloor\", \"mesh\": \"SM_House1stFloor04\"}]"
    for i, p in enumerate(parts):
        if not isinstance(p, dict):
            return f"part {i + 1} is not a dict (got {type(p).__name__})"
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            return f"part {i + 1} has no \"name\" (every part needs a unique name such as \"Roof\")"
        if not p.get("light") and (not isinstance(p.get("mesh"), str) or not p["mesh"].strip()):
            return (f"part \"{p['name']}\" has no \"mesh\" (e.g. \"SM_HouseRoof01\" - find names with kit_parts), "
                    f"and is not a light")
        for k in ("place", "cover"):
            if k in p and not isinstance(p[k], str):
                return f"part \"{p['name']}\": \"{k}\" must be text such as \"on:GroundFloor\""
    return None


def build_allowed(name, folder):
    """None if ue-kit may create or replace folder/name, else the reason it may not. Replacing is limited to
    what ue-kit built itself: a Blueprint anywhere else in the project is never deleted."""
    if not NAME_RX.fullmatch(name or ""):
        return f"name {name!r} is not a valid asset name (letters, digits and _ only, e.g. \"BP_HouseMill\")"
    folder = (folder or "").rstrip("/")
    mine = designs().get(name, {}).get("folder")
    in_sandbox = folder == SANDBOX or folder.startswith(SANDBOX + "/")
    if not in_sandbox and folder != mine:
        return (f"folder {folder} is outside {SANDBOX} and ue-kit did not build {name} there before - build it "
                f"under {SANDBOX} (the default) and let Mu move the finished Blueprint")
    return None


def overwrite_allowed(name, folder):
    """Called when folder/name already exists as an asset: only something ue-kit made may be replaced."""
    d = designs().get(name)
    if d and d.get("folder", "").rstrip("/") == folder.rstrip("/"):
        return None
    if not d and name in _read_json(SPOTS) and (folder == SANDBOX or folder.startswith(SANDBOX + "/")):
        return None                    # built by ue-kit before designs.json existed
    return (f"{folder}/{name} already exists and ue-kit has no record of building it there - it will not be "
            f"deleted. Choose another name")


def check_designs(names=None):
    """Dry-run every design on file against the current checks. Read-only."""
    d = designs()
    todo = [n for n in (names or sorted(d))]
    lines = []
    bad = 0
    for n in todo:
        if n not in d:
            lines.append(f"{n}: not on file (build it once with build_blueprint)")
            continue
        try:
            issues = check(resolve(d[n]["parts"]))
        except (ValueError, ue.UEError) as e:
            issues = [f"ERROR {e}"]
        bad += bool(issues)
        lines.append(f"{n}: " + ("ok" if not issues else f"{len(issues)} issue(s)"))
        lines.extend("   - " + i for i in issues)
    return f"{len(todo)} design(s), {bad} with issues\n" + "\n".join(lines)


def get_design(name=""):
    """The parts of a built design as JSON text, ready to edit and send back to build_blueprint; with no
    name, the list of designs on file."""
    d = designs()
    if not name:
        return f"{len(d)} design(s) on file: " + ", ".join(sorted(d))
    if name not in d:
        near = [n for n in sorted(d) if name.lower().replace("bp_", "") in n.lower()]
        return f"no design named {name!r} on file" + (f" - did you mean: {', '.join(near[:6])}?" if near else "")
    e = d[name]
    note = ""
    if all(p.get("place") == "at" for p in e["parts"]):
        note = ("\nNOTE these parts were read back from the built copy, so every part is placed with \"at\" (exact "
                "coordinates). To change the shape, re-place the parts you touch with on:/against:/flush:.")
    return (f"{name} - folder {e.get('folder')}, built {e.get('built')}, {len(e['parts'])} parts, "
            f"issues at build: {len(e.get('issues') or [])}{note}\n" + json.dumps(e["parts"], ensure_ascii=False))


def kit_notes(folder, query=""):
    """Writes a markdown summary of a mesh folder - sizes, pivots, known doorways, and which wall/floor
    modules stack on which - so a new asset pack can be used without measuring by hand. Read-only in the
    editor (doorways come from the cache only). Returns (text, path)."""
    paths = list_meshes(folder, query)
    if not paths:
        return f"no SM_* meshes matching {query!r} under {folder}", None
    bm = bounds(paths)
    oc = _read_json(OPEN_CACHE)
    fam = {}
    for p in paths:
        short = p.rsplit("/", 1)[-1].split(".")[0]
        fam.setdefault(re.sub(r"[_\d]+$", "", short), []).append((short, p))
    pack = folder.strip("/").split("/")[1] if folder.count("/") >= 2 else folder.strip("/")
    lines = [f"# {pack} kit notes (generated by ue-kit)", "",
             f"{len(paths)} meshes under `{folder}`" + (f" matching `{query}`" if query else "")
             + ". Sizes in cm, X x Y x Z, measured in the editor.", ""]
    for f in sorted(fam):
        lines += [f"## {f.replace('SM_', '')}", "", "| Mesh | Size | Pivot | Doorways |", "|---|---|---|---|"]
        for short, p in fam[f]:
            b = bm[p]
            door = opening_note(oc[p]).replace("doorways: ", "") if p in oc else "not measured"
            lines.append(f"| `{short}` | {b[3]-b[0]:.0f} x {b[4]-b[1]:.0f} x {b[5]-b[2]:.0f} | {pivot_note(b)} | {door} |")
        lines.append("")
    shells = [(p.rsplit("/", 1)[-1].split(".")[0], bm[p]) for p in paths
              if SHELL_MESH.search(p.rsplit("/", 1)[-1].replace("SM_", "")) and "Roof" not in p
              and bm[p][3] - bm[p][0] >= 200 and bm[p][4] - bm[p][1] >= 200]
    if 1 < len(shells) <= 40:
        lines += ["## What stacks on what", "",
                  "A module fits on another when neither is more than 75 cm wider on any side (the OVERHANG / "
                  "LEDGE checks). Sizes compared as placed, both centred.", ""]
        for top, tb in shells:
            fits = [low for low, lb in shells if low != top
                    and abs((tb[3] - tb[0]) - (lb[3] - lb[0])) / 2 <= 75 and abs((tb[4] - tb[1]) - (lb[4] - lb[1])) / 2 <= 75]
            lines.append(f"- `{top}` fits on: " + (", ".join(f"`{x}`" for x in fits) if fits else "nothing in this folder"))
        lines.append("")
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"KIT_{pack}_auto.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    unmeasured = sum(1 for p in paths if p not in oc)
    text = (f"wrote {out}: {len(paths)} meshes in {len(fam)} families"
            + (f", stacking table for {len(shells)} wall/floor modules" if 1 < len(shells) <= 40 else "")
            + (f". Doorways are not measured for {unmeasured} of them (kit_parts(..., doorways=True) in a test map "
               f"measures the ones you need)." if unmeasured else "."))
    return text, out


# ---------------------------------------------------------------- changing the level (test maps only)

_EXACT_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
def call(name, args):
    return execute_tool(name, json.dumps(args))
def run():
    out = []
    for a in call(S + "find_actors", {"name": DATA["label"], "tag": "", "collision_channels": []})["returnValue"]:
        lab = call(A + "get_label", {"actor": a})["returnValue"]
        if lab == DATA["label"]:
            if DATA["remove"]:
                call(S + "remove_from_scene", {"actor": a})
            out.append(a["refPath"])
        elif len(out) + len(DATA["near"]) < 8:
            DATA["near"].append(lab)
    return {"exact": out, "near": DATA["near"]}
"""


def exact_actors(label, remove=False):
    """Actors whose label IS `label` (the editor's own search matches any label that merely contains it).
    Returns (refPaths, a few similar labels). remove=True deletes the exact ones."""
    got = ue.batch(_EXACT_JOB, {"label": label, "remove": bool(remove), "near": []})
    return got["exact"], got["near"]


def remove_test_copy(label):
    """Deletes test copies by exact label. Refuses anything that is not a ue-kit test copy in a test map."""
    label = (label or "").strip()
    if not label.endswith(TEST_SUFFIX) or len(label) <= len(TEST_SUFFIX) + 2:
        return (f"NOT REMOVED: remove_actor only deletes ue-kit test copies - give the full label, which ends in "
                f"{TEST_SUFFIX} (e.g. \"BP_HouseMill{TEST_SUFFIX}\"). Got {label!r}.")
    level = current_level()
    if not in_test_map(level):
        return f"NOT REMOVED: the open level is {level}, not a test map - ue-kit never deletes actors in a game map."
    refs, near = exact_actors(label, remove=True)
    log_action("remove_actor", level=level, label=label, removed=refs)
    if not refs:
        return f"no actor labelled exactly {label!r}" + (f" (similar: {', '.join(near)})" if near else "")
    return f"removed {len(refs)} actor(s) labelled {label}"


_BUILD_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
O = "editor_toolset.toolsets.object.ObjectTools."
BT = "editor_toolset.toolsets.blueprint.BlueprintTools."
AT = "editor_toolset.toolsets.asset.AssetTools."

def call(name, args):
    return execute_tool(name, json.dumps(args))

def run():
    path = DATA["folder"] + "/" + DATA["name"]
    ref = {"refPath": path + "." + DATA["name"]}
    replaced = bool(call(AT + "exists", {"path": path})["returnValue"])
    if replaced and not DATA["may_replace"]:
        return {"refused": path}           # before anything is touched
    removed = []
    for a in call(S + "find_actors", {"name": DATA["label"], "tag": "", "collision_channels": []})["returnValue"]:
        # the search matches labels that only CONTAIN the text: delete this Blueprint's own copy, nothing else
        if call(A + "get_label", {"actor": a})["returnValue"] == DATA["label"]:
            call(S + "remove_from_scene", {"actor": a})
            removed.append(a["refPath"])
    if replaced:
        call(AT + "delete", {"path": path})
    return {"replaced": replaced, "removed": removed}
"""

_MAKE_JOB = """
S = "editor_toolset.toolsets.scene.SceneTools."
A = "editor_toolset.toolsets.actor.ActorTools."
O = "editor_toolset.toolsets.object.ObjectTools."
BT = "editor_toolset.toolsets.blueprint.BlueprintTools."
AT = "editor_toolset.toolsets.asset.AssetTools."

def call(name, args):
    return execute_tool(name, json.dumps(args))

def run():
    path = DATA["folder"] + "/" + DATA["name"]
    ref = {"refPath": path + "." + DATA["name"]}
    call(BT + "create", {"folder_path": DATA["folder"], "asset_name": DATA["name"],
                         "asset_type": {"refPath": "/Script/Engine.Actor"}})
    for p in DATA["parts"]:
        if p.get("light"):
            c = call(A + "add_component", {"owner": ref, "component_type": {"refPath": "/Script/Engine.PointLightComponent"},
                                           "name": p["name"]})["returnValue"]
            lt = p["light"]
            col = lt.get("color", [255, 200, 140])
            call(O + "set_properties", {"instance": c, "values": json.dumps({
                "RelativeLocation": {"X": p["loc"][0], "Y": p["loc"][1], "Z": p["loc"][2]},
                "Intensity": float(lt.get("intensity", 8.0)), "AttenuationRadius": float(lt.get("radius", 800.0)),
                "LightColor": {"R": col[0], "G": col[1], "B": col[2], "A": 255}})})
            continue
        c = call(A + "add_component", {"owner": ref, "component_type": {"refPath": "/Script/Engine.StaticMeshComponent"},
                                       "name": p["name"]})["returnValue"]
        vals = {"StaticMesh": p["mesh"],
                "RelativeLocation": {"X": p["loc"][0], "Y": p["loc"][1], "Z": p["loc"][2]},
                "RelativeRotation": {"Pitch": p["rot"][0], "Yaw": p["rot"][1], "Roll": p["rot"][2]},
                "RelativeScale3D": {"X": p["scale"][0], "Y": p["scale"][1], "Z": p["scale"][2]}}
        call(O + "set_properties", {"instance": c, "values": json.dumps(vals)})
    call(BT + "compile_blueprint", {"blueprint": ref})
    saved = call(AT + "save_assets", {"asset_paths": [path]})["returnValue"]
    t = DATA["at"]
    a = call(S + "add_to_scene_from_asset", {"asset_path": path, "name": DATA["label"],
             "xform": {"location": {"x": t[0], "y": t[1], "z": t[2]},
                       "rotation": {"pitch": 0, "yaw": 0, "roll": 0}, "scale": {"x": 1, "y": 1, "z": 1}}})["returnValue"]
    call(A + "add_tag", {"actor": a, "tag": DATA["tag"]})
    return {"saved": saved, "actor": a["refPath"]}
"""

AT_ = "editor_toolset.toolsets.asset.AssetTools"


def build(name, folder, resolved, at, level):
    """Creates/replaces the Blueprint and its one test copy. The caller has already checked the level, the
    folder and the name; whether an existing asset may be replaced is decided here, inside the same job."""
    folder = folder.rstrip("/")
    label = name + TEST_SUFFIX
    path = f"{folder}/{name}"
    data = {"folder": folder, "name": name, "label": label, "at": list(at), "tag": KIT_TAG,
            "may_replace": overwrite_allowed(name, folder) is None,
            "parts": [{k: p[k] for k in ("name", "mesh", "loc", "rot", "scale", "light") if k in p} for p in resolved]}
    cleared = ue.batch(_BUILD_JOB, data)          # step 1: remove this Blueprint's old copy and old asset
    if cleared.get("refused"):
        return {"refused": overwrite_allowed(name, folder)}
    log_action("clear", level=level, blueprint=path, replaced_asset=cleared.get("replaced"),
               removed_copies=cleared.get("removed"))
    # The editor's delete only drops an asset that was not loaded yet from memory and leaves its file; asked
    # again in a later call it removes the file. Creating over the leftover fails with "already exists".
    for _ in range(3):
        if not ue.call(AT_, "exists", {"path": path}).get("returnValue"):
            break
        ue.call(AT_, "delete", {"path": path})
    else:
        if ue.call(AT_, "exists", {"path": path}).get("returnValue"):
            raise ue.UEError(f"the editor would not delete the old {path} (is it open in a Blueprint tab?)")
    got = ue.batch(_MAKE_JOB, data)               # step 2: create, fill, compile, save, spawn the test copy
    log_action("build", level=level, blueprint=path, test_copy=got.get("actor"), at=list(at))
    return {**cleared, **got}
