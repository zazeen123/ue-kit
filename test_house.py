import sys, json
sys.path.insert(0, '.')
import server
house = [
 {"name":"Plinth","mesh":"SM_HouseBase01"},
 {"name":"GroundFloor","mesh":"SM_House1stFloor04","place":"on:Plinth"},
 {"name":"UpperFloor","mesh":"SM_House2dFloor01","place":"on:GroundFloor","offset":[0,0,-7]},
 {"name":"Roof","mesh":"SM_HouseRoof01","place":"on:UpperFloor","offset":[0,0,-10]},
 {"name":"Door","mesh":"SM_Door01","place":"flush:GroundFloor:+Y","offset":[0,-14,0]},
 {"name":"Steps","mesh":"SM_CastleStairs3m","place":"against:Plinth:+Y","scale":[1,1.33,1.33]},
 {"name":"Chimney","mesh":"SM_HouseChimney","place":"on:UpperFloor","offset":[-120,-220,140],"scale":[1.4,1.4,2.2]},
]
bad = [
 {"name":"Wall","mesh":"SM_CastleWall6m","place":"at","offset":[0,0,130]},
 {"name":"Roof","mesh":"SM_HouseRoof01","place":"at","offset":[0,0,450]},
]
print(server.build_blueprint("BP_KitTest", house, dry_run=True)); print()
print(server.build_blueprint("BP_KitTest", bad, dry_run=True))
