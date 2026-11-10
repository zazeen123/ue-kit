"""One 3/4 photo per house test copy, labelled, in a grid PNG.
python gallery.py out.png BP_A BP_B ...   (labels "<name>_Test" must exist in the open level)"""
import math
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import ue_client as ue  # noqa: E402

S = "editor_toolset.toolsets.scene.SceneTools"
A = "editor_toolset.toolsets.actor.ActorTools"
APP = "EditorToolset.EditorAppToolset"
OUT = r"C:\UE\logs\ue-kit\gallery"
os.makedirs(OUT, exist_ok=True)


def shot(name):
    label = name + "_Test"
    found = ue.call(S, "find_actors", {"name": label, "tag": "", "collision_channels": []})["returnValue"]
    if not found:
        return None
    b = ue.call(A, "get_actor_bounds", {"actor": found[0]})["returnValue"]
    mn, mx = b["min"], b["max"]
    mn["z"] = max(mn["z"], 0.0)
    c = [(mn[k] + mx[k]) / 2 for k in "xyz"]
    size = max(mx["x"] - mn["x"], mx["y"] - mn["y"], (mx["z"] - mn["z"]) * 0.9)
    d = size * 1.25 + 250
    # from the front-right (+X +Y), a little above eye level, looking at the middle of the house
    x, y, z = c[0] + d * 0.55, c[1] + d * 0.85, c[2] + (mx["z"] - mn["z"]) * 0.15 + 120
    yaw = math.degrees(math.atan2(c[1] - y, c[0] - x))
    pitch = -math.degrees(math.atan2(z - c[2], math.hypot(x - c[0], y - c[1])))
    # move the editor camera there first and let a few frames render: right after a long camera jump the
    # previous frame's occlusion results hide whole houses (their cached shadows still show)
    ue.call(APP, "SetCameraTransform", {"transform": {"location": {"x": x, "y": y, "z": z},
                                                      "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0}}})
    time.sleep(1.5)
    args = {"captureTransform": {"location": {"x": x, "y": y, "z": z},
                                 "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0}},
            "annotations": {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0,
                            "classFilter": None, "maxLabels": 0}, "bShowUI": False}
    ue.call(APP, "CaptureViewport", args)      # warm-up: Nanite culls against the previous frame's depth
    r = ue.call(APP, "CaptureViewport", args)
    f = os.path.join(OUT, name + ".png")
    ue.save_png(r, f)
    return f


def main(out, names, cols=5):
    tiles = []
    for n in names:
        f = shot(n)
        im = Image.open(f).convert("RGB") if f else Image.new("RGB", (1280, 720), (40, 0, 0))
        w, h = im.size
        im = im.crop((int(w * 0.18), 0, int(w * 0.82), h)).resize((480, 400))
        dr = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
        dr.rectangle((0, 368, 480, 400), fill=(0, 0, 0))
        dr.text((8, 372), n.replace("BP_", ""), fill=(255, 255, 255), font=font)
        tiles.append(im)
    rows = math.ceil(len(tiles) / cols)
    g = Image.new("RGB", (480 * cols, 400 * rows), (20, 20, 20))
    for i, t in enumerate(tiles):
        g.paste(t, ((i % cols) * 480, (i // cols) * 400))
    g.save(out)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
