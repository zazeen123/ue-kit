import sys, json
sys.path.insert(0, '.')
import server
hermes = [
  {"mesh": "SM_HouseBase01", "name": "Plinth"},
  {"mesh": "SM_House1stFloor02", "name": "GroundFloor", "place": "on:Plinth"},
  {"mesh": "SM_House2dFloor01", "name": "UpperFloor", "offset": [0, 0, -7], "place": "on:GroundFloor"},
  {"cover": "GroundFloor:50", "mesh": "SM_HouseRoof03", "name": "Roof", "offset": [0, 0, -10], "place": "on:UpperFloor"},
  {"mesh": "SM_Door01", "name": "Door", "offset": [0, -14, 0], "place": "flush:GroundFloor:+Y"},
  {"mesh": "SM_CastleStairs3m", "name": "Steps", "place": "against:Plinth:+Y", "scale": [1, 1.33, 1.33]},
  {"mesh": "SM_HouseChimney", "name": "Chimney", "offset": [-100, -180, 140], "place": "on:UpperFloor", "scale": [1.4, 1.4, 2.2]},
]
exec(open('test_house.py').read().split('bad = [')[0].split('import server')[1])
r = server.build_blueprint("X", hermes, dry_run=True); print(r[r.index('ISSUES'):]); print()
r = server.build_blueprint("X", house, dry_run=True); print(r[r.index('ISSUES'):]); print()
print(server.kit_parts("House1stFloor", doorways=True))
