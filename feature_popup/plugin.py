import os
import time

from qgis.core import QgsProject
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5
    from qgis.PyQt.QtWidgets import QAction

from .identify import identify
from .map_tool import FeatureInfoTool
from .popup import FeaturePopup
from .settings import Settings, SettingsDialog

MENU = "&Feature Popup"


class FeaturePopupPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.settings = Settings.load()
        self.tool = None
        self.popup = None
        self.actions = []

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        main = self.iface.mainWindow()

        self.action = QAction(icon, "Feature Popup", main)
        self.action.setCheckable(True)
        self.action.setToolTip("Feature Popup — click a feature to see its attributes")
        self.action.triggered.connect(self.activate)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToWebMenu(MENU, self.action)

        self.settings_action = QAction("Settings…", main)
        self.settings_action.triggered.connect(self.show_settings)
        self.iface.addPluginToWebMenu(MENU, self.settings_action)
        self.actions = [self.action, self.settings_action]

        self.tool = FeatureInfoTool(self.canvas)
        self.tool.setAction(self.action)
        self.tool.clicked.connect(self.on_click)
        self.tool.dismissed.connect(self._close_popup)

        self.popup = FeaturePopup(self.canvas, self.iface, self.settings)
        QgsProject.instance().layersWillBeRemoved.connect(self.popup.on_layers_removed)
        QgsProject.instance().cleared.connect(self.popup.close_popup)

    def unload(self):
        project = QgsProject.instance()
        try:
            project.layersWillBeRemoved.disconnect(self.popup.on_layers_removed)
            project.cleared.disconnect(self.popup.close_popup)
        except TypeError:
            pass
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        for action in self.actions:
            self.iface.removePluginWebMenu(MENU, action)
        self.iface.removeToolBarIcon(self.action)
        self.popup.shutdown()
        self.popup = None
        self.tool = None

    def activate(self):
        self.canvas.setMapTool(self.tool)

    def show_settings(self):
        if SettingsDialog(self.settings, self.iface.mainWindow()).exec():
            self.popup.relayout()

    def _close_popup(self):
        if self.popup is not None:
            self.popup.close_popup()

    def on_click(self, map_point, pixel):
        t0 = time.perf_counter()
        results = identify(self.canvas, map_point, self.settings)
        elapsed = (time.perf_counter() - t0) * 1000
        self.popup.show_results(results, map_point, pixel, elapsed)
