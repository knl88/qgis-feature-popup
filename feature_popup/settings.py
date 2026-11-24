from dataclasses import dataclass, fields

from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
)

_PREFIX = "feature_popup/"


@dataclass
class Settings:
    tolerance_px: int = 6
    max_per_layer: int = 25
    max_total: int = 100
    position: str = "right"  # "right" | "click"
    expand: str = "first"  # "first" | "all"
    hide_empty: bool = False
    include_rasters: bool = True

    @classmethod
    def load(cls):
        s = QgsSettings()
        out = cls()
        for f in fields(cls):
            default = getattr(out, f.name)
            value = s.value(_PREFIX + f.name, default)
            if isinstance(default, bool):
                value = value in (True, "true", "1", 1)
            else:
                value = type(default)(value)
            setattr(out, f.name, value)
        return out

    def save(self):
        s = QgsSettings()
        for f in fields(self):
            s.setValue(_PREFIX + f.name, getattr(self, f.name))


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feature Popup settings")
        self._settings = settings

        self.tolerance = QSpinBox(minimum=1, maximum=50, suffix=" px")
        self.tolerance.setValue(settings.tolerance_px)
        self.per_layer = QSpinBox(minimum=1, maximum=1000)
        self.per_layer.setValue(settings.max_per_layer)
        self.total = QSpinBox(minimum=1, maximum=5000)
        self.total.setValue(settings.max_total)

        self.position = QComboBox()
        self.position.addItem("Docked to the right of the map", "right")
        self.position.addItem("Next to the clicked point", "click")
        self.position.setCurrentIndex(max(0, self.position.findData(settings.position)))

        self.expand = QComboBox()
        self.expand.addItem("Only the first feature", "first")
        self.expand.addItem("All features", "all")
        self.expand.setCurrentIndex(max(0, self.expand.findData(settings.expand)))

        self.hide_empty = QCheckBox("Hide fields with empty / NULL values")
        self.hide_empty.setChecked(settings.hide_empty)
        self.rasters = QCheckBox("Include local raster values")
        self.rasters.setChecked(settings.include_rasters)

        form = QFormLayout(self)
        form.addRow("Click tolerance", self.tolerance)
        form.addRow("Max features per layer", self.per_layer)
        form.addRow("Max features total", self.total)
        form.addRow("Popup position", self.position)
        form.addRow("Expand", self.expand)
        form.addRow(self.hide_empty)
        form.addRow(self.rasters)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        s = self._settings
        s.tolerance_px = self.tolerance.value()
        s.max_per_layer = self.per_layer.value()
        s.max_total = self.total.value()
        s.position = self.position.currentData()
        s.expand = self.expand.currentData()
        s.hide_empty = self.hide_empty.isChecked()
        s.include_rasters = self.rasters.isChecked()
        s.save()
        super().accept()
