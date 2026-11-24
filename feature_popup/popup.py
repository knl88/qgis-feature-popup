"""The floating, card-based feature info panel (child widget of the map canvas)."""

import html
import re

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsIconUtils,
    QgsNetworkContentFetcher,
    QgsProject,
)
from qgis.gui import QgsHighlight, QgsVertexMarker
from qgis.PyQt.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .identify import AttributeFormatter

SHADOW = 14  # transparent margin around the panel used for the drop shadow
MARGIN = 10  # gap between panel and canvas edge
DEFAULT_WIDTH = 380
MIN_W, MIN_H = 280, 140
BATCH = 25  # cards rendered before a "show more" button
THUMB_W, THUMB_H = 260, 180
KEY_MAX_W = 160

LIGHT = dict(
    bg="#ffffff", head="#26303b", head_fg="#ffffff", head_muted="#aab4bf", fg="#1d232b",
    muted="#5d6875", faint="#a3abb5", border="#e3e7ec", card="#ffffff", alt="#f4f6f9",
    hover="#eef1f5", input="#f6f8fa", footer="#fafbfc", accent="#2f80ed",
    accent_soft="#bcd6fa", scroll="#c9d0d8", hl_hover="#f59e0b",
)
DARK = dict(
    bg="#1f242b", head="#14181d", head_fg="#e9eef3", head_muted="#8a96a3", fg="#e3e9ef",
    muted="#9aa6b2", faint="#66717d", border="#343c46", card="#262c34", alt="#2c333c",
    hover="#313942", input="#262c34", footer="#1b2026", accent="#58a6ff",
    accent_soft="#2d4a6e", scroll="#4a5460", hl_hover="#fbbf24",
)

