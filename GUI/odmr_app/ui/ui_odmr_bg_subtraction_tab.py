# -*- coding: utf-8 -*-
"""
UI definition for the Background Subtraction tab.

Built in pure Python (no .ui file) to keep the workflow self-contained.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget,
)


class Ui_bg_sub_tab_content:
    """UI layout for the Background Subtraction tab."""

    def setupUi(self, parent: QWidget):
        """Build and attach all widgets to *parent*."""
        root = QVBoxLayout(parent)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Files ────────────────────────────────────────────────────────
        files_group = QGroupBox("Files")
        files_form = QFormLayout(files_group)

        self.bg_path_edit = QLineEdit()
        self.bg_path_edit.setPlaceholderText("Path to background .npz file (no sample)")
        self.bg_browse_btn = QPushButton("Browse\u2026")
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.bg_path_edit, stretch=1)
        bg_row.addWidget(self.bg_browse_btn)
        files_form.addRow("Background (.npz):", bg_row)

        self.sample_path_edit = QLineEdit()
        self.sample_path_edit.setPlaceholderText("Path to sample .npz file (with sample)")
        self.sample_browse_btn = QPushButton("Browse\u2026")
        sample_row = QHBoxLayout()
        sample_row.addWidget(self.sample_path_edit, stretch=1)
        sample_row.addWidget(self.sample_browse_btn)
        files_form.addRow("Sample (.npz):", sample_row)

        root.addWidget(files_group)

        # ── Parameters ───────────────────────────────────────────────────
        params_group = QGroupBox("Parameters")
        params_hbox = QHBoxLayout(params_group)

        params_hbox.addWidget(QLabel("Gaussian sigma:"))
        self.sigma_spin = QDoubleSpinBox()
        self.sigma_spin.setRange(0.5, 100.0)
        self.sigma_spin.setSingleStep(0.5)
        self.sigma_spin.setValue(7.0)
        self.sigma_spin.setSuffix(" px")
        self.sigma_spin.setDecimals(1)
        params_hbox.addWidget(self.sigma_spin)

        params_hbox.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.run_btn = QPushButton("Run Background Subtraction")
        self.run_btn.setMinimumWidth(220)
        params_hbox.addWidget(self.run_btn)

        root.addWidget(params_group)

        # ── Color Range ──────────────────────────────────────────────────
        color_group = QGroupBox("Color Range (Gauss)")
        color_form = QFormLayout(color_group)

        self._vrange_rows: dict = {}  # key → (auto_chk, min_spin, max_spin)
        for key, label in [
            ("raw",        "Raw:"),
            ("denoised",   "Denoised:"),
            ("processed",  "Processed:"),
            ("subtracted", "Subtracted:"),
        ]:
            auto_chk = QCheckBox("Auto")
            auto_chk.setChecked(True)
            min_spin = QDoubleSpinBox()
            min_spin.setRange(-1000.0, 1000.0)
            min_spin.setDecimals(4)
            min_spin.setSingleStep(0.001)
            min_spin.setValue(-0.1)
            min_spin.setEnabled(False)
            max_spin = QDoubleSpinBox()
            max_spin.setRange(-1000.0, 1000.0)
            max_spin.setDecimals(4)
            max_spin.setSingleStep(0.001)
            max_spin.setValue(0.1)
            max_spin.setEnabled(False)

            row_widget = QHBoxLayout()
            row_widget.addWidget(auto_chk)
            row_widget.addWidget(QLabel("min"))
            row_widget.addWidget(min_spin)
            row_widget.addWidget(QLabel("max"))
            row_widget.addWidget(max_spin)
            row_widget.addStretch()

            color_form.addRow(label, row_widget)
            self._vrange_rows[key] = (auto_chk, min_spin, max_spin)

        self.replot_btn = QPushButton("Replot")
        self.replot_btn.setEnabled(False)
        color_form.addRow("", self.replot_btn)

        root.addWidget(color_group)

        # ── Stats label ───────────────────────────────────────────────────
        self.stats_label = QLabel("Stats: \u2014")
        root.addWidget(self.stats_label)

        # ── Figure canvas placeholder ─────────────────────────────────────
        # The tab handler injects FigureCanvasQTAgg here at runtime.
        self.canvas_placeholder = QWidget()
        self.canvas_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.canvas_placeholder, stretch=1)

        # ── Save ──────────────────────────────────────────────────────────
        save_group = QGroupBox("Save")
        save_hbox = QHBoxLayout(save_group)
        save_hbox.addWidget(QLabel("Prefix:"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setMaximumWidth(160)
        save_hbox.addWidget(self.prefix_edit)
        save_hbox.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.save_fig_btn = QPushButton("Save Fig")
        self.save_fig_btn.setEnabled(False)
        self.save_data_btn = QPushButton("Save Data")
        self.save_data_btn.setEnabled(False)
        save_hbox.addWidget(self.save_fig_btn)
        save_hbox.addWidget(self.save_data_btn)
        root.addWidget(save_group)
