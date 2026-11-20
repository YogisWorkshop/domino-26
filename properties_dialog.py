from PySide6.QtWidgets import (
    QDialog, QFormLayout, QSpinBox, QLineEdit, QComboBox, QCheckBox, QDialogButtonBox, QLabel
)
from PySide6.QtCore import QSize

from tile import uses_turnout_id

class PropertiesDialog(QDialog):
    def __init__(self, tile, parent=None):
        super().__init__(parent)
        self.tile = tile
        self.setMinimumSize(QSize(400, 300))

        title = getattr(tile, "label", "") or getattr(tile, "id", "") or tile.__class__.__name__
        self.setWindowTitle(f"{title} Properties")

        self.fields = {}

        layout = QFormLayout(self)

        for spec in tile.property_specs:
            field = self._build_field(spec)
            self.fields[spec["key"]] = field
            layout.addRow(tile.field_label(spec), field)
            state = tile.field_state(spec["key"])      # the tile decides what is relevant
            if state == "hidden":
                layout.setRowVisible(field, False)
            elif state == "disabled":
                field.setEnabled(False)

        self.warning = QLabel("DCC-EX in Turnout ID mode needs a number here.")
        self.warning.setStyleSheet("color: #c0392b;")
        self.warning.setWordWrap(True)          # the window is narrower than the message
        layout.addRow(self.warning)
        if uses_turnout_id() and tile.numeric_id_keys:
            for key in tile.numeric_id_keys:
                self.fields[key].textChanged.connect(lambda _text: self._check_numeric())
        self._check_numeric()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _check_numeric(self):
        """Warn while a field that must be a number (DCC-EX Turnout ID mode) is not."""
        bad = False
        if uses_turnout_id():
            for key in self.tile.numeric_id_keys:
                if self.tile.field_state(key) == "hidden":
                    continue
                text = self.fields[key].text()
                if not (text.isdigit() and int(text) > 0):
                    bad = True
        if bad == self.warning.isHidden():      # needs to change (isHidden: hidden by us, not just a closed dialog)
            self.warning.setVisible(bad)
            if self.isVisible():
                self.adjustSize()               # make room for the wrapped message (or give it back)

    def _build_field(self, spec):
        current_value = getattr(self.tile, spec["key"])

        if spec["type"] == int:
            field = QSpinBox()
            field.setRange(0, 9999)
            field.setValue(current_value)
            return field

        if spec["type"] == str:
            field = QLineEdit()
            field.setText(current_value)
            if "max_length" in spec:
                field.setMaxLength(spec["max_length"])
            return field

        if spec["type"] == bool:
            field = QCheckBox()
            field.setChecked(current_value)
            return field

        if spec["type"] == "choice":
            field = QComboBox()
            field.addItems(spec["choices"])
            field.setCurrentText(current_value)
            return field


        raise ValueError(f"Unsupported property type: {spec['type']}")

    def apply_to_tile(self):
        old_id = getattr(self.tile, "id", None)
        for key, field in self.fields.items():
            if isinstance(field, QSpinBox):
                setattr(self.tile, key, field.value())
            elif isinstance(field, QLineEdit):
                setattr(self.tile, key, field.text())
            elif isinstance(field, QComboBox):
                setattr(self.tile, key, field.currentText())
            elif isinstance(field, QCheckBox):
                setattr(self.tile, key, field.isChecked())
        new_id = getattr(self.tile, "id", None)
        scene = self.tile.scene()
        if scene is not None and old_id and new_id != old_id \
                and not getattr(self.tile, "linked_to", ""):
            scene.relink(old_id, new_id)   # keep secondaries pointing at us