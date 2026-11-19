"""No external dependencies; basic fixture and metadata validation."""
import json
from pathlib import Path

p = Path(__file__).parent / "fixtures" / "illustrative-neighborhood.geojson"
data = json.loads(p.read_text(encoding="utf-8"))
assert data["type"] == "FeatureCollection"
assert data["features"]
for feature in data["features"]:
    assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert "SYNTHETIC" in feature["properties"]["source"]
    for ring in feature["geometry"]["coordinates"]:
        assert len(ring) >= 4
        assert ring[0] == ring[-1]
print("Fixture validated:", p)
