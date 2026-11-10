"""Geometry, checks and guards of ue-kit, without Unreal (see conftest.offline)."""
import json

import pytest

import kit
import server

B = server.build_blueprint


def dry(parts, name="X_1", **kw):
    return B(name, parts, dry_run=True, **kw)


# ---------------------------------------------------------------- placement

def test_known_good_house_has_no_issues(offline, house):
    out = dry(house)
    assert "ISSUES: none" in out, out
    assert offline.calls == []


def test_on_puts_bottom_on_top_of_support(offline, house):
    res = {p["name"]: p for p in kit.resolve(house)}
    assert res["GroundFloor"]["box"][2] == pytest.approx(res["Plinth"]["box"][5], abs=0.2)
    assert res["Plinth"]["box"][2] == pytest.approx(0, abs=0.2)


def test_against_and_flush_sides(offline):
    parts = [{"name": "A", "mesh": "SM_House1stFloor04"},
             {"name": "Out", "mesh": "SM_HouseChimney", "place": "against:A:+X"},
             {"name": "In", "mesh": "SM_HouseChimney", "place": "flush:A:-Y"}]
    r = {p["name"]: p["box"] for p in kit.resolve(parts)}
    assert r["Out"][0] == pytest.approx(r["A"][3], abs=0.2)        # outside the +X face
    assert r["In"][1] == pytest.approx(r["A"][1], abs=0.2)         # inside, flush with the -Y face


def test_cover_scales_roof_over_walls_even_when_turned(offline):
    parts = [{"name": "GroundFloor", "mesh": "SM_House1stFloor04"},
             {"name": "Roof", "mesh": "SM_HouseRoof03", "place": "on:GroundFloor", "cover": "GroundFloor:40", "yaw": 90}]
    r = {p["name"]: p["box"] for p in kit.resolve(parts)}
    for lo, hi in ((0, 3), (1, 4)):
        assert r["Roof"][lo] <= r["GroundFloor"][lo] - 39
        assert r["Roof"][hi] >= r["GroundFloor"][hi] + 39


def test_rotation_matches_unreal_yaw(offline):
    # yaw 90 turns local +X to world +Y
    m = kit._rot_matrix(0, 90, 0)
    assert m[0][0] == pytest.approx(0, abs=1e-9) and m[0][1] == pytest.approx(1)


# ---------------------------------------------------------------- checks

def test_floating_and_sunk(offline):
    out = dry([{"name": "Wall", "mesh": "SM_CastleWall6m", "place": "at", "offset": [0, 0, 130]}])
    assert "FLOATING: Wall" in out
    out = dry([{"name": "Wall", "mesh": "SM_CastleWall6m", "place": "at", "offset": [0, 0, -200]}])
    assert "SUNK: Wall" in out


def test_roof_too_small(offline):
    out = dry([{"name": "GroundFloor", "mesh": "SM_House1stFloor02"},
               {"name": "Roof", "mesh": "SM_HouseRoof04", "place": "on:GroundFloor"},
               {"name": "Door", "mesh": "SM_Door01", "place": "flush:GroundFloor:-Y"}])
    assert "ROOF TOO SMALL: Roof does not cover GroundFloor" in out


def test_upper_storey_left_on_the_ground_overlaps(offline, house):
    house[2].pop("place")
    assert "OVERLAP: GroundFloor and UpperFloor" in dry(house) or "OVERLAP" in dry(house)


def test_door_rule_only_for_walk_in_modules(offline, house):
    no_door = [p for p in house if p["name"] != "Door"]
    assert "NO DOOR: GroundFloor" in dry(no_door)
    stall = [{"name": "Cart", "mesh": "SM_HouseChimney"}]
    out = dry(stall)
    assert "NO DOOR" not in out and "ISSUES: none" in out


def test_goods_under_a_canopy_do_not_clash(offline):
    d = kit.designs().get("BP_MarketStall_Fruit")
    if not d:
        pytest.skip("BP_MarketStall_Fruit not on file")
    assert not [i for i in kit.check(kit.resolve(d["parts"])) if i.startswith("CLASH")]


def test_every_design_on_file_still_passes(offline):
    out = kit.check_designs()
    assert ", 0 with issues" in out.splitlines()[0], out


def test_dry_run_never_measures_doorways(offline, house):
    oc = kit._read_json(kit.OPEN_CACHE)
    oc.pop("/Game/FantasyBundle/Meshes/SM_House2dFloor01.SM_House2dFloor01")
    kit._write_json(kit.OPEN_CACHE, oc)
    out = dry(house)
    assert "DOORWAYS NOT MEASURED: SM_House2dFloor01" in out
    assert 'kit_parts("SM_House2dFloor01", doorways=True)' in out
    assert offline.calls == []


