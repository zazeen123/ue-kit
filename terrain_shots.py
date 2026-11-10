"""Terrain photos of L_Gatefall from fixed viewpoints into one sheet.
python terrain_shots.py out.png"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image  # noqa: E402

import ue_client as ue  # noqa: E402

APP = "EditorToolset.EditorAppToolset"
VIEWS = [("overview_south", (0, 140000, 90000), -32, -90),
         ("river_valley", (55000, 40000, 6000), -12, -100),
         ("town_from_river", (38000, 6000, 2500), -6, 180),
         ("north_mountains", (0, -30000, 4000), 8, -95)]


def main(out, settle=30):
    time.sleep(settle)          # let shaders / virtual textures catch up after a material change
    files = []
    for n, (x, y, z), p, yw in VIEWS:
        a = {"captureTransform": {"location": {"x": x, "y": y, "z": z}, "rotation": {"pitch": p, "yaw": yw, "roll": 0}},
             "annotations": {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0,
                             "classFilter": None, "maxLabels": 0}, "bShowUI": False}
        ue.call(APP, "CaptureViewport", a)
        ue.call(APP, "CaptureViewport", a)
        f = rf"C:\UE\logs\ue-kit\terrain_{n}.png"
        ue.save_png(ue.call(APP, "CaptureViewport", a), f)
        files.append(f)
    ims = [Image.open(f).convert("RGB").resize((960, 540)) for f in files]
    g = Image.new("RGB", (1920, 1080), (20, 20, 20))
    for i, im in enumerate(ims):
        g.paste(im, ((i % 2) * 960, (i // 2) * 540))
    g.save(out)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1])
