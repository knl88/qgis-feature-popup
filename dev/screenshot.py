"""Headless smoke test: builds a canvas with sample layers, clicks, and saves screenshots."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import *
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QPoint, QSize
from qgis.PyQt.QtGui import QColor, QImage, QPalette
from qgis.PyQt.QtWidgets import QApplication

app = QgsApplication([], True)
app.initQgis()
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fp"
os.makedirs(out, exist_ok=True)

img_path = os.path.join(out, "photo.png")
img = QImage(640, 420, QImage.Format.Format_RGB32); img.fill(QColor("#6aa5d8")); img.save(img_path)

poly = QgsVectorLayer("Polygon?crs=EPSG:3857&field=name:string&field=area_km2:double&field=type:string"
                      "&field=population:integer&field=website:string&field=notes:string&field=empty:string", "Municipalities", "memory")
f = QgsFeature(poly.fields())
f.setGeometry(QgsGeometry.fromWkt("POLYGON((1180000 8370000, 1220000 8370000, 1220000 8400000, 1180000 8400000, 1180000 8370000))"))
f.setAttributes(["Oslo", 454.123456, "Municipality", 709037, "https://www.oslo.kommune.no",
                 "Capital of Norway; a_very_long_token_without_spaces_that_should_wrap_nicely_in_the_popup_123456", None])
poly.dataProvider().addFeatures([f])
poly.setDisplayExpression('"name"')
poly.setFieldAlias(1, "Area (km²)")
poly.setEditorWidgetSetup(2, QgsEditorWidgetSetup("ValueMap", {"map": [{"Municipality": "Municipality"}, {"County": "County"}]}))

pts = QgsVectorLayer("Point?crs=EPSG:4326&field=station:string&field=depth_m:double&field=photo:string&field=sampled:date", "Sampling stations", "memory")
feats = []
for i, (x, y) in enumerate([(10.75, 59.91), (10.7505, 59.9101), (10.7495, 59.9099)]):
    g = QgsFeature(pts.fields()); g.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    g.setAttributes([f"NIVA-{100+i}", 12.5 + i, img_path if i == 0 else None, None])
    feats.append(g)
pts.dataProvider().addFeatures(feats)
pts.setDisplayExpression("'Station ' || \"station\"")

from osgeo import gdal
import numpy as np
gdal.UseExceptions()
tif = os.path.join(out, "dem.tif")
ds = gdal.GetDriverByName("GTiff").Create(tif, 100, 100, 1, gdal.GDT_Float32)
ds.SetGeoTransform((1170000, 600, 0, 8410000, 0, -500)); ds.SetProjection("EPSG:3857")
ds.GetRasterBand(1).WriteArray(np.linspace(0, 250, 10000, dtype="float32").reshape(100, 100)); ds = None
ras = QgsRasterLayer(tif, "Depth model")
QgsProject.instance().addMapLayers([poly, pts, ras])
QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

canvas = QgsMapCanvas()
canvas.resize(1100, 720)
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
canvas.setLayers([pts, poly, ras])
canvas.setExtent(QgsRectangle(1170000, 8360000, 1230000, 8410000))
canvas.show()
canvas.refresh(); canvas.waitWhileRendering()

from feature_popup.identify import identify
from feature_popup.popup import FeaturePopup
from feature_popup.settings import Settings

settings = Settings()
popup = FeaturePopup(canvas, None, settings)

def snap(name):
    for _ in range(5):
        app.processEvents()
    canvas.grab().save(os.path.join(out, name))

xf = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateReferenceSystem("EPSG:3857"), QgsProject.instance())
click = xf.transform(QgsPointXY(10.75, 59.91))
px = canvas.getCoordinateTransform().transform(click)
t0 = time.perf_counter(); res = identify(canvas, click, settings); ms = (time.perf_counter() - t0) * 1000
print("identify:", len(res), "results in %.1f ms" % ms, [r.title for r in res])
popup.show_results(res, click, QPoint(int(px.x()), int(px.y())), ms)
snap("1_points.png")
popup.cards[0].set_expanded(False); popup.cards[-1].set_expanded(True)
snap("2_polygon.png")
popup.cards[-1].set_expanded(True); snap("2b_raster.png")
popup.search.setText("area"); popup._apply_filter(); snap("3_filter.png")
popup.search.setText("")
empty = QgsPointXY(1171000, 8361000)
popup.show_results(identify(canvas, empty, settings), empty, QPoint(20, 700), 0.4)
snap("4_empty.png")
pal = QPalette(QColor("#2b2b2b")); QgsApplication.setPalette(pal)
settings.position = "click"
popup.show_results(identify(canvas, click, settings), click, QPoint(int(px.x()), int(px.y())), ms)
snap("5_dark_click.png")
print("ok")
del popup; canvas.deleteLater(); app.processEvents(); QgsProject.instance().clear(); app.exitQgis()
