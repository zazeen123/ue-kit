"""Claude's house designs for MyHeadLine (FantasyBundle kit), built with ue-kit.
python designs_claude.py [dry|build] [name ...]"""
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
import server  # noqa: E402

FOLDER = "/Game/ARPG/_Sandbox/Houses"
CHIMNEY = dict(mesh="SM_HouseChimney", scale=[1.4, 1.4, 3.6])

D = {}

# 1. narrow two-storey on a stone plinth (the original BP_GatefallHouse, chimney fixed)
D["BP_GatefallHouse"] = [
    dict(name="Plinth", mesh="SM_HouseBase01"),
    dict(name="GroundFloor", mesh="SM_House1stFloor04", place="on:Plinth"),
    dict(name="UpperFloor", mesh="SM_House2dFloor01", place="on:GroundFloor", offset=[0, 0, -7]),
    dict(name="Roof", mesh="SM_HouseRoof01", place="on:UpperFloor", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[0, -14, 0]),
    dict(name="Steps", mesh="SM_CastleStairs3m", place="against:Plinth:+Y", scale=[1, 1.33, 1.33]),
    dict(name="Chimney", place="on:UpperFloor", offset=[-120, -220, -20], **CHIMNEY),
]

# 2. single-storey longhouse: three modules in a row, door in the middle one, one long roof
D["BP_HouseLonghouse"] = [
    dict(name="MidFloor", mesh="SM_House1stFloor04"),
    dict(name="WestFloor", mesh="SM_House1stFloor01", place="against:MidFloor:-X"),
    dict(name="EastFloor", mesh="SM_House1stFloor03", place="against:MidFloor:+X"),
    dict(name="Roof", mesh="SM_HouseRoof03", place="on:WestFloor+MidFloor+EastFloor", yaw=90,
         cover="WestFloor+MidFloor+EastFloor:45", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:MidFloor:+Y", offset=[0, -14, 0]),
    dict(name="Chimney", place="on:EastFloor", offset=[60, -150, 60], **CHIMNEY),
]

# 3. merchant house: wide stone-and-timber ground floor, two narrow modules above, one roof
D["BP_HouseMerchant"] = [
    dict(name="GroundFloor", mesh="SM_House1stFloor02", yaw=180),
    dict(name="UpperFloorW", mesh="SM_House1stFloor01", place="on:GroundFloor", offset=[-155, 0, 0]),
    dict(name="UpperFloorE", mesh="SM_House1stFloor03", place="on:GroundFloor", offset=[155, 0, 0]),
    dict(name="Roof", mesh="SM_HouseRoof02", place="on:UpperFloorW+UpperFloorE", cover="UpperFloorW+UpperFloorE:45",
         offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[143, -14, 0]),
    dict(name="Chimney", place="on:UpperFloorW+UpperFloorE", offset=[-200, -200, 60], **CHIMNEY),
]

# 4. pair: two narrow plinth houses with a 2 m alley between them (their overhangs and roofs need it)
pair = []
for side, dx in (("A", 0), ("B", 1)):
    base = f"Plinth{side}"
    pair += [
        dict(name=base, mesh="SM_HouseBase01", **({} if side == "A" else {"place": "against:PlinthA:+X", "offset": [200, 0, 0]})),
        dict(name=f"GroundFloor{side}", mesh="SM_House1stFloor04", place=f"on:{base}"),
        dict(name=f"UpperFloor{side}", mesh="SM_House2dFloor01", place=f"on:GroundFloor{side}", offset=[0, 0, -7]),
        dict(name=f"Roof{side}", mesh="SM_HouseRoof01" if side == "A" else "SM_HouseRoof02",
             place=f"on:UpperFloor{side}", offset=[0, 0, -10]),
        dict(name=f"Door{side}", mesh="SM_Door01", place=f"flush:GroundFloor{side}:+Y", offset=[0, -14, 0]),
        dict(name=f"Steps{side}", mesh="SM_CastleStairs3m", place=f"against:{base}:+Y", scale=[1, 1.33, 1.33]),
    ]
D["BP_HousePair"] = pair

# 5. tower house: three plain storeys of the same width stacked straight up, steep short roof
D["BP_HouseTower"] = [
    dict(name="GroundFloor", mesh="SM_House1stFloor04"),
    dict(name="SecondFloor", mesh="SM_House1stFloor01", place="on:GroundFloor"),
    dict(name="ThirdFloor", mesh="SM_House1stFloor03", place="on:SecondFloor"),
    dict(name="Roof", mesh="SM_HouseRoof01", place="on:ThirdFloor", cover="ThirdFloor:40", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[0, -14, 0]),
    dict(name="WindowW", mesh="SM_Window01", place="against:SecondFloor:-X", yaw=90, offset=[3, 0, 90]),
    dict(name="WindowE", mesh="SM_Window01", place="against:ThirdFloor:+X", yaw=90, offset=[-3, 0, 90]),
    dict(name="Chimney", place="on:ThirdFloor", offset=[0, -200, 0], **CHIMNEY),
]

# 6. workshop: one wide storey with its doorway on the side, low roof, open lean-to with a cart
D["BP_HouseWorkshop"] = [
    dict(name="GroundFloor", mesh="SM_House1stFloor05", yaw=-90),
    dict(name="Roof", mesh="SM_HouseRoof04", place="on:GroundFloor", cover="GroundFloor:50", offset=[0, 0, -8]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[145, -14, 0]),
    dict(name="WoodPile", mesh="SM_WoodChunks02", place="against:GroundFloor:+X", scale=0.6),
    dict(name="Cart", mesh="SM_Wagon02", place="against:GroundFloor:-X", yaw=90, scale=0.65),
    dict(name="Chimney", place="on:GroundFloor", offset=[100, -120, 40], **CHIMNEY),
]

# 7. tall house: three storeys, the two upper ones overhanging, brackets under the first overhang
D["BP_HouseTall"] = [
    dict(name="GroundFloor", mesh="SM_House1stFloor04"),
    dict(name="SecondFloor", mesh="SM_House2dFloor01", place="on:GroundFloor", offset=[0, 0, -7]),
    dict(name="ThirdFloor", mesh="SM_House2dFloor01", place="on:SecondFloor", offset=[0, 0, -7]),
    dict(name="Roof", mesh="SM_HouseRoof03", place="on:ThirdFloor", cover="ThirdFloor:45", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[0, -14, 0]),
    dict(name="BracketE", mesh="SM_HouseWoodSupport01", yaw=180, place="against:GroundFloor:+X", offset=[0, 0, 245]),
    dict(name="BracketW", mesh="SM_HouseWoodSupport01", place="against:GroundFloor:-X", offset=[0, 0, 245]),
    dict(name="Chimney", place="on:ThirdFloor", offset=[-120, -220, -20], **CHIMNEY),
]

# 8. stone gatehouse-style store: castle walls around a small yard building, grated gate as the door
D["BP_HouseStoneStore"] = [
    dict(name="Base", mesh="SM_FloorCastle01"),
    dict(name="WallBack", mesh="SM_CastleWall6m", place="flush:Base:-Y", yaw=180, offset=[-150, 0, 0]),
    dict(name="WallBack2", mesh="SM_CastleWall6m", place="flush:Base:-Y", yaw=180, offset=[150, 0, 0]),
    dict(name="WallWest", mesh="SM_CastleWall6m", place="flush:Base:-X", yaw=90, offset=[0, -150, 0]),
    dict(name="WallWest2", mesh="SM_CastleWall6m", place="flush:Base:-X", yaw=90, offset=[0, 150, 0]),
    dict(name="WallEast", mesh="SM_CastleWall6m", place="flush:Base:+X", yaw=-90, offset=[0, -150, 0]),
    dict(name="WallEast2", mesh="SM_CastleWall6m", place="flush:Base:+X", yaw=-90, offset=[0, 150, 0]),
    dict(name="WallFront", mesh="SM_CastleWall6m", place="flush:Base:+Y", offset=[-150, 0, 0]),
    dict(name="DoorGate", mesh="SM_CastleGate", place="flush:Base:+Y", offset=[150, -18, 0], scale=[1, 1, 0.75]),
    dict(name="Roof", mesh="SM_HouseRoof03", place="on:WallBack+WallFront+WallWest+WallEast",
         cover="Base:30", offset=[0, 0, -10]),
]

# 9. small cottage on a plinth with a porch roof over the door on two posts
D["BP_HousePorch"] = [
    dict(name="Plinth", mesh="SM_HouseBase01"),
    dict(name="GroundFloor", mesh="SM_House1stFloor04", place="on:Plinth"),
    dict(name="Roof", mesh="SM_HouseRoof01", place="on:GroundFloor", cover="GroundFloor:45", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[0, -14, 0]),
    dict(name="Steps", mesh="SM_CastleStairs3m", place="against:Plinth:+Y", scale=[1, 1.33, 1.33]),
    dict(name="PostL", mesh="SM_WoodBeam3m", place="against:Plinth:+Y", offset=[-110, 100, 0], scale=[1, 1, 1.05]),
    dict(name="PostR", mesh="SM_WoodBeam3m", place="against:Plinth:+Y", offset=[110, 100, 0], scale=[1, 1, 1.05]),
    dict(name="PorchRoof", mesh="SM_HouseRoof04", yaw=90, place="flush:GroundFloor:+Y", offset=[0, 160, 300],
         scale=[0.7, 0.4, 0.5]),
    dict(name="Chimney", place="on:GroundFloor", offset=[0, -230, 120], **CHIMNEY),
]

# 10. barn: wide floor with its big doorway at the back turned to the front, low roof, hay wagon
D["BP_HouseBarn"] = [
    dict(name="GroundFloor", mesh="SM_House1stFloor02", yaw=180),
    dict(name="SideFloor", mesh="SM_House1stFloor03", place="against:GroundFloor:-X"),
    dict(name="Roof", mesh="SM_HouseRoof03", yaw=90, place="on:GroundFloor+SideFloor",
         cover="GroundFloor+SideFloor:45", offset=[0, 0, -10]),
    dict(name="Door", mesh="SM_Door01", place="flush:GroundFloor:+Y", offset=[143, -14, 0]),
    dict(name="Wagon", mesh="SM_Wagon01", place="against:GroundFloor:+Y", offset=[-200, 120, 0], scale=0.65),
]

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry"
    names = sys.argv[2:] or list(D)
    for n in names:
        folder = "/Game/ARPG/Environment/Town" if n == "BP_GatefallHouse" else FOLDER
        r = server.build_blueprint(n, D[n], folder=folder, dry_run=(mode == "dry"))
        r = r[0] if isinstance(r, list) else r          # a clean build also returns the photo sheet
        head = r.split("\n")[0 if mode == "dry" else 1]
        print(f"=== {n}: {head}")
        print(r[r.index("ISSUES"):])
