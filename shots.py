"""Photos for ue-kit: every function saves PNG/JPG files and returns (text, path of a small sheet or None).
Read-only in the editor apart from moving the editor camera. Hot-reloaded by server.py like kit.py."""
import math
import os
import time

from PIL import Image, ImageDraw, ImageFont

import kit
import ue_client as ue

A = "editor_toolset.toolsets.actor.ActorTools"
APP = "EditorToolset.EditorAppToolset"
NO_NOTES = {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0, "classFilter": None,
            "maxLabels": 0}

LOOK_QUESTIONS = (
    "Answer each question from the picture before you report:\n"
    "1. Front view: is a door visible, and can you walk up to it (steps if the floor is raised)?\n"
    "2. Does anything hang in the air or stick out past what holds it up?\n"
    "3. Does the roof cover every wall below it, with no bare flat ledges?\n"
    "4. Do the floors line up (no box sitting on a much bigger or smaller box)?\n"
    "5. Is anything buried in the ground or poking through another part?")


def _font(size):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def capture(loc, pitch, yaw, path, settle=0.0):
    """One viewport photo from loc looking along pitch/yaw, saved to path. Captured twice, the second kept:
    Nanite culls against the previous frame's depth, so the first frame from a new viewpoint can drop whole
    modules. settle > 0 also moves the editor camera there first and waits (needed after a long jump)."""
    xf = {"location": {"x": loc[0], "y": loc[1], "z": loc[2]}, "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0}}
    if settle:
        ue.call(APP, "SetCameraTransform", {"transform": xf})
        time.sleep(settle)
    args = {"captureTransform": xf, "annotations": NO_NOTES, "bShowUI": False}
    ue.call(APP, "CaptureViewport", args)
    return ue.save_png(ue.call(APP, "CaptureViewport", args), path)


def _aim(frm, to):
    yaw = math.degrees(math.atan2(to[1] - frm[1], to[0] - frm[0]))
    pitch = -math.degrees(math.atan2(frm[2] - to[2], math.hypot(to[0] - frm[0], to[1] - frm[1])))
    return pitch, yaw


def _bounds(actor):
    b = ue.call(A, "get_actor_bounds", {"actor": actor})["returnValue"]
    mn, mx = b["min"], b["max"]
    mn["z"] = max(mn["z"], 0.0) if mn["z"] > -50 else mn["z"]      # ignore editor-only sprites just below the ground
    return mn, mx


def find(label):
    """({"refPath": ...}, None) for the actor labelled exactly `label`, else (None, message)."""
    refs, near = kit.exact_actors((label or "").strip())
    if refs:
        return {"refPath": refs[0]}, None
    return None, (f"no actor labelled exactly {label!r} in the open level"
                  + (f" - did you mean: {', '.join(near)}?" if near else ""))


def look(label, distance_scale=1.0):
    """Front, back, right, left and a high 3/4 view of one actor as a 3x2 sheet."""
    actor, err = find(label)
    if err:
        return err, None
    mn, mx = _bounds(actor)
    c = [(mn[k] + mx[k]) / 2 for k in "xyz"]
    size = max(mx["x"] - mn["x"], mx["y"] - mn["y"], mx["z"] - mn["z"])
    d = (size * 1.5 + 300) * distance_scale
    h = c[2] + (mx["z"] - mn["z"]) * 0.1
    q = d * 0.75
    views = [("front_+Y", (c[0], c[1] + d, h)), ("back_-Y", (c[0], c[1] - d, h)), ("right_+X", (c[0] + d, c[1], h)),
             ("left_-X", (c[0] - d, c[1], h)), ("three_quarter", (c[0] + q, c[1] + q, mx["z"] + d * 0.45))]
    files = []
    for vname, pos in views:
        pitch, yaw = _aim(pos, c)
        files.append((vname, capture(pos, pitch, yaw, os.path.join(kit.OUT, f"{label}_{vname}.png"))))
    tiles = [Image.open(f).convert("RGB").resize((640, 360)) for _, f in files]
    sheet = Image.new("RGB", (1920, 720), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * 640, (i // 3) * 360))
    out = os.path.join(kit.OUT, f"{label}_sheet.png")
    sheet.save(out)
    small = os.path.join(kit.OUT, f"{label}_sheet_small.jpg")
    sheet.resize((1344, 504)).save(small, quality=85)
    text = (f"saved sheet {out} (row 1: front +Y, back -Y, right +X; row 2: left -X, 3/4 from +X+Y above).\n"
            f"actor box: ({mn['x']:.0f}, {mn['y']:.0f}, {mn['z']:.0f}) -> ({mx['x']:.0f}, {mx['y']:.0f}, {mx['z']:.0f})\n"
            + "\n".join(f"{v}: {f}" for v, f in files) +
            "\n\nThe sheet is attached below. If you cannot see an image, open the sheet with your vision tool NOW. "
            + LOOK_QUESTIONS)
    return text, small


def thumbs(meshes, sheet_name="parts"):
    """Asset thumbnails side by side, each with its mesh name written under it."""
    tiles = []
    for m in meshes:
        path = kit.full_path(m).split(".")[0]
        short = path.rsplit("/", 1)[-1]
        f = os.path.join(kit.OUT, f"thumb_{short}.png")
        try:
            ue.save_png(ue.call(APP, "CaptureAssetImage", {"assetPath": path}), f)
        except ue.UEError as e:
            return f"ERROR no picture of {m}: {str(e)[:200]} - check the name with kit_parts", None
        im = Image.open(f).convert("RGB")
        im = im.resize((256, round(256 * im.height / im.width)))
        tile = Image.new("RGB", (256, im.height + 30), (0, 0, 0))
        tile.paste(im, (0, 0))
        dr = ImageDraw.Draw(tile)
        name = short.replace("SM_", "")
        font = _font(18 if len(name) < 22 else 14)
        dr.text((6, im.height + 5), name, fill=(255, 255, 255), font=font)
        tiles.append(tile)
    cols = min(4, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    th = max(t.height for t in tiles)
    sheet = Image.new("RGB", (256 * cols, th * rows), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 256, (i // cols) * th))
    out = os.path.join(kit.OUT, f"{sheet_name}_sheet.png")
    sheet.save(out)
    return (f"saved {out} - each picture has its mesh name under it ({cols} per row): "
            + ", ".join(m.rsplit('/', 1)[-1] for m in meshes)), out


def gallery(names, cols=5, out_name="gallery"):
    """One labelled 3/4 photo per test copy (<name>_Test) in a grid: compare many designs at a glance."""
    tiles, missing = [], []
    font = _font(22)
    for n in names:
        actor, err = find(n + kit.TEST_SUFFIX)
        if err:
            missing.append(n)
            continue
        mn, mx = _bounds(actor)
        c = [(mn[k] + mx[k]) / 2 for k in "xyz"]
        size = max(mx["x"] - mn["x"], mx["y"] - mn["y"], (mx["z"] - mn["z"]) * 0.9)
        d = size * 1.25 + 250
        pos = (c[0] + d * 0.55, c[1] + d * 0.85, c[2] + (mx["z"] - mn["z"]) * 0.15 + 120)
        pitch, yaw = _aim(pos, c)
        f = capture(pos, pitch, yaw, os.path.join(kit.OUT, f"gallery_{n}.png"), settle=1.0)
        im = Image.open(f).convert("RGB")
        w, h = im.size
        im = im.crop((int(w * 0.18), 0, int(w * 0.82), h)).resize((480, 400))
        dr = ImageDraw.Draw(im)
        dr.rectangle((0, 368, 480, 400), fill=(0, 0, 0))
        dr.text((8, 372), n.replace("BP_", ""), fill=(255, 255, 255), font=font)
        tiles.append(im)
    if not tiles:
        return "no test copies found for: " + ", ".join(missing), None
    cols = min(cols, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    g = Image.new("RGB", (480 * cols, 400 * rows), (20, 20, 20))
    for i, t in enumerate(tiles):
        g.paste(t, ((i % cols) * 480, (i // cols) * 400))
    out = os.path.join(kit.OUT, f"{out_name}.png")
    g.save(out)
    small = os.path.join(kit.OUT, f"{out_name}_small.jpg")
    scale = min(1.0, 1600 / g.width)
    g.resize((round(g.width * scale), round(g.height * scale))).save(small, quality=85)
    text = f"saved {out}: {len(tiles)} design(s), {cols} per row, name under each picture."
    if missing:
        text += " No test copy in the open level for: " + ", ".join(missing)
    return text, small


def area(x, y, size, z=0.0, name="area"):
    """A region of the map (centre x,y in cm, `size` cm across) from straight above and from four corners:
    use it to judge a street or a whole town, not one building."""
    size = max(500.0, float(size))
    c = (float(x), float(y), float(z))
    h = size * 0.9
    r = size * 0.75
    views = [("top", (c[0], c[1] + 1.0, z + size * 1.15))]
    for vname, dx, dy in (("from_SE", 1, 1), ("from_SW", -1, 1), ("from_NW", -1, -1), ("from_NE", 1, -1)):
        views.append((vname, (c[0] + dx * r, c[1] + dy * r, z + h * 0.6)))
    files = []
    for vname, pos in views:
        pitch, yaw = _aim(pos, c)
        if vname == "top":
            pitch, yaw = -89.9, -90.0
        files.append((vname, capture(pos, pitch, yaw, os.path.join(kit.OUT, f"{name}_{vname}.png"), settle=1.0)))
    tiles = [Image.open(f).convert("RGB").resize((640, 360)) for _, f in files]
    sheet = Image.new("RGB", (1920, 720), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * 640, (i // 3) * 360))
    out = os.path.join(kit.OUT, f"{name}_sheet.png")
    sheet.save(out)
    small = os.path.join(kit.OUT, f"{name}_sheet_small.jpg")
    sheet.resize((1344, 504)).save(small, quality=85)
    return (f"saved {out} (row 1: straight down with +X right and +Y down, from south-east, from south-west; "
            f"row 2: from north-west, from north-east). Centre ({c[0]:.0f}, {c[1]:.0f}), {size:.0f} cm across.\n"
            + "\n".join(f"{v}: {f}" for v, f in files)), small