QSS = """
#fpPanel { background: %(bg)s; border: 1px solid %(border)s; border-radius: 12px; }
#fpHeader { background: %(head)s; border-top-left-radius: 11px; border-top-right-radius: 11px; }
#fpHeaderTitle { color: %(head_fg)s; font-weight: 600; font-size: 13px; }
#fpHeaderSub { color: %(head_muted)s; font-size: 11px; }
#fpPill { background: %(accent)s; color: #ffffff; border-radius: 8px; padding: 0px 7px;
          font-size: 11px; font-weight: 600; }
QToolButton#fpHeadBtn { border: none; border-radius: 6px; padding: 4px; background: transparent; }
QToolButton#fpHeadBtn:hover { background: rgba(255, 255, 255, 0.14); }
QLineEdit#fpSearch { border: 1px solid %(border)s; border-radius: 8px; padding: 5px 6px;
                     background: %(input)s; color: %(fg)s; font-size: 12px;
                     selection-background-color: %(accent)s; }
QLineEdit#fpSearch:focus { border: 1px solid %(accent)s; }
QScrollArea#fpScroll, QWidget#fpViewport, QWidget#fpContainer { background: transparent; border: none; }
#fpCard { background: %(card)s; border: 1px solid %(border)s; border-radius: 9px; }
#fpCard:hover { border: 1px solid %(accent_soft)s; }
#fpCard[expanded="true"] { border: 1px solid %(accent)s; }
#fpCardTitle { color: %(fg)s; font-weight: 600; font-size: 12px; }
#fpCardSub { color: %(muted)s; font-size: 11px; }
QToolButton#fpCardBtn { border: none; border-radius: 5px; padding: 3px; background: transparent; }
QToolButton#fpCardBtn:hover { background: %(hover)s; }
#fpRowAlt { background: %(alt)s; border-radius: 5px; }
#fpKey { color: %(muted)s; font-size: 12px; padding: 5px 12px 5px 8px; }
#fpValue { color: %(fg)s; font-size: 12px; padding: 5px 8px 5px 0px; }
#fpNull { color: %(faint)s; font-size: 12px; padding: 5px 8px 5px 0px; }
#fpThumb { border-radius: 6px; padding: 2px 0px 4px 0px; }
#fpEmpty { color: %(muted)s; font-size: 12px; padding: 24px 12px; }
QPushButton#fpMore { border: 1px dashed %(border)s; border-radius: 8px; padding: 7px;
                     color: %(accent)s; background: transparent; font-size: 12px; }
QPushButton#fpMore:hover { background: %(hover)s; }
#fpFooter { background: %(footer)s; border-top: 1px solid %(border)s;
            border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }
#fpFooterText { color: %(muted)s; font-size: 11px; }
#fpFooterFaint { color: %(faint)s; font-size: 11px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 2px 2px 0px; }
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_LONG_TOKEN = re.compile(r"(\S{28})(?=\S)")


def _theme():
    window = QgsApplication.palette().color(QPalette.ColorRole.Window)
    return DARK if window.lightness() < 128 else LIGHT


def _event_pos(e):
    return e.position().toPoint() if hasattr(e, "position") else e.pos()


def _global_pos(e):
    return e.globalPosition().toPoint() if hasattr(e, "globalPosition") else e.globalPos()


def _soft_wrap(text):
    """Allow very long tokens (paths, hashes) to wrap instead of widening the panel."""
    return _LONG_TOKEN.sub("\\1\u200b", text)


def _tool_button(name, color, tooltip, object_name, size=16):
    b = QToolButton()
    b.setObjectName(object_name)
    b.setIcon(icons.icon(name, color, size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def _open(target):
    url = QUrl(target) if "://" in target else QUrl.fromLocalFile(target)
    QDesktopServices.openUrl(url)


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(_event_pos(e)):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# --------------------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------------------
class CardHeader(QWidget):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(_event_pos(e)):
            self.clicked.emit()
        e.accept()

    def mousePressEvent(self, e):
        e.accept()


class FeatureCard(QFrame):
    toggled = pyqtSignal(object, bool)
    hovered = pyqtSignal(object, bool)

    def __init__(self, popup, result):
        super().__init__()
        self.popup = popup
        self.result = result
        self.expanded = False
        self._rows = result.rows
        self._body = None
        self._row_widgets = []
        self._fetchers = []
        self.setObjectName("fpCard")
        self.setProperty("expanded", False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        t = popup.theme

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = CardHeader()
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(8, 7, 6, 7)
        h.setSpacing(6)

        self.chevron = QLabel()
        self.chevron.setFixedSize(16, 16)
        h.addWidget(self.chevron, 0, Qt.AlignmentFlag.AlignTop)

        layer = result.layer
        if layer is not None:
            lay_icon = QLabel()
            lay_icon.setPixmap(QgsIconUtils.iconForLayer(layer).pixmap(16, 16))
            lay_icon.setFixedSize(16, 16)
            h.addWidget(lay_icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(_soft_wrap(result.title))
        title.setObjectName("fpCardTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        text.addWidget(title)
        if result.title != result.layer_name:
            sub = QLabel(result.layer_name)
            sub.setObjectName("fpCardSub")
            sub.setTextFormat(Qt.TextFormat.PlainText)
            sub.setWordWrap(True)
            text.addWidget(sub)
        h.addLayout(text, 1)

        if result.is_vector:
            zoom = _tool_button("zoom", t["muted"], "Zoom to feature", "fpCardBtn")
            zoom.clicked.connect(self.zoom_to)
            form = _tool_button("form", t["muted"], "Open attribute form", "fpCardBtn")
            form.clicked.connect(self.open_form)
            h.addWidget(zoom, 0, Qt.AlignmentFlag.AlignTop)
            h.addWidget(form, 0, Qt.AlignmentFlag.AlignTop)
        self.copy_btn = _tool_button("copy", t["muted"], "Copy attributes", "fpCardBtn")
        self.copy_btn.clicked.connect(self.copy)
        h.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignTop)

        lay.addWidget(self.header)
        self.header.clicked.connect(lambda: self.set_expanded(not self.expanded))
        self._update_chevron()

    # -- data -----------------------------------------------------------------------
    def rows(self):
        if self._rows is None:
            layer = self.result.layer
            if layer is None:
                self._rows = []
            else:
                self._rows = self.popup.formatter.rows(
                    layer, self.result.feature, self.popup.settings.hide_empty
                )
        return self._rows

    def matches(self, needle):
        if needle in self.result.title.lower() or needle in self.result.layer_name.lower():
            return True
        return any(needle in r.key.lower() or needle in r.value.lower() for r in self.rows())

    # -- state ----------------------------------------------------------------------
    def set_expanded(self, expanded, notify=True):
        if expanded == self.expanded:
            return
        self.expanded = expanded
        if expanded and self._body is None:
            self._build_body()
        if self._body is not None:
            self._body.setVisible(expanded)
        self.setProperty("expanded", expanded)
        self.style().unpolish(self)
        self.style().polish(self)
        self._update_chevron()
        if notify:
            self.toggled.emit(self, expanded)

    def _update_chevron(self):
        name = "chevron-down" if self.expanded else "chevron-right"
        self.chevron.setPixmap(icons.pixmap(name, self.popup.theme["muted"], 16))

    def apply_filter(self, needle):
        """Show only rows matching needle; returns whether the card matches at all."""
        if not needle:
            for widgets in self._row_widgets:
                for w in widgets:
                    w.setVisible(True)
            return True
        title_hit = needle in self.result.title.lower() or needle in self.result.layer_name.lower()
        hit = title_hit or self.matches(needle)
        if hit and not self.expanded:
            self.set_expanded(True)
        for row, widgets in zip(self.rows(), self._row_widgets):
            show = title_hit or needle in row.key.lower() or needle in row.value.lower()
            for w in widgets:
                w.setVisible(show)
        return hit

    # -- body -----------------------------------------------------------------------
    def _build_body(self):
        t = self.popup.theme
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(6, 0, 6, 6)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        rows = self.rows()
        if not rows:
            empty = QLabel("No attributes")
            empty.setObjectName("fpNull")
            grid.addWidget(empty, 0, 0, 1, 2)

        for i, row in enumerate(rows):
            widgets = []
            if i % 2 == 0:
                bg = QFrame()
                bg.setObjectName("fpRowAlt")
                grid.addWidget(bg, i, 0, 1, 2)
                widgets.append(bg)

            key = QLabel(row.key)
            key.setObjectName("fpKey")
            key.setTextFormat(Qt.TextFormat.PlainText)
            key.setWordWrap(True)
            key.setMaximumWidth(KEY_MAX_W)
            key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(key, i, 0)
            widgets.append(key)

            value = self._value_widget(row, t)
            grid.addWidget(value, i, 1)
            widgets.append(value)
            self._row_widgets.append(widgets)

        self.layout().addWidget(body)
        self._body = body
        # Keep short keys on one line; only long keys wrap (capped column width).
        for widgets in self._row_widgets:
            key = widgets[-2]
            key.setWordWrap(False)
            natural = key.sizeHint().width() + 2
            key.setWordWrap(True)
            key.setMinimumWidth(min(natural, KEY_MAX_W))

    def _value_widget(self, row, t):
        if row.kind == "null":
            w = QLabel(row.value)
            w.setObjectName("fpNull")
            return w

        if row.kind in ("url", "image"):
            link = QLabel()
            link.setObjectName("fpValue")
            link.setTextFormat(Qt.TextFormat.RichText)
            shown = row.value if row.value != row.target else row.target
            if len(shown) > 48:
                shown = shown[:22] + "…" + shown[-22:]
            link.setText(
                '<a style="color:%s; text-decoration:none" href="%s">%s</a>'
                % (t["accent"], html.escape(row.target, quote=True), html.escape(shown))
            )
            link.setToolTip(row.target)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            link.linkActivated.connect(_open)
            link.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            if row.kind == "url":
                return link

            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 4, 0, 0)
            v.setSpacing(0)
            thumb = ClickableLabel()
            thumb.setObjectName("fpThumb")
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.setToolTip("Open image")
            thumb.clicked.connect(lambda target=row.target: _open(target))
            thumb.hide()
            v.addWidget(thumb)
            v.addWidget(link)
            QTimer.singleShot(0, lambda: self._load_image(row.target, thumb))
            return box

        w = QLabel(_soft_wrap(row.value))
        w.setObjectName("fpValue")
        w.setTextFormat(Qt.TextFormat.PlainText)
        w.setWordWrap(True)
        w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return w

    def _load_image(self, target, label):
        if "://" not in target:
            reader = QImageReader(target)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio))
            self._show_image(label, reader.read())
            return
        fetcher = QgsNetworkContentFetcher()
        self._fetchers.append(fetcher)

        def done():
            reply = fetcher.reply()
            img = QImage()
            if reply is not None:
                img.loadFromData(reply.readAll())
            self._show_image(label, img)

        fetcher.finished.connect(done)
        fetcher.fetchContent(QUrl(target))

    def _show_image(self, label, img):
        if img.isNull():
            return
        if img.width() > THUMB_W or img.height() > THUMB_H:
            img = img.scaled(
                THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        try:
            label.setPixmap(_rounded(QPixmap.fromImage(img), 6))
            label.show()
        except RuntimeError:  # card was cleared while loading
            return
        self.popup.schedule_relayout()

    # -- actions --------------------------------------------------------------------
    def zoom_to(self):
        layer = self.result.layer
        if layer is None:
            return
        canvas = self.popup.canvas
        fid = self.result.feature.id()
        canvas.zoomToFeatureIds(layer, [fid])
        c = QColor(self.popup.theme["accent"])
        end = QColor(c)
        end.setAlpha(0)
        canvas.flashFeatureIds(layer, [fid], c, end, 2, 400)

    def open_form(self):
        layer = self.result.layer
        if layer is not None and self.popup.iface is not None:
            self.popup.iface.openFeatureForm(layer, self.result.feature, False, False)

    def copy(self):
        lines = [f"{r.key}\t{(r.target or r.value) if r.kind != 'null' else ''}" for r in self.rows()]
        QGuiApplication.clipboard().setText("\n".join(lines))
        t = self.popup.theme
        self.copy_btn.setIcon(icons.icon("check", t["accent"]))
        QTimer.singleShot(1200, lambda: self._reset_copy_icon())

    def _reset_copy_icon(self):
        try:
            self.copy_btn.setIcon(icons.icon("copy", self.popup.theme["muted"]))
        except RuntimeError:
            pass

    # -- hover ----------------------------------------------------------------------
    def enterEvent(self, e):
        self.hovered.emit(self, True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered.emit(self, False)
        super().leaveEvent(e)


def _rounded(pm, radius):
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pm.width(), pm.height()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


# --------------------------------------------------------------------------------------
# Panel chrome
# --------------------------------------------------------------------------------------
class DragHeader(QFrame):
    def __init__(self, popup):
        super().__init__()
        self.popup = popup
        self._offset = None
        self.setObjectName("fpHeader")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._offset = _global_pos(e) - self.popup.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        e.accept()

    def mouseMoveEvent(self, e):
        if self._offset is not None:
            self.popup.user_move(_global_pos(e) - self._offset)
        e.accept()

    def mouseReleaseEvent(self, e):
        self._offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self.popup.reset_geometry()
        e.accept()


class ResizeGrip(QWidget):
    def __init__(self, popup):
        super().__init__()
        self.popup = popup
        self._start = None
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Resize")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.popup.theme["faint"]))
        for x, y in ((10, 4), (10, 10), (4, 10), (10, 7), (7, 10)):
            p.drawEllipse(QRectF(x - 1, y - 1, 2, 2))

    def mousePressEvent(self, e):
        self._start = (_global_pos(e), self.popup.frame.size())
        e.accept()

    def mouseMoveEvent(self, e):
        if self._start:
            origin, size = self._start
            d = _global_pos(e) - origin
            self.popup.user_resize(QSize(size.width() + d.x(), size.height() + d.y()))
        e.accept()

    def mouseReleaseEvent(self, e):
        self._start = None
        e.accept()


class FeaturePopup(QWidget):
    closed = pyqtSignal()

    def __init__(self, canvas, iface, settings):
        super().__init__(canvas)
        self.canvas = canvas
        self.iface = iface
        self.settings = settings
        self.theme = _theme()
        self.formatter = AttributeFormatter()
        self.cards = []
        self._pending = []
        self._highlights = {}
        self._hover_hl = None
        self._marker = None
        self._click_px = None
        self._map_point = None
        self._user_pos = None
        self._user_size = None
        self._relayout_pending = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build()
        self.hide()
        canvas.installEventFilter(self)

    # -- construction ---------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        self.frame = QFrame()
        self.frame.setObjectName("fpPanel")
        outer.addWidget(self.frame)

        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header
        self.header = DragHeader(self)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(14, 9, 8, 9)
        h.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel("Feature information")
        self.title.setObjectName("fpHeaderTitle")
        self.pill = QLabel()
        self.pill.setObjectName("fpPill")
        self.pill.setFixedHeight(16)
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.title)
        title_row.addWidget(self.pill)
        title_row.addStretch(1)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("fpHeaderSub")
        titles.addLayout(title_row)
        titles.addWidget(self.subtitle)
        h.addLayout(titles, 1)
        self.toggle_all_btn = QToolButton()
        self.toggle_all_btn.setObjectName("fpHeadBtn")
        self.toggle_all_btn.setAutoRaise(True)
        self.toggle_all_btn.setIconSize(QSize(16, 16))
        self.toggle_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_all_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_all_btn.clicked.connect(self._toggle_all)
        h.addWidget(self.toggle_all_btn)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("fpHeadBtn")
        self.close_btn.setAutoRaise(True)
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.clicked.connect(self.close_popup)
        h.addWidget(self.close_btn)
        lay.addWidget(self.header)

        # search
        self.search_wrap = QWidget()
        s = QHBoxLayout(self.search_wrap)
        s.setContentsMargins(10, 10, 10, 2)
        self.search = QLineEdit()
        self.search.setObjectName("fpSearch")
        self.search.setPlaceholderText("Filter features and attributes…")
        self.search.setClearButtonEnabled(True)
        self._search_action = self.search.addAction(
            icons.icon("search", self.theme["faint"]), QLineEdit.ActionPosition.LeadingPosition
        )
        self._filter_timer = QTimer(self, singleShot=True, interval=120)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _: self._filter_timer.start())
        s.addWidget(self.search)
        lay.addWidget(self.search_wrap)

        # cards
        self.scroll = QScrollArea()
        self.scroll.setObjectName("fpScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("fpViewport")
        self.container = QWidget()
        self.container.setObjectName("fpContainer")
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setContentsMargins(10, 8, 10, 10)
        self.cards_layout.setSpacing(7)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        lay.addWidget(self.scroll, 1)

        self.empty = QLabel()
        self.empty.setObjectName("fpEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.hide()

        self.more_btn = QPushButton()
        self.more_btn.setObjectName("fpMore")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.clicked.connect(self._render_more)
        self.more_btn.hide()

        # footer
        self.footer = QFrame()
        self.footer.setObjectName("fpFooter")
        f = QHBoxLayout(self.footer)
        f.setContentsMargins(12, 6, 4, 4)
        f.setSpacing(6)
        self.pin = QLabel()
        f.addWidget(self.pin)
        self.coords = QLabel()
        self.coords.setObjectName("fpFooterText")
        self.coords.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f.addWidget(self.coords)
        self.copy_coords = QToolButton()
        self.copy_coords.setObjectName("fpCardBtn")
        self.copy_coords.setToolTip("Copy coordinates (lat, lon)")
        self.copy_coords.setIconSize(QSize(14, 14))
        self.copy_coords.setAutoRaise(True)
        self.copy_coords.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_coords.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_coords.clicked.connect(self._copy_coords)
        f.addWidget(self.copy_coords)
        f.addStretch(1)
        self.timing = QLabel()
        self.timing.setObjectName("fpFooterFaint")
        f.addWidget(self.timing)
        self.grip = ResizeGrip(self)
        f.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addWidget(self.footer)

    def _apply_theme(self):
        self.theme = t = _theme()
        self.setStyleSheet(QSS % t)
        self.close_btn.setIcon(icons.icon("close", t["head_fg"]))
        self.pin.setPixmap(icons.pixmap("pin", t["muted"], 14))
        self.copy_coords.setIcon(icons.icon("copy", t["muted"], 14))
        self._search_action.setIcon(icons.icon("search", t["faint"]))
        self._update_toggle_all()

    # -- public API -----------------------------------------------------------------
    def show_results(self, results, map_point, click_px, elapsed_ms=None):
        self._clear_cards()
        self.formatter.clear()
        self._apply_theme()
        self._map_point = map_point
        self._click_px = click_px
        self._set_marker(map_point)

        n = len(results)
        self.pill.setText(str(n))
        self.pill.setVisible(n > 0)
        layers = len({r.layer_id for r in results})
        self.subtitle.setText(
            f"{n} feature{'s' if n != 1 else ''} in {layers} layer{'s' if layers != 1 else ''}"
            if n else "Nothing here"
        )
        self.timing.setText(f"{elapsed_ms:.0f} ms" if elapsed_ms is not None else "")
        self._update_coords(map_point)

        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search_wrap.setVisible(n > 0)

        if not results:
            self.empty.setText("No features found at this location.\nTry clicking closer to a feature.")
            self.cards_layout.insertWidget(0, self.empty)
            self.empty.show()
        else:
            self._pending = list(results)
            self._render_more()

        self.scroll.verticalScrollBar().setValue(0)
        self.show()
        self.raise_()
        self.relayout()

    def close_popup(self):
        if not self.isVisible():
            return
        self.hide()
        self._clear_cards()
        self._remove_marker()
        self.closed.emit()

    def on_layers_removed(self, layer_ids):
        ids = set(layer_ids)
        if any(c.result.layer_id in ids for c in self.cards) or any(
            r.layer_id in ids for r in self._pending
        ):
            self.close_popup()

    def shutdown(self):
        self.canvas.removeEventFilter(self)
        self._clear_cards()
        self._remove_marker()
        self.hide()
        self.setParent(None)
        self.deleteLater()

    # -- cards ----------------------------------------------------------------------
    def _render_more(self, refilter=True):
        batch, self._pending = self._pending[:BATCH], self._pending[BATCH:]
        expand_all = self.settings.expand == "all"
        for result in batch:
            card = FeatureCard(self, result)
            card.toggled.connect(self._on_card_toggled)
            card.hovered.connect(self._on_card_hovered)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self.cards.append(card)
            if expand_all or len(self.cards) == 1:
                card.set_expanded(True)

        self.cards_layout.removeWidget(self.more_btn)
        if self._pending:
            self.more_btn.setText(f"Show {len(self._pending)} more")
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, self.more_btn)
            self.more_btn.show()
        else:
            self.more_btn.hide()
        self._update_toggle_all()
        if refilter and self.search.text():
            self._apply_filter()
        self.schedule_relayout()

    def _clear_cards(self):
        self._filter_timer.stop()
        self._clear_hover()
        for hl in self._highlights.values():
            self._remove_item(hl)
        self._highlights.clear()
        for card in self.cards:
            self.cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        self._pending = []
        self.empty.hide()
        self.cards_layout.removeWidget(self.empty)
        self.more_btn.hide()

    def _on_card_toggled(self, card, expanded):
        if expanded:
            self._add_highlight(card)
        else:
            hl = self._highlights.pop(card, None)
            if hl is not None:
                self._remove_item(hl)
        self._update_toggle_all()
        self.schedule_relayout()

    def _on_card_hovered(self, card, inside):
        self._clear_hover()
        if inside and card.result.is_vector and card.result.layer is not None:
            self._hover_hl = self._make_highlight(card, self.theme["hl_hover"], 90)

    def _toggle_all(self):
        expand = not all(c.expanded for c in self.cards)
        for c in self.cards:
            c.set_expanded(expand)
        self._update_toggle_all()

    def _update_toggle_all(self):
        all_open = bool(self.cards) and all(c.expanded for c in self.cards)
        name = "collapse-all" if all_open else "expand-all"
        self.toggle_all_btn.setIcon(icons.icon(name, self.theme["head_fg"]))
        self.toggle_all_btn.setToolTip("Collapse all" if all_open else "Expand all")
        self.toggle_all_btn.setVisible(len(self.cards) > 1)

    def _apply_filter(self):
        needle = self.search.text().strip().lower()
        if needle and self._pending:
            self._render_more_all()
        for card in self.cards:
            card.setVisible(card.apply_filter(needle))
        self.schedule_relayout()

    def _render_more_all(self):
        while self._pending:
            self._render_more(refilter=False)

    # -- map decorations ------------------------------------------------------------
    def _make_highlight(self, card, color, fill_alpha):
        hl = QgsHighlight(self.canvas, card.result.feature.geometry(), card.result.layer)
        c = QColor(color)
        hl.setColor(c)
        fill = QColor(c)
        fill.setAlpha(fill_alpha)
        hl.setFillColor(fill)
        hl.setWidth(3)
        hl.setMinWidth(3)
        hl.show()
        return hl

    def _add_highlight(self, card):
        if card.result.is_vector and card.result.layer is not None and card not in self._highlights:
            self._highlights[card] = self._make_highlight(card, self.theme["accent"], 60)

    def _clear_hover(self):
        if self._hover_hl is not None:
            self._remove_item(self._hover_hl)
            self._hover_hl = None

    def _set_marker(self, map_point):
        self._remove_marker()
        m = QgsVertexMarker(self.canvas)
        m.setCenter(map_point)
        try:
            m.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        except AttributeError:
            m.setIconType(QgsVertexMarker.ICON_CIRCLE)
        m.setIconSize(14)
        m.setPenWidth(3)
        m.setColor(QColor(self.theme["accent"]))
        m.setFillColor(QColor(255, 255, 255, 220))
        self._marker = m

    def _remove_marker(self):
        if self._marker is not None:
            self._remove_item(self._marker)
            self._marker = None

    def _remove_item(self, item):
        try:
            self.canvas.scene().removeItem(item)
        except RuntimeError:
            pass

    # -- coordinates ----------------------------------------------------------------
    def _latlon(self, map_point):
        src = self.canvas.mapSettings().destinationCrs()
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            p = QgsCoordinateTransform(src, wgs, QgsProject.instance()).transform(map_point)
        except QgsCsException:
            return None
        return p.y(), p.x()

    def _update_coords(self, map_point):
        ll = self._latlon(map_point)
        if ll is None:
            self.coords.setText(f"{map_point.x():.2f}, {map_point.y():.2f}")
            return
        lat, lon = ll
        self.coords.setText(
            f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"
        )

    def _copy_coords(self):
        ll = self._latlon(self._map_point) if self._map_point is not None else None
        if ll is None:
            return
        QGuiApplication.clipboard().setText(f"{ll[0]:.6f}, {ll[1]:.6f}")
        self.copy_coords.setIcon(icons.icon("check", self.theme["accent"], 14))
        QTimer.singleShot(
            1200, lambda: self.copy_coords.setIcon(icons.icon("copy", self.theme["muted"], 14))
        )

    # -- geometry -------------------------------------------------------------------
    def schedule_relayout(self):
        if not self._relayout_pending:
            self._relayout_pending = True
            QTimer.singleShot(0, self.relayout)

    def relayout(self):
        self._relayout_pending = False
        if not self.isVisible():
            return
        area = self.canvas.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        if self._user_size is not None:
            w = self._user_size.width()
            h = self._user_size.height()
        else:
            w = DEFAULT_WIDTH
            h = self._natural_height(min(w, area.width()))
        w = max(MIN_W, min(w, area.width()))
        h = max(MIN_H, min(h, area.height()))

        if self._user_pos is not None:
            x, y = self._user_pos.x(), self._user_pos.y()
        elif self.settings.position == "click" and self._click_px is not None:
            cx, cy = self._click_px.x(), self._click_px.y()
            x = cx + 18 if cx + 18 + w <= area.right() else cx - 18 - w
            y = cy - 40
        else:
            x, y = area.right() - w + 1, area.top()

        x = max(area.left(), min(x, area.right() - w + 1))
        y = max(area.top(), min(y, area.bottom() - h + 1))
        self.setGeometry(QRect(x - SHADOW, y - SHADOW, w + 2 * SHADOW, h + 2 * SHADOW))

    def _natural_height(self, width):
        inner = width - 2  # panel border
        chrome = self.header.sizeHint().height() + self.footer.sizeHint().height() + 2
        if self.search_wrap.isVisible():
            chrome += self.search_wrap.sizeHint().height()
        content_w = inner - self.scroll.verticalScrollBar().sizeHint().width()
        lay = self.container.layout()
        content = (
            lay.heightForWidth(content_w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        )
        return chrome + content + 2

    def user_move(self, outer_pos):
        self._user_pos = outer_pos + QPoint(SHADOW, SHADOW)
        self.relayout()

    def user_resize(self, size):
        self._user_size = QSize(max(MIN_W, size.width()), max(MIN_H, size.height()))
        if self._user_pos is None:
            self._user_pos = self.frame.geometry().topLeft() + self.pos()
        self.relayout()

    def reset_geometry(self):
        self._user_pos = None
        self._user_size = None
        self.relayout()

    # -- events ---------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.canvas and event.type() == QEvent.Type.Resize:
            self.schedule_relayout()
        return False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.frame.geometry())
        dark = self.theme is DARK
        for i in range(SHADOW, 0, -2):
            alpha = int((40 if dark else 22) * (1 - i / SHADOW) ** 1.6) + 2
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 12 + i, 12 + i)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_popup()
            e.accept()
            return
        if e.key() == Qt.Key.Key_F and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.search.setFocus()
            e.accept()
            return
        super().keyPressEvent(e)

    # Swallow pointer events so they never fall through to the map canvas / map tool.
    def mousePressEvent(self, e):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        e.accept()

    def mouseReleaseEvent(self, e):
        e.accept()

    def mouseMoveEvent(self, e):
        e.accept()

    def mouseDoubleClickEvent(self, e):
        e.accept()

    def wheelEvent(self, e):
        e.accept()

    def contextMenuEvent(self, e):
        e.accept()
