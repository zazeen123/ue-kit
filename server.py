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
import shots  # noqa: E402
import town  # noqa: E402
import ue_client as ue  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_MTIMES = {}


def _fresh():
    """Reload the logic modules when they changed on disk, so a long-lived server (e.g. started by the
    Hermes desktop gateway) never runs stale checks. Changes to server.py itself still need a restart."""
    global kit, ue, shots, town
    changed = False
    for name in ("ue_client.py", "kit.py", "shots.py", "town.py"):
        m = os.path.getmtime(os.path.join(HERE, name))
        if _MTIMES.get(name, m) != m:
            changed = True
        _MTIMES[name] = m
    if changed:                                   # dependency order: each later module imports the earlier ones
        ue = importlib.reload(ue)
        kit = importlib.reload(kit)
        shots = importlib.reload(shots)
        town = importlib.reload(town)


def _img(text, path):
    """A tool result with the picture attached when there is one."""
    return [text, MCPImage(path=path)] if path else [text]


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
def kit_pictures(meshes: list[str], sheet_name: str = "parts"):
    """Render thumbnails of up to 8 meshes (names like "SM_HouseRoof01" or full /Game paths) into ONE PNG
    sheet; each picture has its mesh name written under it. The sheet is attached and its path returned -
    look at it to see what each part is like (e.g. which side has the door opening)."""
    _fresh()
    if not isinstance(meshes, list) or not meshes or not all(isinstance(m, str) and m.strip() for m in meshes):
        return "ERROR meshes must be a list of 1-8 mesh names, e.g. [\"SM_HouseRoof01\", \"SM_Door01\"]"
    return _img(*shots.thumbs(meshes[:8], sheet_name))


