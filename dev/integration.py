"""Headless integration test: plugin load/unload via stub iface, click+drag via map tool, raster, perf."""
import os, sys, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from osgeo import gdal
import numpy as np
from qgis.core import *
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QPoint, Qt, QObject
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMainWindow

app = QgsApplication([], True); app.initQgis()
out = "/tmp/fp"; os.makedirs(out, exist_ok=True)

# raster
tif = os.path.join(out, "dem.tif")
ds = gdal.GetDriverByName("GTiff").Create(tif, 100, 100, 2, gdal.GDT_Float32)
ds.SetGeoTransform((1170000, 600, 0, 8410000, 0, -500)); ds.SetProjection("EPSG:3857")
ds.GetRasterBand(1).WriteArray(np.full((100, 100), 123.456, dtype="float32"))
ds.GetRasterBand(2).WriteArray(np.full((100, 100), 7, dtype="float32")); ds = None
ras = QgsRasterLayer(tif, "Depth model")
assert ras.isValid()

# big point layer
N = 200_000
big = QgsVectorLayer("Point?crs=EPSG:3857&field=id:integer&field=v:double&field=label:string", "Big points", "memory")
feats = []
for i in range(N):
    f = QgsFeature(big.fields()); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(random.uniform(1170000, 1230000), random.uniform(8360000, 8410000))))
    f.setAttributes([i, random.random(), f"pt {i}"]); feats.append(f)
big.dataProvider().addFeatures(feats); big.dataProvider().createSpatialIndex()
QgsProject.instance().addMapLayers([big, ras])

class Iface(QObject):
    def __init__(self, canvas): super().__init__(); self.c = canvas; self.mw = QMainWindow(); self.menu = []
    def mapCanvas(self): return self.c
    def mainWindow(self): return self.mw
    def addToolBarIcon(self, a): self.menu.append(a)
    def removeToolBarIcon(self, a): self.menu.remove(a)
    def addPluginToWebMenu(self, m, a): pass
    def removePluginWebMenu(self, m, a): pass
    def openFeatureForm(self, *a): print("form", a)

canvas = QgsMapCanvas(); canvas.resize(1100, 720)
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
canvas.setLayers([big, ras]); canvas.setExtent(QgsRectangle(1170000, 8360000, 1230000, 8410000))
canvas.show(); canvas.refresh(); canvas.waitWhileRendering()

from feature_popup.plugin import FeaturePopupPlugin
iface = Iface(canvas)
plugin = FeaturePopupPlugin(iface)
plugin.initGui()
plugin.action.trigger()
assert canvas.mapTool() is plugin.tool

vp = canvas.viewport()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300))
app.processEvents()
pop = plugin.popup
print("popup visible:", pop.isVisible(), "cards:", len(pop.cards), "pending:", len(pop._pending), "timing:", pop.timing.text())
print("titles:", [c.result.title for c in pop.cards[:3]], "...", [c.result.title for c in pop.cards if not c.result.is_vector])
assert pop.isVisible() and pop.cards

# click inside the popup must NOT trigger identify / reach canvas
before = pop.timing.text(); n_before = len(pop.cards)
QTest.mouseClick(pop.frame, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 300))
app.processEvents()
assert len(pop.cards) == n_before

# drag = pan, no identify
c0 = canvas.center()
QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 300))
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtCore import QPointF, QEvent
for x in range(300, 200, -10):
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, 300), QPointF(vp.mapToGlobal(QPoint(x, 300))), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(vp, ev)
QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 300))
app.processEvents(); canvas.waitWhileRendering()
print("panned:", round(canvas.center().x() - c0.x()), "map units; cards still:", len(pop.cards))

# raster card contents
r = [c for c in pop.cards if not c.result.is_vector]
print("raster rows:", [(x.key, x.value) for x in r[0].rows()] if r else "none (pending?)")

# filter over everything
t0 = time.perf_counter(); pop.search.setText("pt 1"); pop._apply_filter(); print("filter ms: %.1f" % ((time.perf_counter() - t0) * 1000), "visible:", sum(c.isVisible() for c in pop.cards))
pop.search.setText(""); pop._apply_filter()

# timings of identify on big layer
from feature_popup.identify import identify
ts = []
for _ in range(20):
    p = QgsPointXY(random.uniform(1175000, 1225000), random.uniform(8365000, 8405000))
    t0 = time.perf_counter(); res = identify(canvas, p, plugin.settings); ts.append((time.perf_counter() - t0) * 1000)
print("identify on %d pts: median %.2f ms, max %.2f ms" % (N, sorted(ts)[10], max(ts)))
t0 = time.perf_counter()
pop.show_results(res, p, QPoint(500, 300), 0); app.processEvents()
print("show_results + paint: %.1f ms" % ((time.perf_counter() - t0) * 1000))

# hover highlight + layer removal + escape
pop.cards[0].hovered.emit(pop.cards[0], True); assert pop._hover_hl is not None
pop.cards[0].hovered.emit(pop.cards[0], False); assert pop._hover_hl is None
QTest.keyClick(pop, Qt.Key.Key_Escape); assert not pop.isVisible()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)); app.processEvents()
assert pop.isVisible()
QgsProject.instance().removeMapLayer(ras.id()); app.processEvents()
print("closed after layer removal:", not pop.isVisible())
canvas.grab().save(os.path.join(out, "6_integration.png"))

plugin.unload(); app.processEvents()
print("unloaded; map tool:", canvas.mapTool())
print("ALL OK")
if True:  # orderly teardown avoids PyQGIS exit-time segfaults
    del plugin, pop; canvas.deleteLater(); app.processEvents(); QgsProject.instance().clear(); app.exitQgis()
