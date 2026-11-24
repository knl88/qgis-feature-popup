"""Fast identify: spatially-indexed bbox requests against visible layers only."""

import math
import os
import re
from dataclasses import dataclass, field

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateTransform,
    QgsCsException,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRenderer,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayer,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRenderContext,
    QgsVectorLayer,
)

try:
    EXACT_INTERSECT = Qgis.FeatureRequestFlag.ExactIntersect
except AttributeError:  # QGIS < 3.36
    EXACT_INTERSECT = QgsFeatureRequest.ExactIntersect

try:
    IDENTIFIABLE = QgsMapLayer.LayerFlag.Identifiable
except AttributeError:
    IDENTIFIABLE = QgsMapLayer.Identifiable

try:
    RASTER_IDENTIFY_VALUE = Qgis.RasterInterfaceCapability.IdentifyValue
    RASTER_FORMAT_VALUE = Qgis.RasterIdentifyFormat.Value
except AttributeError:  # QGIS < 3.38
    from qgis.core import QgsRaster, QgsRasterInterface

    RASTER_IDENTIFY_VALUE = QgsRasterInterface.IdentifyValue
    RASTER_FORMAT_VALUE = QgsRaster.IdentifyFormatValue

try:
    RENDERER_FILTER = QgsFeatureRenderer.Capability.Filter
except AttributeError:
    RENDERER_FILTER = QgsFeatureRenderer.Filter

# Raster providers that answer identify() instantly from local data.
LOCAL_RASTER_PROVIDERS = {"gdal", "virtualraster"}

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg")


@dataclass
class Row:
    key: str
    value: str
    kind: str = "text"  # text | null | url | image
    target: str = ""  # resolved url/path for url & image rows


@dataclass
class IdentifyResult:
    layer_id: str
    layer_name: str
    title: str
    feature: object = None  # QgsFeature for vector results
    rows: list = field(default=None)  # lazily built for vectors, eager for rasters

    @property
    def layer(self):
        return QgsProject.instance().mapLayer(self.layer_id)

    @property
    def is_vector(self):
        return self.feature is not None


def _transform(canvas, layer):
    return QgsCoordinateTransform(
        canvas.mapSettings().destinationCrs(), layer.crs(), QgsProject.instance()
    )


def _flag_set(flags, flag):
    try:
        return bool(flags & flag)
    except TypeError:
        return bool(int(flags) & int(flag))


def identify(canvas, map_point, settings):
    """Return IdentifyResults for all identifiable, visible layers at map_point (canvas CRS)."""
    radius = settings.tolerance_px * canvas.mapUnitsPerPixel()
    search = QgsRectangle(
        map_point.x() - radius, map_point.y() - radius,
        map_point.x() + radius, map_point.y() + radius,
    )
    scale = canvas.scale()
    results = []
    remaining = settings.max_total

    for layer in canvas.layers(True):
        if remaining <= 0:
            break
        if not layer.isValid() or not _flag_set(layer.flags(), IDENTIFIABLE):
            continue
        if layer.hasScaleBasedVisibility() and not layer.isInScaleRange(scale):
            continue
        try:
            if isinstance(layer, QgsVectorLayer):
                found = _identify_vector(canvas, layer, map_point, search, min(remaining, settings.max_per_layer))
            elif isinstance(layer, QgsRasterLayer) and settings.include_rasters:
                found = _identify_raster(canvas, layer, map_point)
            else:
                continue
        except QgsCsException:
            continue
        results.extend(found)
        remaining -= len(found)
    return results


def _identify_vector(canvas, layer, map_point, search, limit):
    xform = _transform(canvas, layer)
    rect = xform.transformBoundingBox(search)
    point = xform.transform(map_point)

    ms = canvas.mapSettings()
    ctx = QgsRenderContext.fromMapSettings(ms)
    ctx.expressionContext().appendScope(QgsExpressionContextUtils.layerScope(layer))

    renderer = layer.renderer().clone() if layer.renderer() else None
    use_filter = False
    if renderer is not None:
        renderer.startRender(ctx, layer.fields())
        use_filter = _flag_set(renderer.capabilities(), RENDERER_FILTER)

    request = QgsFeatureRequest().setFilterRect(rect).setFlags(EXACT_INTERSECT)
    # Over-fetch a bit when the renderer may hide some of the candidates.
    request.setLimit(limit * 4 if use_filter else limit)

    candidates = []
    try:
        for feat in layer.getFeatures(request):
            if use_filter:
                ctx.expressionContext().setFeature(feat)
                if not renderer.willRenderFeature(feat, ctx):
                    continue
            candidates.append(feat)
    finally:
        if renderer is not None:
            renderer.stopRender(ctx)

    if not candidates:
        return []

    click = QgsGeometry.fromPointXY(QgsPointXY(point))

    def distance(f):
        g = f.geometry()
        return g.distance(click) if g and not g.isEmpty() else math.inf

    candidates.sort(key=distance)
    candidates = candidates[:limit]

    title_exp = QgsExpression(layer.displayExpression() or "")
    exp_ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    has_title = title_exp.isValid() and not title_exp.hasParserError() and title_exp.expression()
    if has_title:
        title_exp.prepare(exp_ctx)

    name = layer.name()
    out = []
    for feat in candidates:
        title = None
        if has_title:
            exp_ctx.setFeature(feat)
            value = title_exp.evaluate(exp_ctx)
            if value not in (None, "") and not _is_null(value):
                title = str(value)
        out.append(IdentifyResult(layer.id(), name, title or f"Feature {feat.id()}", feat))
    return out