@mcp.tool()
def build_blueprint(name: str, parts: list[dict], folder: str = "/Game/ARPG/_Sandbox",
                    test_location: list[float] | None = None, dry_run: bool = False, autofix: bool = False):
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
    ue-kit built it. A door is only demanded when the design has a walk-in house module.
    autofix=True repairs the issues that have one answer (roof not covering its walls, a part a little above
    or below where it rests, steps taller than the door sill) and prints the corrected parts - use THOSE
    parts from then on. When a real build has no issues at all, the photo sheet of the test copy is attached,
    so you can answer the look questions straight away."""
    _fresh()
    folder = (folder or "").rstrip("/")
    bad = kit.validate_parts(parts) or kit.build_allowed(name, folder)
    if bad:
        return f"ERROR {bad}"
    level = ""
    fixed = []
    try:
        if not dry_run:
            level = kit.current_level()
        if autofix:
            parts, fixed = kit.autofix(parts)
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
    if fixed:
        report += ["AUTO-FIXED (already applied):", *[" - " + f for f in fixed],
                   "PARTS NOW (send and report these from now on): " + json.dumps(parts, ensure_ascii=False)]
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
    if issues or traced:
        return "\n".join(report)
    try:                                           # a clean build: show it, so the look questions get answered
        text, small = shots.look(label)
    except Exception as e:
        return "\n".join(report + [f"(photo failed: {str(e)[:200]} - call look(\"{label}\"))"])
    report[0] = report[0].replace(f" Next: look(\"{label}\") and open the sheet.", "")
    return _img("\n".join(report) + "\n\nPHOTOS of the test copy - " + text, small)


@mcp.tool()
def look(label: str, distance_scale: float = 1.0):
    """Photograph a placed actor (by its exact label, e.g. "MyHouse_Test") from front (+Y), back (-Y), right
    (+X), left (-X) and a high 3/4 view. Saves each photo and ONE 2x3 sheet PNG, attaches the sheet and
    returns the paths. Judge it: parts floating or sunk, gaps, roof not covering, door missing or blocked,
    odd scale."""
    _fresh()
    try:
        return _img(*shots.look(label, distance_scale))
    except ue.UEError as e:
        return f"ERROR {e}"


@mcp.tool()
def look_inside(label: str, door_side: str = "+Y", door_offset: float = 0.0):
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



@mcp.tool()
def get_design(name: str = "") -> str:
    """The parts JSON of a design ue-kit built (e.g. "BP_HouseBakery"), to edit and send back to
    build_blueprint under a new name - much easier than writing a house from nothing. With no name: the list
    of designs on file."""
    _fresh()
    return kit.get_design(name)


@mcp.tool()
def gallery(names: list[str] | None = None):
    """One labelled 3/4 photo per built design (its test copy) in a single grid picture - compare many
    designs at a glance, e.g. to pick houses for a street or to spot the odd one out. names = Blueprint names
    without _Test; leave out for every design on file (slow: about 3 s each)."""
    _fresh()
    try:
        return _img(*shots.gallery(names or sorted(kit.designs())))
    except ue.UEError as e:
        return f"ERROR {e}"


@mcp.tool()
def look_area(x: float, y: float, size: float = 6000, z: float = 0, name: str = "area"):
    """Photograph a REGION of the open level - centre x, y (cm), `size` cm across - from straight above and
    from four corners, as one sheet. For judging a street, a market square or a whole town layout rather
    than one building (use look for that)."""
    _fresh()
    try:
        return _img(*shots.area(x, y, size, z, name))
    except ue.UEError as e:
        return f"ERROR {e}"


@mcp.tool()
def kit_notes(folder: str = "/Game/FantasyBundle/Meshes", query: str = "") -> str:
    """Write a markdown summary of a mesh folder: every mesh's size and pivot, known doorways, and which
    wall/floor modules stack on which. Use it once when starting with a new asset pack, then read the file
    it names instead of measuring parts one by one."""
    _fresh()
    try:
        return kit.kit_notes(folder, query)[0]
    except (ValueError, ue.UEError) as e:
        return f"ERROR {e}"



@mcp.tool()
def promote(name: str, folder: str = "/Game/ARPG/Environment/Town") -> str:
    """Move a FINISHED design out of the sandbox into the game's content folder, so it can be used in real
    maps. Only for a design ue-kit built that has no issues; refused otherwise. Do this once per design, when
    Mu has accepted it - not as part of building."""
    _fresh()
    try:
        return kit.promote(name, folder)
    except ue.UEError as e:
        return f"ERROR {e}"



@mcp.tool()
def place_town(assign: dict | None = None, types: list[str] | None = None, lots: list[int] | None = None,
               dry_run: bool = True, seed: int = 1, origin: list[float] | None = None):
    """Put built designs on the lots of the town layout (Docs/World/gatefall-layout.json): one design per
    lot, turned so its door faces the nearest road, set on the ground under it (with a stone foundation where
    the ground slopes a little). Test map only.

      assign  {"36": "BP_HouseBakery", ...} fixes the design of some lots; every other selected lot gets a
              design that fits it, chosen so that neighbours differ (same seed = same town)
      types   layout types to fill: ["house"] (default), or ["stall"], or both
      lots    only these lot ids (default: all of those types)
      dry_run True (default) only plans and measures - nothing is placed. Read the table and the ISSUES
              (LOT OCCUPIED, TOO BIG, ON THE ROAD, OVERLAP, STEEP LOT) first.
      origin  [x, y] cm added to every position - to try a layout on empty ground

    A real run first removes what ue-kit placed before (found by its tag, nothing else), places the plan,
    and attaches an overview photo. Occupied and steep lots are skipped, never built over."""
    _fresh()
    try:
        layout = town.load_layout()
    except (OSError, ValueError) as e:
        return f"ERROR cannot read the layout {town.LAYOUT}: {e}"
    origin = tuple(origin or (0, 0))[:2]
    try:
        rows, issues = town.plan(layout, assign, tuple(types or ("house",)), lots, origin, seed)
        if not rows:
            return "nothing to place.\nISSUES:\n" + "\n".join(" - " + i for i in issues)
        removed = None
        if not dry_run:                 # take ue-kit's earlier town out first, so the ground can be measured
            err, removed = town.remove_own()
            if err:
                return err
        issues += town.survey(rows)
        res = town.place(rows, dry_run, removed=removed)
    except (ValueError, KeyError, TypeError) as e:
        return f"ERROR {e}"
    except ue.UEError as e:
        return f"ERROR {e}"
    if res.get("error"):
        return res["error"]
    skipped = [r for r in rows if r.get("flag")]
    head = (f"DRY RUN (nothing placed): would place {len(rows) - len(skipped)} of {len(rows)} lot(s)" if dry_run else
            f"placed {res['placed']} actor(s) on {len(rows) - len(skipped)} lot(s); removed {res['removed']} from the "
            f"previous placement")
    founds = [j["label"] for j in res["jobs"] if j["label"].endswith("_Foundation")]
    if not dry_run and res["placed"] != res["wanted"]:
        issues.append(f"PLACEMENT INCOMPLETE: {res['placed']} of {res['wanted']} actors are in the level - call "
                      f"place_town again")
    text = "\n".join([head, town.table(rows), "ISSUES: " + ("none" if not issues else ""),
                       *[" - " + i for i in issues]]
                      + (["foundations: " + ", ".join(founds)] if founds else []))
    if dry_run:
        return text + "\nCall again with dry_run=False to place it."
    xs = [v for r in rows for v in (r["box"][0], r["box"][2])]
    ys = [v for r in rows for v in (r["box"][1], r["box"][3])]
    z = max((r.get("z", 0) for r in rows), default=0)
    try:
        ptext, small = shots.area((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                                  max(max(xs) - min(xs), max(ys) - min(ys)) + 1500, z, "town")
    except Exception as e:
        return text + f"\n(overview photo failed: {str(e)[:200]} - call look_area)"
    return _img(text + "\n\nOVERVIEW - " + ptext + "\nCheck: does every door face a road, does any house "
                "stand on a road or touch its neighbour, does anything float or sink?", small)


@mcp.tool()
def clear_town() -> str:
    """Remove everything place_town put into the open test map (only actors carrying ue-kit's town tag)."""
    _fresh()
    try:
        return town.clear()
    except ue.UEError as e:
        return f"ERROR {e}"


if __name__ == "__main__":
    mcp.run()