# ---------------------------------------------------------------- input errors

@pytest.mark.parametrize("parts, needle", [
    ([], "parts must be a non-empty list"),
    ([{"name": "A"}], 'part "A" has no "mesh"'),
    ([{"mesh": "SM_Door01"}], 'has no "name"'),
    (["SM_Door01"], "is not a dict"),
    ([{"name": "A", "mesh": "SM_Door01", "place": "on:Nope"}], "not an earlier part"),
    ([{"name": "A", "mesh": "SM_Door01"}, {"name": "A", "mesh": "SM_Door01"}], "duplicate part name"),
    ([{"name": "A", "mesh": "SM_NoSuchMesh"}], "cannot measure SM_NoSuchMesh"),
])
def test_bad_parts_get_a_plain_error(offline, parts, needle):
    out = dry(parts)
    assert out.startswith("ERROR") and needle in out, out


def test_other_tools_reject_bad_input(offline):
    assert "not a valid regular expression" in server.kit_parts("House(")
    out = server.kit_pictures([])
    assert "ERROR meshes must be a list" in (out if isinstance(out, str) else out[0])


# ---------------------------------------------------------------- guards

@pytest.mark.parametrize("label", ["", "House", "StaticMeshActor", "_Test", "a_Test", "BP_HouseInn"])
def test_remove_actor_refuses_anything_but_a_full_test_label(offline, label):
    assert "NOT REMOVED" in server.remove_actor(label)
    assert offline.calls == []


@pytest.mark.parametrize("name, folder, ok", [
    ("BP_New", "/Game/ARPG/_Sandbox", True),
    ("BP_New", "/Game/ARPG/_Sandbox/Houses", True),
    ("BP_New", "/Game/ARPG/_SandboxEvil", False),
    ("BP_New", "/Game/ARPG/Blueprints", False),
    ("../x", "/Game/ARPG/_Sandbox", False),
    ("BP_GatefallHouse", "/Game/ARPG/Environment/Town", True),      # ue-kit built it there
    ("BP_Other", "/Game/ARPG/Environment/Town", False),
])
def test_where_a_blueprint_may_be_built(offline, name, folder, ok):
    assert (kit.build_allowed(name, folder) is None) == ok


def test_only_own_blueprints_are_replaced(offline):
    assert kit.overwrite_allowed("BP_GatefallHouse", "/Game/ARPG/Environment/Town") is None
    assert kit.overwrite_allowed("BP_KitTest", "/Game/ARPG/_Sandbox") is None            # legacy: in test_spots
    assert "will not be" in kit.overwrite_allowed("BP_SomeoneElses", "/Game/ARPG/_Sandbox")
    assert "will not be" in kit.overwrite_allowed("BP_GatefallHouse", "/Game/ARPG/_Sandbox")


def test_changed_mesh_file_invalidates_its_cached_size(offline):
    key = "/Game/FantasyBundle/Meshes/SM_Door01.SM_Door01"
    if kit._mesh_mtime(key) is None:
        pytest.skip("project content not on this machine")
    kit.bounds([key])
    c = kit._read_json(kit.CACHE)
    c["__mtime__"][key] -= 5
    kit._write_json(kit.CACHE, c)
    with pytest.raises(ValueError, match="cannot measure SM_Door01"):
        kit.bounds([key])


def test_state_files_are_valid_json(offline):
    for attr in ("CACHE", "OPEN_CACHE", "SPOTS", "REGISTRY", "DESIGNS"):
        with open(getattr(kit, attr), encoding="utf-8") as f:
            assert isinstance(json.load(f), dict)


# ---------------------------------------------------------------- autofix, get_design, kit_notes

WIDE = [{"name": "GroundFloor", "mesh": "SM_House1stFloor02"},
        {"name": "Roof", "mesh": "SM_HouseRoof04", "place": "on:GroundFloor", "offset": [0, 0, 40]},
        {"name": "Door", "mesh": "SM_Door01", "place": "flush:GroundFloor:-Y", "offset": [-143, 14, 0]}]


