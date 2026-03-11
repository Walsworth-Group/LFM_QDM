"""
ReconstructionTabHandler -- Wires the Reconstruction tab UI to LFMAppState
and ReconstructionWorker.

Manages input image selection, deconvolution parameter controls, and
reconstruction execution with live progress.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QSpinBox, QCheckBox,
    QProgressBar, QFileDialog, QMessageBox, QRadioButton,
    QButtonGroup, QSplitter,
)
from PySide6.QtCore import Slot, Qt

from state.lfm_state import LFMAppState, CalibrationStage


class ReconstructionTabHandler:
    """
    Handles the Reconstruction tab: input selection, deconvolution parameters,
    reconstruction execution, and result preview.

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
        """Build the reconstruction tab UI programmatically."""
        outer = QHBoxLayout(parent)

        # -- Left panel: controls --
        controls = QWidget()
        ctrl_layout = QVBoxLayout(controls)

        # Input source group
        input_group = QGroupBox("Input Image")
        input_layout = QVBoxLayout(input_group)

        self._radio_camera = QRadioButton("From Camera")
        self._radio_file = QRadioButton("From File")
        self._radio_file.setChecked(True)
        self._source_group = QButtonGroup()
        self._source_group.addButton(self._radio_camera)
        self._source_group.addButton(self._radio_file)
        input_layout.addWidget(self._radio_camera)
        input_layout.addWidget(self._radio_file)

        file_row = QHBoxLayout()
        self._file_path_edit = QLineEdit()
        self._file_path_edit.setPlaceholderText("Path to raw LFM image .tif")
        self._btn_browse = QPushButton("Browse...")
        file_row.addWidget(self._file_path_edit)
        file_row.addWidget(self._btn_browse)
        input_layout.addLayout(file_row)

        self._btn_use_camera = QPushButton("Use Current Camera Frame")
        input_layout.addWidget(self._btn_use_camera)

        self._input_status = QLabel("No input image loaded.")
        input_layout.addWidget(self._input_status)

        ctrl_layout.addWidget(input_group)

        # Parameters group
        param_group = QGroupBox("Deconvolution Parameters")
        param_grid = QGridLayout(param_group)

        param_grid.addWidget(QLabel("Iterations:"), 0, 0)
        self._iter_spin = QSpinBox()
        self._iter_spin.setRange(1, 50)
        self._iter_spin.setValue(self.state.num_iterations)
        param_grid.addWidget(self._iter_spin, 0, 1)

        self._filter_check = QCheckBox("Anti-aliasing filter")
        self._filter_check.setChecked(self.state.filter_flag)
        param_grid.addWidget(self._filter_check, 1, 0, 1, 2)

        ctrl_layout.addWidget(param_group)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._btn_reconstruct = QPushButton("Reconstruct")
        self._btn_reconstruct.setMinimumHeight(40)
        self._btn_abort = QPushButton("Abort")
        self._btn_abort.setEnabled(False)
        btn_layout.addWidget(self._btn_reconstruct)
        btn_layout.addWidget(self._btn_abort)
        ctrl_layout.addLayout(btn_layout)

        # Progress
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        ctrl_layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        ctrl_layout.addWidget(self._progress_label)

        ctrl_layout.addStretch()

        # -- Right panel: preview --
        viz = QWidget()
        viz_layout = QVBoxLayout(viz)

        viz_layout.addWidget(QLabel("Raw Input Image:"))
        self._raw_view = pg.GraphicsLayoutWidget()
        self._raw_viewbox = self._raw_view.addViewBox()
        self._raw_viewbox.setAspectLocked(True)
        self._raw_image_item = pg.ImageItem()
        self._raw_viewbox.addItem(self._raw_image_item)
        viz_layout.addWidget(self._raw_view, stretch=1)

        viz_layout.addWidget(QLabel("Reconstruction Preview (middle slice):"))
        self._preview_view = pg.GraphicsLayoutWidget()
        self._preview_viewbox = self._preview_view.addViewBox()
        self._preview_viewbox.setAspectLocked(True)
        self._preview_image_item = pg.ImageItem()
        self._preview_viewbox.addItem(self._preview_image_item)
        viz_layout.addWidget(self._preview_view, stretch=1)

        self._btn_view_volume = QPushButton("View in Volume Viewer")
        self._btn_view_volume.setEnabled(False)
        viz_layout.addWidget(self._btn_view_volume)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(viz)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    def _connect_signals(self):
        """Wire UI widgets to state and actions."""
        self._btn_browse.clicked.connect(self._on_browse)
        self._btn_use_camera.clicked.connect(self._on_use_camera)
        self._btn_reconstruct.clicked.connect(self._on_reconstruct)
        self._btn_abort.clicked.connect(self._on_abort)

        self._iter_spin.valueChanged.connect(
            lambda v: setattr(self.state, 'num_iterations', v))
        self._filter_check.toggled.connect(
            lambda v: setattr(self.state, 'filter_flag', v))

        # State signals
        self.state.recon_running_changed.connect(self._on_running_changed)
        self.state.recon_progress.connect(self._on_progress)
        self.state.recon_completed.connect(self._on_completed)
        self.state.recon_failed.connect(self._on_failed)

    def _sync_from_state(self):
        """Push current state values into UI widgets."""
        self._iter_spin.setValue(self.state.num_iterations)
        self._filter_check.setChecked(self.state.filter_flag)

    # ------------------------------------------------------------------
    # Input selection
    # ------------------------------------------------------------------

    @Slot()
    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Raw LFM Image", "",
            "TIFF files (*.tif *.tiff);;All files (*)")
        if path:
            self._file_path_edit.setText(path)
            self._load_raw_image(path)

    @Slot()
    def _on_use_camera(self):
        """Use the raw image previously captured from camera tab."""
        if self.state.recon_raw_image is not None:
            self._show_raw_preview(self.state.recon_raw_image)
            self._input_status.setText(
                f"Camera frame: {self.state.recon_raw_image.shape}")
        else:
            QMessageBox.warning(
                None, "No Frame",
                "Capture a raw LFM image from the Camera tab first.")

    def _load_raw_image(self, path: str):
        """Load a TIFF file as the raw input image."""
        try:
            import tifffile
            img = tifffile.imread(path)
            self.state.recon_raw_image = img
            self._show_raw_preview(img)
            self._input_status.setText(
                f"Loaded: {Path(path).name} ({img.shape})")
        except Exception as exc:
            QMessageBox.warning(
                None, "Load Error", f"Could not load image:\n{exc}")

    def _show_raw_preview(self, img: np.ndarray):
        """Display the raw image in the preview panel."""
        self._raw_image_item.setImage(img.T.astype(float))

    # ------------------------------------------------------------------
    # Reconstruction execution
    # ------------------------------------------------------------------

    @Slot()
    def _on_reconstruct(self):
        """Start reconstruction worker."""
        if not self.state.can_start_reconstruction():
            msg = []
            if self.state.calibration_stage != CalibrationStage.OPERATORS_READY:
                msg.append("Calibration not complete.")
            if self.state.recon_raw_image is None:
                msg.append("No input image loaded.")
            if self.state.recon_is_running:
                msg.append("Reconstruction already running.")
            QMessageBox.warning(
                None, "Cannot Reconstruct", "\n".join(msg))
            return

        from workers.reconstruction_worker import ReconstructionWorker

        self.state.recon_is_running = True
        self._btn_reconstruct.setEnabled(False)
        self._btn_abort.setEnabled(True)
        self._progress_bar.setRange(0, self.state.num_iterations)
        self._progress_bar.setValue(0)

        calibration = {
            "Camera": self.state.camera_dict,
            "H": self.state.H,
            "Ht": self.state.Ht,
            "LensletCenters": self.state.lenslet_centers,
            "Resolution": self.state.resolution,
            "trans": self.state.trans,
            "imgSize": self.state.img_size,
            "texSize": self.state.tex_size,
            "volumeSize": self.state.volume_size,
            "kernelFFT": self.state.kernel_fft,
        }

        self._worker = ReconstructionWorker(
            raw_image=self.state.recon_raw_image,
            calibration=calibration,
            num_iterations=self.state.num_iterations,
            filter_flag=self.state.filter_flag,
        )
        self._worker.iteration_completed.connect(self._on_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.state.status_message.emit("Reconstruction started...")

    @Slot()
    def _on_abort(self):
        if self._worker is not None:
            self._worker.abort()
            self._btn_abort.setEnabled(False)
            self.state.status_message.emit("Reconstruction abort requested.")

    def abort_if_running(self):
        """Called by main window on close."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(5000)

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    @Slot(bool)
    def _on_running_changed(self, is_running: bool):
        self._btn_reconstruct.setEnabled(not is_running)

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(current)
        self._progress_label.setText(f"Iteration {current}/{total}")

    @Slot(object)
    def _on_completed(self, volume: np.ndarray):
        self.state.recon_volume = volume
        self.state.recon_is_running = False
        self._btn_reconstruct.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._btn_view_volume.setEnabled(True)
        self._worker = None

        # Show middle depth slice as preview
        mid = volume.shape[2] // 2
        self._preview_image_item.setImage(volume[:, :, mid].T)
        self._progress_label.setText(
            f"Done. Volume shape: {volume.shape}")
        self.state.status_message.emit(
            f"Reconstruction complete. Volume: {volume.shape}")

    @Slot(str)
    def _on_failed(self, error_msg: str):
        self.state.recon_is_running = False
        self._btn_reconstruct.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._worker = None
        QMessageBox.critical(None, "Reconstruction Failed", error_msg)
        self.state.status_message.emit(f"Reconstruction failed: {error_msg}")
