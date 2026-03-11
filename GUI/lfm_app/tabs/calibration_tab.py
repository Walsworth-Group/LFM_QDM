"""
CalibrationTabHandler -- Wires the Calibration tab UI to LFMAppState and
CalibrationWorker.

Manages file inputs (YAML config, white image), pyolaf parameter controls,
calibration execution, and lenslet center visualization.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox, QSpinBox,
    QProgressBar, QFileDialog, QMessageBox, QSplitter,
)
from PySide6.QtCore import Slot, Qt

from state.lfm_state import LFMAppState, CalibrationStage


class CalibrationTabHandler:
    """
    Handles the Calibration tab: file inputs, parameter controls, calibration
    execution with CalibrationWorker, and lenslet overlay visualization.

    Parameters
    ----------
    tab_widget : QWidget
        The bare QWidget placeholder from the main tab widget.
    state : LFMAppState
        Central application state.
    stop_streaming_fn : callable
        Function to stop camera streaming before acquisition.
    set_camera_mode_fn : callable
        Function to set camera mode.
    """

    def __init__(self, tab_widget: QWidget, state: LFMAppState,
                 stop_streaming_fn=None, set_camera_mode_fn=None):
        self.state = state
        self._stop_streaming = stop_streaming_fn or (lambda: None)
        self._set_camera_mode = set_camera_mode_fn or (lambda m: None)
        self._worker = None

        self._build_ui(tab_widget)
        self._connect_signals()
        self._sync_from_state()

    def _build_ui(self, parent: QWidget):
        """Build the calibration tab UI programmatically."""
        outer = QHBoxLayout(parent)

        # -- Left panel: controls --
        controls = QWidget()
        ctrl_layout = QVBoxLayout(controls)

        # File inputs group
        file_group = QGroupBox("Input Files")
        file_grid = QGridLayout(file_group)

        file_grid.addWidget(QLabel("Config YAML:"), 0, 0)
        self._config_path_edit = QLineEdit()
        self._config_path_edit.setPlaceholderText("Path to LFM config .yaml")
        file_grid.addWidget(self._config_path_edit, 0, 1)
        self._btn_browse_config = QPushButton("Browse...")
        file_grid.addWidget(self._btn_browse_config, 0, 2)

        file_grid.addWidget(QLabel("White Image:"), 1, 0)
        self._white_path_edit = QLineEdit()
        self._white_path_edit.setPlaceholderText("Path to calibration .tif")
        file_grid.addWidget(self._white_path_edit, 1, 1)
        self._btn_browse_white = QPushButton("Browse...")
        file_grid.addWidget(self._btn_browse_white, 1, 2)

        ctrl_layout.addWidget(file_group)

        # Parameters group
        param_group = QGroupBox("Reconstruction Parameters")
        param_grid = QGridLayout(param_group)

        row = 0
        param_grid.addWidget(QLabel("Depth range min (um):"), row, 0)
        self._depth_min_spin = QDoubleSpinBox()
        self._depth_min_spin.setRange(-10000, 10000)
        self._depth_min_spin.setValue(self.state.depth_range_min)
        param_grid.addWidget(self._depth_min_spin, row, 1)

        row += 1
        param_grid.addWidget(QLabel("Depth range max (um):"), row, 0)
        self._depth_max_spin = QDoubleSpinBox()
        self._depth_max_spin.setRange(-10000, 10000)
        self._depth_max_spin.setValue(self.state.depth_range_max)
        param_grid.addWidget(self._depth_max_spin, row, 1)

        row += 1
        param_grid.addWidget(QLabel("Depth step (um):"), row, 0)
        self._depth_step_spin = QDoubleSpinBox()
        self._depth_step_spin.setRange(1, 10000)
        self._depth_step_spin.setValue(self.state.depth_step)
        param_grid.addWidget(self._depth_step_spin, row, 1)

        row += 1
        param_grid.addWidget(QLabel("Lenslet spacing (px):"), row, 0)
        self._spacing_spin = QSpinBox()
        self._spacing_spin.setRange(1, 100)
        self._spacing_spin.setValue(self.state.new_spacing_px)
        param_grid.addWidget(self._spacing_spin, row, 1)

        row += 1
        param_grid.addWidget(QLabel("Super-res factor:"), row, 0)
        self._superres_spin = QSpinBox()
        self._superres_spin.setRange(1, 20)
        self._superres_spin.setValue(self.state.super_res_factor)
        param_grid.addWidget(self._superres_spin, row, 1)

        row += 1
        param_grid.addWidget(QLabel("Lanczos window:"), row, 0)
        self._lanczos_spin = QSpinBox()
        self._lanczos_spin.setRange(1, 10)
        self._lanczos_spin.setValue(self.state.lanczos_window_size)
        param_grid.addWidget(self._lanczos_spin, row, 1)

        ctrl_layout.addWidget(param_group)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._btn_run = QPushButton("Run Calibration")
        self._btn_run.setMinimumHeight(40)
        self._btn_abort = QPushButton("Abort")
        self._btn_abort.setEnabled(False)
        btn_layout.addWidget(self._btn_run)
        btn_layout.addWidget(self._btn_abort)
        ctrl_layout.addLayout(btn_layout)

        # Save/Load calibration
        calib_io_layout = QHBoxLayout()
        self._btn_save_calib = QPushButton("Save Calibration...")
        self._btn_load_calib = QPushButton("Load Calibration...")
        calib_io_layout.addWidget(self._btn_save_calib)
        calib_io_layout.addWidget(self._btn_load_calib)
        ctrl_layout.addLayout(calib_io_layout)

        # Progress
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 5)
        self._progress_bar.setValue(0)
        ctrl_layout.addWidget(self._progress_bar)

        self._stage_label = QLabel("Stage: Unconfigured")
        ctrl_layout.addWidget(self._stage_label)

        ctrl_layout.addStretch()

        # -- Right panel: visualization --
        viz = QWidget()
        viz_layout = QVBoxLayout(viz)

        self._info_label = QLabel("Load config and white image to begin.")
        self._info_label.setWordWrap(True)
        viz_layout.addWidget(self._info_label)

        # Lenslet overlay widget (lazy import to avoid circular deps)
        from widgets.lenslet_overlay import LensletOverlayWidget
        self._overlay_widget = LensletOverlayWidget()
        viz_layout.addWidget(self._overlay_widget, stretch=1)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(viz)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    def _connect_signals(self):
        """Wire UI widgets to state and actions."""
        # Browse buttons
        self._btn_browse_config.clicked.connect(self._on_browse_config)
        self._btn_browse_white.clicked.connect(self._on_browse_white)

        # Parameter spinboxes → state
        self._depth_min_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'depth_range_min', v))
        self._depth_max_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'depth_range_max', v))
        self._depth_step_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'depth_step', v))
        self._spacing_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'new_spacing_px', v))
        self._superres_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'super_res_factor', v))
        self._lanczos_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'lanczos_window_size', v))

        # Path edits → state
        self._config_path_edit.editingFinished.connect(
            lambda: setattr(self.state, 'config_yaml_path',
                            self._config_path_edit.text()))
        self._white_path_edit.editingFinished.connect(
            lambda: setattr(self.state, 'white_image_path',
                            self._white_path_edit.text()))

        # Action buttons
        self._btn_run.clicked.connect(self._on_run_calibration)
        self._btn_abort.clicked.connect(self._on_abort)
        self._btn_save_calib.clicked.connect(self._on_save_calibration)
        self._btn_load_calib.clicked.connect(self._on_load_calibration)

        # State signals → UI
        self.state.calibration_stage_changed.connect(self._on_stage_changed)
        self.state.calibration_progress.connect(self._on_progress)
        self.state.calibration_completed.connect(self._on_completed)
        self.state.calibration_failed.connect(self._on_failed)

    def _sync_from_state(self):
        """Push current state values into UI widgets."""
        self._config_path_edit.setText(self.state.config_yaml_path)
        self._white_path_edit.setText(self.state.white_image_path)
        self._depth_min_spin.setValue(self.state.depth_range_min)
        self._depth_max_spin.setValue(self.state.depth_range_max)
        self._depth_step_spin.setValue(self.state.depth_step)
        self._spacing_spin.setValue(self.state.new_spacing_px)
        self._superres_spin.setValue(self.state.super_res_factor)
        self._lanczos_spin.setValue(self.state.lanczos_window_size)

    # ------------------------------------------------------------------
    # Browse actions
    # ------------------------------------------------------------------

    @Slot()
    def _on_browse_config(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select LFM Config YAML", "",
            "YAML files (*.yaml *.yml);;All files (*)")
        if path:
            self._config_path_edit.setText(path)
            self.state.config_yaml_path = path

    @Slot()
    def _on_browse_white(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select White Calibration Image", "",
            "TIFF files (*.tif *.tiff);;All files (*)")
        if path:
            self._white_path_edit.setText(path)
            self.state.white_image_path = path

    # ------------------------------------------------------------------
    # Calibration execution
    # ------------------------------------------------------------------

    @Slot()
    def _on_run_calibration(self):
        """Start calibration worker."""
        if not self.state.can_start_calibration():
            QMessageBox.warning(
                None, "Missing Inputs",
                "Please provide both a config YAML file and a white "
                "calibration image before running calibration.")
            return

        from workers.calibration_worker import CalibrationWorker

        self._btn_run.setEnabled(False)
        self._btn_abort.setEnabled(True)
        self._progress_bar.setValue(0)

        self._worker = CalibrationWorker(
            config_yaml_path=self.state.config_yaml_path,
            white_image_path=self.state.white_image_path,
            white_image_array=self.state.white_image,
            depth_range=(self.state.depth_range_min,
                         self.state.depth_range_max),
            depth_step=self.state.depth_step,
            new_spacing_px=self.state.new_spacing_px,
            super_res_factor=self.state.super_res_factor,
            lanczos_window_size=self.state.lanczos_window_size,
        )
        self._worker.stage_progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.state.status_message.emit("Calibration started...")

    @Slot()
    def _on_abort(self):
        """Abort running calibration."""
        if self._worker is not None:
            self._worker.abort()
            self._btn_abort.setEnabled(False)
            self.state.status_message.emit("Calibration abort requested.")

    def abort_if_running(self):
        """Called by main window on close."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    @Slot(str, int, int)
    def _on_progress(self, stage_name: str, current: int, total: int):
        self._stage_label.setText(f"Stage: {stage_name}")
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(current)

    @Slot(dict)
    def _on_completed(self, result: dict):
        self.state.store_calibration_result(result)
        self._btn_run.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._worker = None

        # Update visualization
        if self.state.white_image is not None:
            self._overlay_widget.set_white_image(self.state.white_image)
        if self.state.lenslet_centers is not None:
            centers = self.state.lenslet_centers.get('px', None)
            if centers is not None:
                self._overlay_widget.set_lenslet_centers(centers)

        # Update info label
        n_depths = len(self.state.resolution.get('depths', []))
        self._info_label.setText(
            f"Calibration complete. Depth planes: {n_depths}")

        self.state.status_message.emit(
            f"Calibration complete ({n_depths} depth planes).")

    @Slot(str)
    def _on_failed(self, error_msg: str):
        self._btn_run.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._worker = None
        QMessageBox.critical(None, "Calibration Failed", error_msg)
        self.state.status_message.emit(f"Calibration failed: {error_msg}")

    @Slot(str)
    def _on_stage_changed(self, stage: str):
        self._stage_label.setText(f"Stage: {stage}")

    # ------------------------------------------------------------------
    # Save/Load calibration
    # ------------------------------------------------------------------

    @Slot()
    def _on_save_calibration(self):
        """Save calibration results to .npz file."""
        if self.state.calibration_stage != CalibrationStage.OPERATORS_READY:
            QMessageBox.warning(
                None, "No Calibration",
                "Run calibration first before saving.")
            return

        path, _ = QFileDialog.getSaveFileName(
            None, "Save Calibration", "", "NumPy files (*.npz)")
        if not path:
            return

        try:
            save_dict = {
                'config_yaml_path': self.state.config_yaml_path,
                'white_image_path': self.state.white_image_path,
                'depth_range_min': self.state.depth_range_min,
                'depth_range_max': self.state.depth_range_max,
                'depth_step': self.state.depth_step,
                'new_spacing_px': self.state.new_spacing_px,
                'super_res_factor': self.state.super_res_factor,
            }
            # Store large arrays
            if self.state.H is not None:
                save_dict['H'] = np.array(self.state.H, dtype=object)
            if self.state.Ht is not None:
                save_dict['Ht'] = np.array(self.state.Ht, dtype=object)
            if self.state.lenslet_centers is not None:
                for k, v in self.state.lenslet_centers.items():
                    save_dict[f'lenslet_centers_{k}'] = v
            if self.state.resolution is not None:
                for k, v in self.state.resolution.items():
                    save_dict[f'resolution_{k}'] = v

            np.savez(path, **save_dict)
            self.state.status_message.emit(f"Calibration saved to {path}")
        except Exception as exc:
            QMessageBox.warning(
                None, "Save Error", f"Could not save calibration:\n{exc}")

    @Slot()
    def _on_load_calibration(self):
        """Load calibration results from .npz file."""
        path, _ = QFileDialog.getOpenFileName(
            None, "Load Calibration", "", "NumPy files (*.npz)")
        if not path:
            return

        try:
            data = np.load(path, allow_pickle=True)
            # Restore what we can — full restoration requires re-running
            # calibration with the original config, but this saves H/Ht
            if 'H' in data:
                self.state.H = data['H']
            if 'Ht' in data:
                self.state.Ht = data['Ht']
            self.state.calibration_stage = CalibrationStage.OPERATORS_READY
            self.state.status_message.emit(f"Calibration loaded from {path}")
        except Exception as exc:
            QMessageBox.warning(
                None, "Load Error", f"Could not load calibration:\n{exc}")