def test_autofix_covers_walls_lowers_roof_and_trims_steps(offline, house):
    wide = [dict(p) for p in WIDE]
    before = kit.check(kit.resolve(wide))
    assert any(i.startswith("ROOF TOO SMALL") for i in before) and any(i.startswith("FLOATING ROOF") for i in before)
    fixed, notes = kit.autofix(wide)
    after = kit.check(kit.resolve(fixed))
    assert not [i for i in after if i.split(":")[0] in ("ROOF TOO SMALL", "FLOATING ROOF")], after
    assert any("cover" in n for n in notes)
    assert wide[1].get("cover") is None                      # the caller's list is not modified

    house[5]["scale"] = [1, 1.33, 3.0]                       # steps far taller than the plinth
    assert any(i.startswith("STEPS TOO TALL") for i in kit.check(kit.resolve(house)))
    fixed, notes = kit.autofix(house)
    assert not kit.check(kit.resolve(fixed)), kit.check(kit.resolve(fixed))
    assert any(n.startswith("Steps") for n in notes)


def test_autofix_leaves_design_decisions_alone(offline, house):
    house[2].pop("place")                                    # upper storey on the ground: OVERLAP
    fixed, _ = kit.autofix(house)
    assert any(i.startswith("OVERLAP") for i in kit.check(kit.resolve(fixed)))


def test_autofix_through_the_tool_prints_the_new_parts(offline):
    out = dry([dict(p) for p in WIDE], autofix=True)
    assert "AUTO-FIXED" in out and "PARTS NOW" in out and "ROOF TOO SMALL" not in out, out


def test_get_design(offline):
    assert "design(s) on file" in server.get_design()
    out = server.get_design("BP_GatefallHouse")
    parts = json.loads(out.split("\n")[-1])
    assert parts[0]["name"] == "Plinth"
    assert "did you mean" in server.get_design("Gatefall")


def test_kit_notes_writes_a_table(offline):
    text, path = kit.kit_notes("/Game/FantasyBundle/Meshes", "House1stFloor|House2dFloor|HouseBase")
    if path is None:
        pytest.skip("project content not on this machine")
    body = open(path, encoding="utf-8").read()
    assert "| `SM_HouseBase01` |" in body and "What stacks on what" in body
    assert offline.calls == []


# ---------------------------------------------------------------- other packs, dressing, budget

def test_bare_names_resolve_across_packs(offline):
    assert kit.full_path("SM_Door01") == "/Game/FantasyBundle/Meshes/SM_Door01.SM_Door01"
    assert kit.full_path("/Game/X/SM_A") == "/Game/X/SM_A.SM_A"
    idx = kit.mesh_index()
    if not idx:
        pytest.skip("project content not on this machine")
    other = next((n for n, p in idx.items() if len(p) == 1 and "FantasyBundle" not in p[0]), None)
    assert other and kit.full_path(other) == idx[other][0] + "." + other
    twice = next((n for n, p in idx.items() if len(p) > 1), None)
    if twice:
        with pytest.raises(ValueError, match="asset packs"):
            kit.full_path(twice)
    assert "FantasyBundle" in kit.kit_packs()


def test_dress_adds_props_without_new_issues(offline, house):
    before = set(kit.check(kit.resolve(house)))
    out, notes = kit.dress(house, count=3, seed=7)
    assert len(out) == len(house) + 3 and len(notes) == 3
    assert set(kit.check(kit.resolve(out))) == before
    res = {p["name"]: p for p in kit.resolve(out)}
    door = res["Door"]["box"]
    for p in out[len(house):]:
        b = res[p["name"]]["box"]
        assert b[2] == pytest.approx(0, abs=1)                       # on the ground
        assert not (b[4] > door[1] and b[0] < door[3] and door[0] < b[3] and b[1] > door[1] - 200), p   # not at the door
    assert kit.dress(house, 3, 7)[0] == out                           # same seed, same result
    assert kit.dress(house, 3, 8)[0] != out


def test_budget_counts_parts_and_lights(offline, monkeypatch):
    monkeypatch.setattr(kit, "mesh_stats", lambda meshes: {kit.full_path(m): [1000, False] for m in meshes})
    out = kit.budget(["BP_GatefallHouse", "BP_Nope"])
    assert "BP_GatefallHouse | 7 | 7 | 0 | 7,000 | 7,000" in out and "BP_Nope | not on file" in out


def test_load_on_a_wagon_bed_does_not_clash(offline):
    parts = [{"name": "Wagon", "mesh": "SM_Wagon01"},
             {"name": "Keg", "mesh": "SM_Barrel01", "place": "inside:Wagon", "offset": [0, -60, 80], "scale": 0.5}]
    assert not [i for i in kit.check(kit.resolve(parts)) if i.startswith("CLASH")]
    two = [{"name": "KegA", "mesh": "SM_Barrel01"}, {"name": "KegB", "mesh": "SM_Barrel01", "offset": [10, 0, 0]}]
    assert [i for i in kit.check(kit.resolve(two)) if i.startswith("CLASH")]        # real clashes still fire
