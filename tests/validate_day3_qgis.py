"""Run in QGIS Python. All network coordinates in this test are synthetic."""
import sys
from pathlib import Path

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProcessingContext, QgsProject, QgsVectorLayer)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis"))
from day3_research import acs_values, origins_for, pedestrian_access, service_area

app = QgsApplication([], False)
app.initQgis()
sys.path.append(str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))
from processing.core.Processing import Processing
Processing.initialize()


def add_line(layer, coordinates, attributes=()):
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*point) for point in coordinates]))
    feature.setAttributes(list(attributes))
    layer.dataProvider().addFeatures([feature])
    layer.updateExtents()


def main():
    crs = QgsCoordinateReferenceSystem("EPSG:26914")
    reference = (700000, 3600000)
    x, y = reference
    project = QgsProject.instance()
    project.setCrs(crs)
    project.setEllipsoid("NONE")
    context = QgsProcessingContext()
    context.setProject(project)
    context.setEllipsoid("NONE")
    corridor = QgsVectorLayer("LineString?crs=EPSG:26914", "Synthetic corridor", "memory")
    add_line(corridor, [(x, y), (x + 100, y)])
    origins = origins_for(corridor, 200)
    assert origins.featureCount() == 2
    network = QgsVectorLayer("LineString?crs=EPSG:26914&field=direction:string", "Synthetic network", "memory")
    add_line(network, [(x - 2000, y), (x + 2000, y)], ("both",))
    add_line(network, [(x + 500, y - 100), (x + 500, y + 100)], ("both",))
    reach, rejected = service_area(network, origins, context, 10, 4.8, 10)
    assert rejected == 0
    assert abs(reach.length() - 1700) < 0.01, reach.length()
    assert abs(reach.boundingBox().height()) < 0.01, "Non-noded crossing became routable"
    assert pedestrian_access({"highway":"residential"})
    assert not pedestrian_access({"highway":"footway","foot":"private"})
    assert not pedestrian_access({"highway":"motorway"})
    assert pedestrian_access({"highway":"path","foot":"yes","access":"private"})
    try:
        acs_values([["B01003_001E", "B01003_001M", "state", "county", "tract", "block group"],
                    ["100", "-1", "48", "113", "000001", "1"]])
    except ValueError:
        pass
    else:
        raise AssertionError("Bad ACS margin must be rejected")
    print("QGIS Day 3 regression checks passed", flush=True)


if __name__ == "__main__":
    main()
