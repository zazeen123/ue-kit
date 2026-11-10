"""Town planning without Unreal: which design on which lot, turned which way."""
import os

import pytest

import kit
import town

pytestmark = pytest.mark.skipif(not os.path.exists(town.LAYOUT), reason="project layout not on this machine")


@pytest.fixture()
def layout():
    return town.load_layout()


def test_footprint_knows_where_the_door_is(offline):
    f = town.footprint("BP_GatefallHouse")
    assert f["door"] == "+Y" and f["walk_in"]
    assert f["core"][2] - f["core"][0] < f["box"][2] - f["box"][0] + 1        # walls are within the whole
    assert not town.footprint("BP_MarketStall_Fruit")["walk_in"]


@pytest.mark.parametrize("door, face, yaw", [("+Y", "+Y", 0), ("+Y", "+X", 270), ("+Y", "-Y", 180), ("+Y", "-X", 90),
                                               ("-Y", "+Y", 180), ("+X", "+Y", 90)])
def test_yaw_turns_the_door_to_the_road(door, face, yaw):
    got = town._yaw_for(door, face)
    assert got == yaw
    dx, dy = town._rot(*town.DIRS[door], got)
    assert (round(dx), round(dy)) == town.DIRS[face]


def test_every_house_lot_gets_a_design_that_fits_and_faces_a_road(offline, layout):
    rows, issues = town.plan(layout)
    assert len(rows) == 12 and not issues, issues
    for r in rows:
        w, lot = r["walls"], r["lot_box"]
        assert w[0] >= lot[0] - 1 and w[1] >= lot[1] - 1 and w[2] <= lot[2] + 1 and w[3] <= lot[3] + 1
        assert town.footprint(r["design"])["walk_in"]
        # the door side, turned by yaw, is the side that faces the road
        dx, dy = town._rot(*town.DIRS[town.footprint(r["design"])["door"]], r["yaw"])
        assert (round(dx), round(dy)) == town.DIRS[r["faces"]]
    assert len({r["design"] for r in rows}) >= 8                         # variety, not one house twelve times
    assert offline.calls == []


def test_same_seed_same_town_and_assign_is_respected(offline, layout):
    a, _ = town.plan(layout, seed=3)
    b, _ = town.plan(layout, seed=3)
    assert [(r["lot"], r["design"], r["yaw"]) for r in a] == [(r["lot"], r["design"], r["yaw"]) for r in b]
    rows, issues = town.plan(layout, assign={"36": "BP_HouseBakery"}, lots=[36, 37])
    assert rows[0]["design"] == "BP_HouseBakery" and len(rows) == 2 and not issues


def test_origin_moves_everything(offline, layout):
    a, _ = town.plan(layout, lots=[44])
    b, _ = town.plan(layout, lots=[44], origin=(0, 21000))
    assert b[0]["loc"][1] == pytest.approx(a[0]["loc"][1] + 21000) and b[0]["yaw"] == a[0]["yaw"]


def test_stalls_get_stall_designs(offline, layout):
    rows, issues = town.plan(layout, types=("stall",), lots=[12, 13, 14, 15, 16, 17, 18, 19])
    assert len(rows) == 8 and all("MarketStall" in r["design"] for r in rows)
    assert not [i for i in issues if i.startswith("ON THE ROAD")], issues       # the market square is not a road


def test_survey_flags_occupied_and_steep_and_fills_a_slope(offline, layout, monkeypatch):
    rows, _ = town.plan(layout, lots=[36, 37, 38])

    def fake(points):                 # 5 inside + 4 outside points per lot
        out = []
        for i in range(len(points) // 9):
            inside = {0: [0, 0, 0, 0, 600], 1: [0, 40, 80, 120, 60], 2: [0, 100, 200, 300, 150]}[i]
            out += inside + ([0, 100, 200, 300] if i == 2 else [0, 0, 0, 0])      # lot 2 is on a hillside
        return out
    monkeypatch.setattr(town, "ground", fake)
    monkeypatch.setattr(town, "own_lots", lambda: set())
    issues = town.survey(rows)
    assert rows[0]["flag"] == "OCCUPIED" and any("LOT OCCUPIED" in i for i in issues)
    assert rows[1].get("flag") is None and rows[1]["z"] == 120 and rows[1]["fill"] == 120
    assert rows[2]["flag"] == "STEEP"
    plan = town.place(rows, dry_run=True)
    labels = [j["label"] for j in plan["jobs"]]
    assert labels == [f"Town_37_{rows[1]['design']}", "Town_37_Foundation"]
    f = plan["jobs"][1]
    assert f["z"] == pytest.approx(120 - 140) and f["sz"] > 1


def test_placing_is_refused_outside_a_test_map(offline, layout, monkeypatch):
    rows, _ = town.plan(layout, lots=[36])
    rows[0]["z"] = 0.0
    monkeypatch.setattr(kit, "current_level", lambda: "/Game/ARPG/Maps/L_Gatefall")
    assert "NOT PLACED" in town.place(rows, dry_run=False)["error"]
    assert "NOT CLEARED" in town.clear()
    assert offline.calls == []


def test_own_earlier_placement_is_not_an_occupied_lot(offline, layout, monkeypatch):
    rows, _ = town.plan(layout, lots=[36])
    monkeypatch.setattr(town, "ground", lambda pts: [500, 500, 500, 500, 600, 0, 0, 0, 0])
    monkeypatch.setattr(town, "own_lots", lambda: {36})
    assert town.survey(rows) == [] and rows[0].get("flag") is None and rows[0]["z"] == 0
    monkeypatch.setattr(town, "own_lots", lambda: set())
    rows, _ = town.plan(layout, lots=[36])
    assert any("LOT OCCUPIED" in i for i in town.survey(rows))
