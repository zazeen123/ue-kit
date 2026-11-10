import sys
sys.path.insert(0, '.')
import server
exec(open('test_house.py').read().split('bad = [')[0])
print(server.build_blueprint("BP_KitTest", house, test_location=[0, -30000, 0]))
print(server.look("BP_KitTest_Test"))
