"""Offline fixtures: every editor call is blocked and the state files are copies, so a test run can never
change Unreal or the real caches. Mesh sizes come from the committed bounds_cache.json."""
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kit  # noqa: E402
import server  # noqa: E402
import ue_client as ue  # noqa: E402

STATE = (("CACHE", "bounds_cache.json"), ("OPEN_CACHE", "openings_cache.json"), ("SPOTS", "test_spots.json"),
         ("REGISTRY", "designs_registry.json"), ("DESIGNS", "designs.json"))


@pytest.fixture()
def offline(tmp_path, monkeypatch):
    """kit/server with the editor unreachable. `offline.calls` lists every attempted editor call."""
    calls = []

    def blocked(*a, **k):
        calls.append(a[:2])
        raise ue.UEError("editor call blocked by the offline test")

    # server.py reloads kit/ue_client when their files change; pin the modules the tests patch
    monkeypatch.setattr(server, "_fresh", lambda: None)
    monkeypatch.setattr(server, "kit", kit)
    monkeypatch.setattr(server, "ue", ue)
    import shots
    import town
    monkeypatch.setattr(server, "shots", shots)
    monkeypatch.setattr(server, "town", town)
    monkeypatch.setattr(town, "PLAN", str(tmp_path / "town_plan.json"))
    monkeypatch.setattr(ue, "call", blocked)
    monkeypatch.setattr(ue, "batch", blocked)
    for attr, fn in STATE:
        src = os.path.join(ROOT, fn)
        dst = tmp_path / fn
        if os.path.exists(src):
            shutil.copy(src, dst)
        monkeypatch.setattr(kit, attr, str(dst))
    monkeypatch.setattr(kit, "ACTIONS", str(tmp_path / "actions.log"))
    monkeypatch.setattr(kit, "OUT", str(tmp_path))

    class Ctx:
        pass
    ctx = Ctx()
    ctx.calls, ctx.tmp = calls, tmp_path
    return ctx


HOUSE = [
    {"name": "Plinth", "mesh": "SM_HouseBase01"},
    {"name": "GroundFloor", "mesh": "SM_House1stFloor04", "place": "on:Plinth"},
    {"name": "UpperFloor", "mesh": "SM_House2dFloor01", "place": "on:GroundFloor", "offset": [0, 0, -7]},
    {"name": "Roof", "mesh": "SM_HouseRoof01", "place": "on:UpperFloor", "offset": [0, 0, -10]},
    {"name": "Door", "mesh": "SM_Door01", "place": "flush:GroundFloor:+Y", "offset": [0, -14, 0]},
    {"name": "Steps", "mesh": "SM_CastleStairs3m", "place": "against:Plinth:+Y", "scale": [1, 1.33, 1.33]},
    {"name": "Chimney", "mesh": "SM_HouseChimney", "place": "on:UpperFloor", "offset": [-120, -220, -20],
     "scale": [1.4, 1.4, 3.6]},
]


@pytest.fixture()
def house():
    return [dict(p) for p in HOUSE]
