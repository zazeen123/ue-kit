"""ue-kit: an MCP server that lets an agent (Hermes, Claude) assemble buildings in the open Unreal Editor
without doing 3D maths and without handling raw images.

Tools
  kit_parts      list kit meshes with real sizes and where each pivot sits
  kit_pictures   thumbnails of meshes, saved as one PNG sheet (open it with your vision tool)
  build_blueprint  parts placed RELATIVELY (on / against / flush / ground) -> Blueprint + test copy + checks
  look           photos of a placed actor from 4 sides + a 3/4 view, saved as one PNG sheet
  look_inside    photos of a building's interior from its doorway
  remove_actor   delete one test copy by its exact label (<name>_Test), test maps only
  check_designs  re-run the checks on every design ue-kit has built (read-only)

Runs over stdio:  python U:/ai_workspace/ue-kit/server.py
Needs the Unreal Editor open with its MCP server (http://127.0.0.1:8000/mcp).

What ue-kit may change is decided in kit.py (hot-reloaded): test copies, probes and deletions only in a
test map; Blueprints only under kit.SANDBOX or where ue-kit built that name before; every change is logged
to C:/UE/logs/ue-kit/actions.log.
"""
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.fastmcp import Image as MCPImage  # noqa: E402
from PIL import Image  # noqa: E402

import importlib  # noqa: E402

import kit  # noqa: E402
import ue_client as ue  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_MTIMES = {}


def _fresh():
    """Reload kit.py / ue_client.py when they changed on disk, so a long-lived server (e.g. started by the
    Hermes desktop gateway) never runs stale checks. Changes to server.py itself still need a restart."""
    global kit, ue
    changed = False
    for name in ("ue_client.py", "kit.py"):
        m = os.path.getmtime(os.path.join(HERE, name))
        if _MTIMES.get(name, m) != m:
            changed = True
        _MTIMES[name] = m
    if changed:
        ue = importlib.reload(ue)
        kit = importlib.reload(kit)


_fresh()

OUT = r"C:\UE\logs\ue-kit"
os.makedirs(OUT, exist_ok=True)

mcp = FastMCP("ue-kit", instructions=(
    "Build things in the open Unreal Editor by naming parts and how they sit on each other; ue-kit computes "
    "coordinates from real mesh sizes, checks for floating/sunk parts and roofs that do not cover the walls, "
    "and saves photos as PNG files you can open. Workflow: kit_parts -> kit_pictures -> build_blueprint -> "
    "fix every ISSUE it reports -> look -> open the sheet PNG with your vision tool -> fix -> repeat."))

S = "editor_toolset.toolsets.scene.SceneTools"
A = "editor_toolset.toolsets.actor.ActorTools"
APP = "EditorToolset.EditorAppToolset"


def _find(label):
    """([actor], None) for the actor labelled exactly `label`, or ([], a message naming similar labels).
    The editor's own search returns every actor whose label merely contains the text."""
    try:
        refs, near = kit.exact_actors((label or "").strip())
    except ue.UEError as e:
        return [], f"ERROR {e}"
    if refs:
        return [{"refPath": r} for r in refs], None
    return [], (f"no actor labelled exactly {label!r} in the open level"
                + (f" - did you mean: {', '.join(near)}?" if near else ""))


