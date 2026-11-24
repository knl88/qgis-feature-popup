from qgis.core import QgsApplication
from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication


class FeatureInfoTool(QgsMapTool):
    """Click to identify, click-drag to pan (like a web map).

    Deliberately has no keyPressEvent: overriding it stops the canvas from handling
    arrow-key panning and PgUp/PgDn zooming. Esc is handled via QgsMapCanvas.keyPressed.
    """

    clicked = pyqtSignal(object, object)  # map point (canvas CRS), pixel QPoint
    dismissed = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._press = None
        self._dragging = False
        self._cursor = QgsApplication.getThemeCursor(QgsApplication.Cursor.Identify)
        self.setCursor(self._cursor)

    def canvasPressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.pixelPoint()
            self._dragging = False

    def canvasMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self._dragging:
            if (e.pixelPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self.canvas().setCursor(Qt.CursorShape.ClosedHandCursor)
        self.canvas().panAction(e)

    def canvasReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.dismissed.emit()
            return
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        if self._dragging:
            self.canvas().panActionEnd(e.pixelPoint())
            self.canvas().setCursor(self._cursor)
        else:
            self.clicked.emit(e.mapPoint(), e.pixelPoint())
        self._press = None
        self._dragging = False

    def deactivate(self):
        self._press = None
        self._dragging = False
        super().deactivate()