def _identify_raster(canvas, layer, map_point):
    provider = layer.dataProvider()
    if provider is None or provider.name() not in LOCAL_RASTER_PROVIDERS:
        return []
    if not _flag_set(provider.capabilities(), RASTER_IDENTIFY_VALUE):
        return []
    point = _transform(canvas, layer).transform(map_point)
    if not layer.extent().contains(point):
        return []
    res = provider.identify(point, RASTER_FORMAT_VALUE)
    if not res.isValid():
        return []
    values = res.results()
    if not values or all(v is None or _is_null(v) for v in values.values()):
        return []
    rows = []
    for band in sorted(values):
        v = values[band]
        if v is None or _is_null(v):
            rows.append(Row(layer.bandName(band), "No data", "null"))
        else:
            rows.append(Row(layer.bandName(band), format_number(v)))
    return [IdentifyResult(layer.id(), layer.name(), layer.name(), None, rows)]


def _is_null(value):
    is_null = getattr(value, "isNull", None)
    if callable(is_null):
        try:
            return bool(is_null())
        except TypeError:
            return False
    return False


def format_number(v):
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.6g}" if abs(v) < 1e-3 or abs(v) >= 1e7 else f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


class AttributeFormatter:
    """Turns a feature into display rows, honouring aliases, hidden fields and value maps etc.

    Formatter caches (e.g. value relations) are built once per layer/field and reused.
    """

    def __init__(self):
        self._caches = {}

    def clear(self):
        self._caches.clear()

    def rows(self, layer, feature, hide_empty=False):
        registry = QgsApplication.fieldFormatterRegistry()
        project = QgsProject.instance()
        out = []
        for idx, fld in enumerate(layer.fields()):
            setup = layer.editorWidgetSetup(idx)
            wtype = setup.type()
            if wtype == "Hidden":
                continue
            raw = feature.attribute(idx)
            key = layer.attributeDisplayName(idx)
            if raw is None or _is_null(raw) or raw == "":
                if not hide_empty:
                    out.append(Row(key, "—", "null"))
                continue

            cache_key = (layer.id(), idx)
            entry = self._caches.get(cache_key)
            if entry is None:
                formatter = registry.fieldFormatter(wtype)
                config = setup.config()
                entry = (formatter, config, formatter.createCache(layer, idx, config))
                self._caches[cache_key] = entry
            formatter, config, cache = entry

            if isinstance(raw, float) and wtype in ("", "TextEdit", "Range"):
                text = format_number(raw)
            else:
                try:
                    text = formatter.representValue(layer, idx, config, cache, raw)
                except Exception:  # noqa: BLE001 - never let one bad formatter break the popup
                    text = str(raw)

            out.append(_classify(key, text, raw, wtype, config, project))
        return out


def _resolve_path(path, config, project):
    if os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path):
        return path
    root = (config or {}).get("DefaultRoot") or project.homePath()
    return os.path.normpath(os.path.join(root, path)) if root else path


def _classify(key, text, raw, wtype, config, project):
    s = str(raw).strip() if isinstance(raw, str) else ""
    lower = s.lower()
    if lower.startswith(("http://", "https://")):
        if lower.split("?")[0].endswith(IMAGE_EXTENSIONS):
            return Row(key, text, "image", s)
        return Row(key, text, "url", s)
    if s and (wtype == "ExternalResource" or lower.endswith(IMAGE_EXTENSIONS)):
        path = _resolve_path(s, config, project)
        if lower.endswith(IMAGE_EXTENSIONS):
            return Row(key, text, "image", path)
        return Row(key, text, "url", path)
    return Row(key, text)