@mcp.tool()
def kit_parts(query: str = "", folder: str = "/Game/FantasyBundle/Meshes", limit: int = 40,
              doorways: bool = False) -> str:
    """List static meshes in a content folder whose names match `query` (regex, case-insensitive),
    with their real size in cm (X x Y x Z) and where the pivot sits. Example queries: "HouseRoof",
    "House1stFloor|House2dFloor|HouseBase", "Door|Window", "Stairs", "Chimney", "CastleWall".
    Sizes are measured in the editor once and cached.
    doorways=True also probes every side with line traces and lists walk-through gaps ("doorways: +Y -60..55"
    = an opening on the +Y face from x=-60 to 55) - use it for floor/wall modules before placing a door."""
    _fresh()
    try:
        paths = kit.list_meshes(folder, query)[:limit]
    except re.error as e:
        return (f"ERROR query {query!r} is not a valid regular expression ({e}). Use plain words joined with | , "
                f"e.g. \"HouseRoof|Chimney\"")
    if not paths:
        return f"no SM_* meshes matching {query!r} under {folder}"
    try:
        bm = kit.bounds(paths)
    except (ValueError, ue.UEError) as e:
        return f"ERROR {e}"
    ops, note = {}, ""
    if doorways:
        for p in paths:       # one by one: a mesh that cannot be measured now must not hide the cached ones
            try:
                ops.update(kit.openings([p], measure=True))
            except kit.NotMeasured as e:
                note = f"\nNOTE {e} - open a test map (e.g. L_GatefallTown_Preview) and ask again."
            except ue.UEError as e:
                note = f"\nNOTE doorways not measured: {e}"
    lines = [f"{len(paths)} mesh(es). size = X x Y x Z cm; min/max are relative to the pivot."]
    for p in paths:
        b = bm[p]
        extra = f" | {kit.opening_note(ops[p])}" if p in ops else (" | doorways: not measured" if doorways else "")
        lines.append(f"{p.rsplit('/', 1)[-1].split('.')[0]}: {b[3]-b[0]:.0f} x {b[4]-b[1]:.0f} x {b[5]-b[2]:.0f} | "
                     f"{kit.pivot_note(b)}{extra} | path {p}")
    return "\n".join(lines) + note


@mcp.tool()
def kit_pictures(meshes: list[str], sheet_name: str = "parts") -> str:
    """Render thumbnails of up to 8 meshes (names like "SM_HouseRoof01" or full /Game paths) into ONE PNG
    sheet, left to right in the given order. Returns the PNG path - open it with your vision tool to see
    what each part looks like (e.g. which side has the door opening)."""
    _fresh()
    if not isinstance(meshes, list) or not meshes or not all(isinstance(m, str) and m.strip() for m in meshes):
        return "ERROR meshes must be a list of 1-8 mesh names, e.g. [\"SM_HouseRoof01\", \"SM_Door01\"]"
    meshes = meshes[:8]
    ims = []
    for m in meshes:
        path = kit.full_path(m).split(".")[0]
        f = os.path.join(OUT, f"thumb_{path.rsplit('/', 1)[-1]}.png")
        try:
            ue.save_png(ue.call(APP, "CaptureAssetImage", {"assetPath": path}), f)
        except ue.UEError as e:
            return f"ERROR no picture of {m}: {str(e)[:200]} - check the name with kit_parts"
        ims.append(Image.open(f).convert("RGB"))
    w = sum(i.width for i in ims)
    sheet = Image.new("RGB", (w, max(i.height for i in ims)))
    x = 0
    for i in ims:
        sheet.paste(i, (x, 0))
        x += i.width
    out = os.path.join(OUT, f"{sheet_name}_sheet.png")
    sheet.save(out)
    return f"saved {out} - left to right: " + ", ".join(m.rsplit('/', 1)[-1] for m in meshes)


