"""Build the toolkit's DART map geometry from the reviewed improvement-map fixtures."""
import argparse
from pathlib import Path
import json
from math import cos, radians

base=Path(__file__).resolve().parents[1]/"blender/assets"
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("improvement_map",type=Path,help="Local improvement-map checkout")
src=parser.parse_args().improvement_map/"src/data/rails"
fixture=json.loads((base/"dart-downtown-fixture.json").read_text())
tre=json.loads((base/"tre-fixture.json").read_text())
def smooth(points):
    # Round local vertices while keeping junction endpoints fixed.
    for _ in range(2):
        points=[points[0], *[[round(a+(b-a)*q,8) for a,b in zip(p,r)]
                 for p,r in zip(points,points[1:]) for q in (.25,.75)],points[-1]]
    return points
def dist(a,b):
    return ((a[0]-b[0])*cos(radians(a[1])))**2+(a[1]-b[1])**2
def replace(path, chunks):
    start=min(range(len(path)),key=lambda i:dist(path[i],chunks[0][0]))
    end=min(range(len(path)),key=lambda i:dist(path[i],chunks[-1][-1]))
    if end<start:
        return replace(path[::-1],chunks)[::-1]
    assert start<end
    return [*smooth(path[:start+1]),*(p for chunk in chunks for p in smooth(chunk)),*smooth(path[end:])]
keys={"RED":("south_pair","trunk","north_trio","north_pair"),
      "BLUE":("south_pair","trunk","north_trio","blue_branch"),
      "GREEN":("west_pair","trunk","green_east"),
      "ORANGE":("west_pair","trunk","north_trio","north_pair")}
features=[]
for key,part in (("GREEN",0),("ORANGE",3),("RED",0),("BLUE",0),("SILVER",0),("TRE",0)):
    p,=src.glob(f"DALLAS AREA RAPID TRANSIT - {key} *.geojson")
    original=json.loads(p.read_text(encoding="utf-8-sig"))["features"][0]
    path=original["geometry"]["coordinates"][part]
    if key in keys:
        line=replace(path,[fixture[k] for k in keys[key]])
    elif key=="TRE":
        line=replace(tre["coordinates"],[tre["spine"]])
    else:
        line=smooth(path)
    line=[p for i,p in enumerate(line) if i==0 or line[i-1]!=p]
    props={"id":key,"name":key,"source":"DallasUrbanists/improvement-map, "+p.name}
    if key in keys:props["alignment_fixture"]=fixture["source"]
    elif key=="TRE":props["alignment_fixture"]=tre["source"]
    features.append({"type":"Feature","properties":props,"geometry":{"type":"LineString","coordinates":line}})
(base/"dart-rail.geojson").write_text(json.dumps({"type":"FeatureCollection","features":features},separators=(",",":"))+"\n")
