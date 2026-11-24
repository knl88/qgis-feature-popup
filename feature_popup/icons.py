"""Tiny vector icons painted at runtime so they match the popup theme colours."""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_cache = {}


def icon(name, color, size=16):
    key = (name, color, size)
    if key not in _cache:
        _cache[key] = QIcon(pixmap(name, color, size))
    return _cache[key]


def pixmap(name, color, size=16):
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 16.0, size / 16.0)
    pen = QPen(QColor(color), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _DRAW[name](p)
    p.end()
    return pm


def _poly(p, *pts):
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def _close(p):
    _poly(p, (4.5, 4.5), (11.5, 11.5))
    _poly(p, (11.5, 4.5), (4.5, 11.5))


def _zoom(p):
    p.drawEllipse(QPointF(7, 7), 4.3, 4.3)
    _poly(p, (10.3, 10.3), (13.5, 13.5))


def _form(p):
    p.drawRoundedRect(QRectF(2.5, 2.5, 11, 11), 2, 2)
    _poly(p, (5.2, 6), (10.8, 6))
    _poly(p, (5.2, 8.5), (10.8, 8.5))
    _poly(p, (5.2, 11), (8.5, 11))


def _copy(p):
    p.drawRoundedRect(QRectF(5.5, 5.5, 8, 8), 1.6, 1.6)
    _poly(p, (3, 10.5), (2.6, 10.1), (2.6, 3.6), (3.4, 2.7), (9.8, 2.7), (10.4, 3.2))


def _pin(p):
    path = QPainterPath(QPointF(8, 14.5))
    path.cubicTo(QPointF(8, 14.5), QPointF(3.2, 9.6), QPointF(3.2, 6.6))
    path.cubicTo(QPointF(3.2, 3.9), QPointF(5.4, 1.8), QPointF(8, 1.8))
    path.cubicTo(QPointF(10.6, 1.8), QPointF(12.8, 3.9), QPointF(12.8, 6.6))
    path.cubicTo(QPointF(12.8, 9.6), QPointF(8, 14.5), QPointF(8, 14.5))
    p.drawPath(path)
    p.drawEllipse(QPointF(8, 6.6), 1.6, 1.6)


_DRAW = {
    "close": _close,
    "zoom": _zoom,
    "search": _zoom,
    "form": _form,
    "copy": _copy,
    "pin": _pin,
    "check": lambda p: _poly(p, (3.5, 8.5), (6.5, 11.5), (12.5, 4.5)),
    "chevron-right": lambda p: _poly(p, (6, 3.8), (10.2, 8), (6, 12.2)),
    "chevron-down": lambda p: _poly(p, (3.8, 6), (8, 10.2), (12.2, 6)),
    "expand-all": lambda p: (_poly(p, (4, 3.5), (8, 7.5), (12, 3.5)), _poly(p, (4, 8.5), (8, 12.5), (12, 8.5))),
    "collapse-all": lambda p: (_poly(p, (4, 7.5), (8, 3.5), (12, 7.5)), _poly(p, (4, 12.5), (8, 8.5), (12, 12.5))),
}