@mcp.tool()
def build_blueprint(name: str, parts: list[dict], folder: str = "/Game/ARPG/_Sandbox",
                    test_location: list[float] | None = None, dry_run: bool = False) -> str:
    """Build (or rebuild) an Actor Blueprint from static-mesh parts placed RELATIVE to each other, save it,
    and spawn one test copy (label <name>_Test) at test_location (default: this Blueprint's own free spot
    in a row outside the town, so different Blueprints never overlap). Returns a parts table and an ISSUES list -
    fix every issue and call again (each call replaces the Blueprint and the test copy).

    Each part is a dict:
      name   unique, e.g. "Plinth", "GroundFloor", "Roof", "Door" (names containing roof/door/floor/wall/
             base/plinth are used by the checks)
      mesh   "SM_HouseBase01" (FantasyBundle) or a full /Game path
      place  where it goes (default "ground"):
               "ground"            bottom on z=0, centred at offset
               "on:<Part>"         centred on top of an EARLIER part (bottom = its top)
               "against:<Part>:<side>"  outside that face of an earlier part, side +X -X +Y -Y,
                                   bottom = that part's bottom (steps against a plinth, a lean-to)
               "flush:<Part>:<side>"    inside that face, flush with it (a door in a wall opening)
               "inside:<Part>"     on the floor inside that module, centred unless offset
               "at"                pivot exactly at offset (escape hatch)
      offset [x, y, z] cm added after placing (e.g. raise a bracket, shift a door sideways)
      yaw    degrees (also pitch, roll)
      scale  number or [x, y, z]
      cover  "<Part>" or "<Part>:<margin_cm>" - scale X/Y so this part's footprint covers that part plus the
             margin on every side (default 40) - use it for roofs
      light  {"intensity": 8, "radius": 800, "color": [255, 200, 140]} makes this part a point light (no mesh);
             put one in a shop: {"name": "Lamp", "light": {...}, "place": "inside:GroundFloor", "offset": [0, 0, 230]}
    Interiors: "place": "inside:<module>" sets a prop on that module's floor (counter, shelves, crates, goods).
    dry_run=True only computes and checks (fast, nothing changes in the editor).
    folder must stay under /Game/ARPG/_Sandbox (leave it out); an existing Blueprint is only replaced if
    ue-kit built it. A door is only demanded when the design has a walk-in house module."""
    _fresh()
    folder = (folder or "").rstrip("/")
    bad = kit.validate_parts(parts) or kit.build_allowed(name, folder)
    if bad:
        return f"ERROR {bad}"
    level = ""
    try:
        if not dry_run:
            level = kit.current_level()
        res = kit.resolve(parts)
        # a real build in a test map may measure doorways it has not seen; a dry run never touches the level
        issues = kit.check(res, measure=not dry_run and kit.in_test_map(level))
    except KeyError as e:
        return f"ERROR a part is missing the key {e}"
    except (ValueError, TypeError, ue.UEError) as e:
        return f"ERROR {e}"
    top = max(p["box"][5] for p in res)
    xs = (min(p["box"][0] for p in res), max(p["box"][3] for p in res))
    ys = (min(p["box"][1] for p in res), max(p["box"][4] for p in res))
    report = [f"{len(res)} parts; overall {xs[1]-xs[0]:.0f} x {ys[1]-ys[0]:.0f} cm footprint, {top:.0f} cm tall",
              kit.table(res), "ISSUES: " + ("none" if not issues else ""), *[" - " + i for i in issues]]
    if dry_run:
        return "\n".join(["DRY RUN (nothing built)"] + report)
    label = name + kit.TEST_SUFFIX
    if not kit.in_test_map(level):
        return ("NOT BUILT: the open level is " + level + ", not a test map - test copies must never go into a "
                "real game map. Ask Claude/Mu to open /Game/ARPG/Maps/Gatefall/L_GatefallTown_Preview, then build "
                "again (dry_run works anywhere).\n" + "\n".join(report))
    test_location = kit.test_spot(name, test_location)
    try:
        got = kit.build(name, folder, res, test_location, level)
    except ue.UEError as e:
        kit.log_action("build_failed", level=level, blueprint=f"{folder}/{name}", error=str(e)[:300])
        return (f"BUILD FAILED part-way: {str(e)[:400]}\nThe Blueprint {folder}/{name} may be incomplete - fix the "
                f"cause and build again.\n" + "\n".join(report))
    if got.get("refused"):
        return "NOT BUILT: " + got["refused"] + "\n" + "\n".join(report)
    kit.save_design(name, folder, parts, issues)
    report.insert(0, f"Blueprint {folder}/{name} saved={got.get('saved')}; test copy '{label}' at "
                     f"{list(test_location)}. Next: look(\"{label}\") and open the sheet.")
    try:
        traced = kit.post_build(res, test_location)     # hot-reloaded: checks on the real, built geometry
    except Exception as e:
        traced = [f"(traced checks skipped: {e})"]
    if traced:
        report.append("TRACED ISSUES (measured on the built copy - fix these too):")
        report.extend(" - " + t for t in traced)
    return "\n".join(report)


@mcp.tool()
def look(label: str, distance_scale: float = 1.0) -> list:
    """Photograph a placed actor (by its label, e.g. "MyHouse_Test") from front (+Y), back (-Y), right (+X),
    left (-X) and a high 3/4 view. Saves each photo and ONE 2x3 sheet PNG; returns the paths. Open the sheet
    with your vision tool and judge it: parts floating or sunk, gaps, roof not covering, door missing or
    blocked, odd scale."""
    _fresh()
    found, err = _find(label)
    if err:
        return err
    b = ue.call(A, "get_actor_bounds", {"actor": found[0]})["returnValue"]
    mn, mx = b["min"], b["max"]
    mn["z"] = max(mn["z"], 0.0)      # ignore editor-only sprites below the ground
    c = [(mn[k] + mx[k]) / 2 for k in "xyz"]
    size = max(mx["x"] - mn["x"], mx["y"] - mn["y"], mx["z"] - mn["z"])
    d = (size * 1.5 + 300) * distance_scale
    h = c[2] + (mx["z"] - mn["z"]) * 0.1
    views = [("front_+Y", (c[0], c[1] + d, h), -90), ("back_-Y", (c[0], c[1] - d, h), 90),
             ("right_+X", (c[0] + d, c[1], h), 180), ("left_-X", (c[0] - d, c[1], h), 0)]
    q = d * 0.75
    views.append(("three_quarter", (c[0] + q, c[1] + q, mx["z"] + d * 0.45), -135))
    files = []
    for vname, (x, y, z), yaw in views:
        pitch = -math.degrees(math.atan2(z - c[2], math.hypot(x - c[0], y - c[1])))
        args = {"captureTransform": {"location": {"x": x, "y": y, "z": z},
                                     "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0}},
                "annotations": {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0,
                                "classFilter": None, "maxLabels": 0},
                "bShowUI": False}
        # Capture twice and keep the second: Nanite culls against the previous frame's depth, so the first
        # frame from a new viewpoint can drop whole modules (their cached shadows still show).
        ue.call(APP, "CaptureViewport", args)
        r = ue.call(APP, "CaptureViewport", args)
        f = os.path.join(OUT, f"{label}_{vname}.png")
        ue.save_png(r, f)
        files.append((vname, f))
    tiles = [Image.open(f).convert("RGB").resize((640, 360)) for _, f in files]
    sheet = Image.new("RGB", (1920, 720), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * 640, (i // 3) * 360))
    out = os.path.join(OUT, f"{label}_sheet.png")
    sheet.save(out)
    small = os.path.join(OUT, f"{label}_sheet_small.jpg")
    sheet.resize((1344, 504)).save(small, quality=85)
    text = (f"saved sheet {out} (row 1: front +Y, back -Y, right +X; row 2: left -X, 3/4 from +X+Y above).\n"
            f"actor box: ({mn['x']:.0f}, {mn['y']:.0f}, {mn['z']:.0f}) -> ({mx['x']:.0f}, {mx['y']:.0f}, {mx['z']:.0f})\n"
            + "\n".join(f"{v}: {f}" for v, f in files) +
            "\n\nThe sheet is attached below. If you cannot see an image, open the sheet with your vision tool NOW. "
            "Answer each question from the picture before you report:\n"
            "1. Front view: is a door visible, and can you walk up to it (steps if the floor is raised)?\n"
            "2. Does anything hang in the air or stick out past what holds it up?\n"
            "3. Does the roof cover every wall below it, with no bare flat ledges?\n"
            "4. Do the floors line up (no box sitting on a much bigger or smaller box)?\n"
            "5. Is anything buried in the ground or poking through another part?")
    return [text, MCPImage(path=small)]


@mcp.tool()
def look_inside(label: str, door_side: str = "+Y", door_offset: float = 0.0) -> list:
    """Photograph the INSIDE of a placed building: from just inside its doorway looking in, from the back
    looking at the doorway, and from a back corner. door_side = the side the entrance faces (+X -X +Y -Y);
    door_offset slides the cameras along that wall to line up with the doorway (cm, e.g. 143). Returns one
    sheet image + 3 questions."""
    _fresh()
    found, err = _find(label)
    if err:
        return err
    b = ue.call(A, "get_actor_bounds", {"actor": found[0]})["returnValue"]
    mn, mx = b["min"], b["max"]
    mn["z"] = max(mn["z"], 0.0)
    cx, cy = (mn["x"] + mx["x"]) / 2, (mn["y"] + mx["y"]) / 2
    ax = 0 if door_side[1] == "X" else 1
    sgn = 1 if door_side[0] == "+" else -1
    z = mn["z"] + 160
    lo, hi = (mn["x"], mx["x"]) if ax == 0 else (mn["y"], mx["y"])
    near = (hi - 110) if sgn > 0 else (lo + 110)          # just inside the doorway wall
    far = (lo + 90) if sgn > 0 else (hi - 90)             # near the back wall
    along0 = (cy if ax == 0 else cx) + door_offset

    def pt(depth, along):
        return (depth, along) if ax == 0 else (along, depth)
    in_yaw = {(1, 0): 180, (-1, 0): 0, (1, 1): -90, (-1, 1): 90}[(sgn, ax)]
    views = [("from_door", pt(near, along0), in_yaw, -8),
             ("from_back", pt(far, along0), in_yaw + 180, -8),
             ("back_corner", pt(far, along0 + 120), in_yaw + 205, -15)]
    files = []
    for vname, (x, y), yaw, pitch in views:
        args = {"captureTransform": {"location": {"x": x, "y": y, "z": z},
                                     "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0}},
                "annotations": {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0,
                                "classFilter": None, "maxLabels": 0}, "bShowUI": False}
        ue.call(APP, "CaptureViewport", args)
        f = os.path.join(OUT, f"{label}_inside_{vname}.png")
        ue.save_png(ue.call(APP, "CaptureViewport", args), f)
        files.append((vname, f))
    tiles = [Image.open(f).convert("RGB").resize((640, 360)) for _, f in files]
    sheet = Image.new("RGB", (1920, 360), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * 640, 0))
    out = os.path.join(OUT, f"{label}_inside_sheet.png")
    sheet.save(out)
    small = os.path.join(OUT, f"{label}_inside_small.jpg")
    sheet.resize((1344, 252)).save(small, quality=85)
    text = ("saved " + out + " (left: from the doorway looking in, middle: from the back looking at the "
            "doorway, right: back corner).\n" + "\n".join(f"{v}: {f}" for v, f in files) +
            "\n\nAnswer from the picture: 1. Is there a floor and room to walk in (nothing blocking the "
            "doorway)? 2. Is the shop furnished (counter, shelves, goods) and lit? 3. Does anything float, "
            "sink or poke through a wall?")
    return [text, MCPImage(path=small)]


@mcp.tool()
def remove_actor(label: str) -> str:
    """Delete ONE ue-kit test copy from the open test map. `label` must be its full, exact label, which ends
    in _Test (e.g. "BP_HouseMill_Test"). Anything else - a partial name, an actor that is not a test copy, a
    level that is not a test map - is refused. To replace a test copy just build again; this is only for
    removing a design you are abandoning."""
    _fresh()
    try:
        return kit.remove_test_copy(label)
    except ue.UEError as e:
        return f"ERROR {e}"


@mcp.tool()
def check_designs(names: list[str] | None = None) -> str:
    """Re-run the current checks on the designs ue-kit has built (all of them, or just `names`), from the
    parts of each one's last build. Read-only. Use it after the checks changed, or to see which Blueprints
    need rebuilding; then rebuild each one that reports issues."""
    _fresh()
    return kit.check_designs(names)


if __name__ == "__main__":
    mcp.run()
