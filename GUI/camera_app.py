"""
Basler Camera Streaming Application

PySide6 application for live camera streaming, image averaging, and data saving.
Follows architecture defined in claude_app.md.
"""

import sys
import json
import queue
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QGridLayout,
    QCheckBox, QFileDialog, QComboBox, QSpinBox, QSlider
)
from PySide6.QtCore import Qt, Slot, QTimer
import pyqtgraph as pg

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.camera_state import CameraState
from workers.camera_worker import CameraWorker
from workers.camera_consumer import CameraConsumer

# Configuration file path
CONFIG_FILE = Path(__file__).parent / "config" / "basler_camera_config.json"


class BaslerCameraApp(QMainWindow):
    """
    Main window for Basler camera streaming application.

    Architecture:
    - CameraState: single source of truth
    - CameraWorker: producer thread for frame acquisition
    - CameraConsumer: consumer thread for averaging and saving
    - Producer-consumer pattern with queue.Queue
    """

    def __init__(self, state=None):
        super().__init__()
        # Use provided state or create new one
        self.state = state if state is not None else CameraState()

        # Worker threads
        self.worker = None
        self.consumer = None
        self.frame_queue = None

        # UI update throttling
        self.last_live_update = 0
        self.last_status_update = 0

        # Frame storage for mouse hover
        self.current_live_frame = None
        self.current_averaged_frame = None

        # Last known mouse position for each panel (widget coords), None if outside
        self._last_live_mouse_pos = None
        self._last_avg_mouse_pos = None

        # FPS tracking
        self.fps_timestamps = []
        self.fps_window_size = 10
        self.last_fps_value = 0.0

        # Load configuration (before init_ui so state is ready;
        # UI widgets populated after init_ui via _apply_config_to_ui)
        self.load_config()

        self.init_ui()
        self.connect_signals()
        self._apply_config_to_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Basler Camera Streaming")
        self.setGeometry(100, 100, 1400, 600)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # === Top section: Live and Averaged Images ===
        images_layout = QHBoxLayout()

        # Live image panel
        live_panel = self.create_live_image_panel()
        images_layout.addWidget(live_panel, 1)

        # Averaged image panel
        avg_panel = self.create_averaged_image_panel()
        images_layout.addWidget(avg_panel, 1)

        main_layout.addLayout(images_layout, 3)

        # === Bottom section: Controls ===
        controls_layout = QHBoxLayout()

        # Camera controls
        camera_controls = self.create_camera_controls()
        controls_layout.addWidget(camera_controls)

        # Save controls
        save_controls = self.create_save_controls()
        controls_layout.addWidget(save_controls)

        main_layout.addLayout(controls_layout, 1)

        # === Status bar ===
        self.statusLabel = QLabel("Status: Ready")
        main_layout.addWidget(self.statusLabel)

    def create_live_image_panel(self):
        """Create live image display panel."""
        panel = QGroupBox("Live Image")
        layout = QVBoxLayout()
        panel.setLayout(layout)

        # Top bar: Enable checkbox + Save App Configuration button
        top_bar = QHBoxLayout()
        self.live_display_checkbox = QCheckBox("Enable Live Display")
        self.live_display_checkbox.setChecked(self.state.camera_live_display_enabled)
        self.live_display_checkbox.toggled.connect(self.on_live_display_toggled)
        top_bar.addWidget(self.live_display_checkbox)
        top_bar.addStretch()
        save_config_button = QPushButton("Save App Configuration")
        save_config_button.setFixedWidth(160)
        save_config_button.clicked.connect(self.save_config)
        top_bar.addWidget(save_config_button)
        layout.addLayout(top_bar)

        # Image view - minimal display (no ROI/Menu/Histogram)
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')

        self.live_graphics_view = pg.GraphicsView()
        self.live_view_box = pg.ViewBox()
        self.live_graphics_view.setCentralItem(self.live_view_box)
        self.live_image_item = pg.ImageItem()
        self.live_view_box.addItem(self.live_image_item)

        # Lock aspect ratio to 1.6:1 (1920/1200)
        self.live_view_box.setAspectLocked(True, ratio=1.6)

        # Enable mouse tracking for hover
        self.live_graphics_view.setMouseTracking(True)
        self.live_graphics_view.viewport().installEventFilter(self)

        layout.addWidget(self.live_graphics_view)

        # Status bar
        status_layout = QHBoxLayout()
        self.live_status_label = QLabel("Pixels: --- | Stream: 0")
        status_layout.addWidget(self.live_status_label)

        self.saturation_label = QLabel("")
        status_layout.addWidget(self.saturation_label)
        status_layout.addStretch()

        layout.addLayout(status_layout)

        return panel

    def create_averaged_image_panel(self):
        """Create averaged image display panel."""
        panel = QGroupBox("Averaged Image")
        layout = QVBoxLayout()
        panel.setLayout(layout)

        # Controls
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Frames to Average:"))

        self.avg_frames_spinbox = QSpinBox()
        self.avg_frames_spinbox.setRange(1, 10000)
        self.avg_frames_spinbox.setValue(self.state.camera_num_frames_to_average)
        self.avg_frames_spinbox.valueChanged.connect(self.on_avg_frames_changed)
        controls_layout.addWidget(self.avg_frames_spinbox)

        self.avg_display_checkbox = QCheckBox("Enable Live Averaging")
        self.avg_display_checkbox.setChecked(self.state.camera_averaged_display_enabled)
        self.avg_display_checkbox.toggled.connect(self.on_avg_display_toggled)
        controls_layout.addWidget(self.avg_display_checkbox)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Image view - minimal display (no ROI/Menu/Histogram)
        self.averaged_graphics_view = pg.GraphicsView()
        self.averaged_view_box = pg.ViewBox()
        self.averaged_graphics_view.setCentralItem(self.averaged_view_box)
        self.averaged_image_item = pg.ImageItem()
        self.averaged_view_box.addItem(self.averaged_image_item)

        # Lock aspect ratio to 1.6:1 (1920/1200)
        self.averaged_view_box.setAspectLocked(True, ratio=1.6)

        # Enable mouse tracking for hover
        self.averaged_graphics_view.setMouseTracking(True)
        self.averaged_graphics_view.viewport().installEventFilter(self)

        layout.addWidget(self.averaged_graphics_view)

        # Status
        self.avg_status_label = QLabel("Averaged: 0")
        layout.addWidget(self.avg_status_label)

        return panel

    def create_camera_controls(self):
        """Create camera control panel.

        Uses a 4-column grid:
          col 0: left label    col 1: left widget (stretch=1)
          col 2: right label   col 3: right widget (stretch=1)
        Equal stretch on cols 1 and 3 keeps every row's widgets aligned.
        Wide items (Connect button, Start/Stop buttons, slider) span cols 2-3
        or cols 0-3 as appropriate.
        """
        panel = QGroupBox("Camera Controls")
        layout = QGridLayout()
        panel.setLayout(layout)

        # Equal stretch on the two widget columns so left and right halves
        # always have the same width, regardless of widget content.
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        row = 0

        # --- Row 0: Serial number | Connect button (spans right two cols) ---
        layout.addWidget(QLabel("Serial Number:"), row, 0)
        self.serial_input = QLineEdit(self.state.camera_serial_number)
        layout.addWidget(self.serial_input, row, 1)

        self.connect_button = QPushButton("Connect to Camera")
        self.connect_button.clicked.connect(self.on_connect_camera)
        layout.addWidget(self.connect_button, row, 2, 1, 2)

        row += 1

        # --- Row 1: Start Streaming | Stop Streaming (each half-width) ---
        self.start_button = QPushButton("Start Streaming")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.on_start_streaming)
        layout.addWidget(self.start_button, row, 0, 1, 2)

        self.stop_button = QPushButton("Stop Streaming")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.on_stop_streaming)
        layout.addWidget(self.stop_button, row, 2, 1, 2)

        row += 1

        # --- Row 2: Exposure (µs) spinbox | slider (spans right two cols) ---
        layout.addWidget(QLabel("Exposure (µs):"), row, 0)
        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setRange(0, 100000)
        self.exposure_spinbox.setValue(int(self.state.camera_exposure_us))
        self.exposure_spinbox.valueChanged.connect(self.on_exposure_changed)
        layout.addWidget(self.exposure_spinbox, row, 1)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setRange(0, 400)  # Piecewise: linear 0-100, log 100-400
        initial_pos = self._exposure_to_slider(self.state.camera_exposure_us)
        self.exposure_slider.setValue(initial_pos)
        self.exposure_slider.valueChanged.connect(self.on_exposure_slider_changed)
        layout.addWidget(self.exposure_slider, row, 2, 1, 2)

        row += 1

        # --- Row 3: Binning X combo | Binning Y label + combo ---
        layout.addWidget(QLabel("Binning X:"), row, 0)
        self.binning_x_combo = QComboBox()
        self.binning_x_combo.addItems(['1', '2', '3', '4'])
        self.binning_x_combo.setCurrentText(str(self.state.camera_binning_x))
        self.binning_x_combo.currentTextChanged.connect(self.on_binning_changed)
        layout.addWidget(self.binning_x_combo, row, 1)

        layout.addWidget(QLabel("Binning Y:"), row, 2)
        self.binning_y_combo = QComboBox()
        self.binning_y_combo.addItems(['1', '2', '3', '4'])
        self.binning_y_combo.setCurrentText(str(self.state.camera_binning_y))
        self.binning_y_combo.currentTextChanged.connect(self.on_binning_changed)
        layout.addWidget(self.binning_y_combo, row, 3)

        row += 1

        # --- Row 4: Binning Mode combo | Pixel Format label + combo ---
        layout.addWidget(QLabel("Binning Mode:"), row, 0)
        self.binning_mode_combo = QComboBox()
        self.binning_mode_combo.addItems(['Average', 'Sum'])
        self.binning_mode_combo.setCurrentText(self.state.camera_binning_mode)
        self.binning_mode_combo.currentTextChanged.connect(self.on_binning_mode_changed)
        self.binning_mode_combo.currentTextChanged.connect(self._on_binning_mode_for_warning)
        layout.addWidget(self.binning_mode_combo, row, 1)

        layout.addWidget(QLabel("Pixel Format:"), row, 2)
        self.pixel_format_combo = QComboBox()
        self.pixel_format_combo.addItems(['Mono8', 'Mono12', 'Mono12p'])
        self.pixel_format_combo.setCurrentText(self.state.camera_pixel_format)
        self.pixel_format_combo.currentTextChanged.connect(self.on_pixel_format_changed)
        layout.addWidget(self.pixel_format_combo, row, 3)

        row += 1

        row += 1

        # --- Row 5: Flip Horizontal | Flip Vertical ---
        self.flip_h_checkbox = QCheckBox("Flip Horizontal (L↔R)")
        self.flip_h_checkbox.setChecked(self.state.camera_flip_horizontal)
        self.flip_h_checkbox.toggled.connect(self.on_flip_h_toggled)
        layout.addWidget(self.flip_h_checkbox, row, 0, 1, 2)

        self.flip_v_checkbox = QCheckBox("Flip Vertical (U↔D)")
        self.flip_v_checkbox.setChecked(self.state.camera_flip_vertical)
        self.flip_v_checkbox.toggled.connect(self.on_flip_v_toggled)
        layout.addWidget(self.flip_v_checkbox, row, 2, 1, 2)

        row += 1

        # --- Sum binning warning (hidden by default, spans all columns) ---
        self.sum_binning_warning = QLabel(
            "⚠ Sum mode: pixel values will exceed nominal bit-depth — "
            "camera outputs uint16 regardless of pixel format. "
            "Saturation warning calibrated accordingly."
        )
        self.sum_binning_warning.setStyleSheet("color: orange; font-size: 10px;")
        self.sum_binning_warning.setWordWrap(True)
        self.sum_binning_warning.setVisible(False)
        layout.addWidget(self.sum_binning_warning, row, 0, 1, 4)

        return panel

    def create_save_controls(self):
        """Create data saving panel."""
        panel = QGroupBox("Data Saving")
        layout = QGridLayout()
        panel.setLayout(layout)

        row = 0

        # Directory
        layout.addWidget(QLabel("Directory:"), row, 0)
        self.save_dir_input = QLineEdit(self.state.camera_save_dir)
        layout.addWidget(self.save_dir_input, row, 1, 1, 2)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.on_browse_dir)
        layout.addWidget(browse_button, row, 3)

        row += 1

        # Subfolder
        layout.addWidget(QLabel("Subfolder:"), row, 0)
        self.subfolder_input = QLineEdit(self.state.camera_save_subfolder)
        layout.addWidget(self.subfolder_input, row, 1, 1, 3)

        row += 1

        # Filename suffix
        layout.addWidget(QLabel("Filename Suffix:"), row, 0)
        self.suffix_input = QLineEdit(self.state.camera_save_filename_suffix)
        layout.addWidget(self.suffix_input, row, 1)

        self.timestamp_checkbox = QCheckBox("Append Timestamp")
        self.timestamp_checkbox.setChecked(self.state.camera_save_append_timestamp)
        layout.addWidget(self.timestamp_checkbox, row, 2, 1, 2)

        row += 1

        # File format
        layout.addWidget(QLabel("File Format:"), row, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(['.npy (NumPy)', '.tiff (16-bit)', '.jpg (8-bit)'])
        self.format_combo.setCurrentIndex(0)  # Default to .npy
        layout.addWidget(self.format_combo, row, 1, 1, 2)

        row += 1

        # Number of images
        layout.addWidget(QLabel("Num. of images to save:"), row, 0)
        self.save_num_spinbox = QSpinBox()
        self.save_num_spinbox.setRange(1, 10000)
        self.save_num_spinbox.setValue(self.state.camera_num_images_to_save)
        layout.addWidget(self.save_num_spinbox, row, 1)

        # Save button
        self.save_button = QPushButton("Begin Saving")
        self.save_button.clicked.connect(self.on_begin_saving)
        layout.addWidget(self.save_button, row, 2, 1, 2)

        return panel

    def connect_signals(self):
        """Connect state signals to UI update methods."""
        self.state.camera_connection_changed.connect(self.on_connection_changed)
        self.state.camera_streaming_changed.connect(self.on_streaming_changed)

    # === Control Methods ===

    @Slot()
    def on_connect_camera(self):
        """Connect to camera."""
        if self.worker is not None:
            # Disconnect
            self.on_disconnect_camera()
            return

        # Update state from UI
        self.state.camera_serial_number = self.serial_input.text()

        # Create queue
        self.frame_queue = queue.Queue(maxsize=30)

        # Start worker
        self.worker = CameraWorker(self.state, self.frame_queue)
        self.worker.connection_established.connect(self.on_connection_established)
        self.worker.connection_failed.connect(self.on_connection_failed)
        self.worker.frame_ready.connect(self.on_frame_ready)
        self.worker.parameter_set_success.connect(self.on_parameter_set)
        self.worker.saturation_detected.connect(self.on_saturation)
        self.worker.start()

        # Start consumer
        self.consumer = CameraConsumer(self.state, self.frame_queue)
        self.consumer.averaged_frame_ready.connect(self.on_averaged_frame_ready)
        self.consumer.save_progress.connect(self.on_save_progress)
        self.consumer.save_completed.connect(self.on_save_completed)
        self.consumer.error_occurred.connect(self.on_error)
        self.consumer.start()

        self.connect_button.setText("Connecting...")
        self.connect_button.setEnabled(False)

    @Slot()
    def on_disconnect_camera(self):
        """Disconnect from camera."""
        # Stop streaming first
        if self.state.camera_is_streaming:
            self.on_stop_streaming()

        # Stop threads
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None

        if self.consumer:
            self.consumer.stop()
            self.consumer.wait()
            self.consumer = None

        self.state.camera_is_connected = False

    @Slot()
    def on_start_streaming(self):
        """Start frame acquisition."""
        if not self.worker:
            return

        self.worker.start_grabbing()
        self.state.camera_is_streaming = True

    @Slot()
    def on_stop_streaming(self):
        """Stop frame acquisition."""
        if self.worker:
            self.worker.stop_grabbing()
        self.state.camera_is_streaming = False
        # Clear saturation warning when streaming stops
        self.saturation_label.setText("")
        self.saturation_label.setStyleSheet("")

    @Slot()
    def on_begin_saving(self):
        """Begin saving averaged images."""
        if not self.consumer or not self.state.camera_is_streaming:
            self.statusLabel.setText("Status: Cannot save - not streaming")
            return

        # Update state from UI
        self.state.camera_save_dir = self.save_dir_input.text()
        self.state.camera_save_subfolder = self.subfolder_input.text()
        self.state.camera_save_filename_suffix = self.suffix_input.text()
        self.state.camera_save_append_timestamp = self.timestamp_checkbox.isChecked()
        self.state.camera_num_images_to_save = self.save_num_spinbox.value()

        # Parse format from combo box
        format_text = self.format_combo.currentText()
        if 'npy' in format_text:
            self.state.camera_save_format = 'npy'
        elif 'tiff' in format_text:
            self.state.camera_save_format = 'tiff'
        elif 'jpg' in format_text:
            self.state.camera_save_format = 'jpg'

        # Start saving
        self.consumer.start_saving(self.state.camera_num_images_to_save)
        self.state.camera_is_saving = True
        self.save_button.setEnabled(False)

    # === Signal Handlers ===

    @Slot(dict)
    def on_connection_established(self, settings):
        """Handle successful camera connection."""
        self.state.camera_is_connected = True
        self.state.update_from_camera_settings(settings)

        # Button state is updated by on_connection_changed signal handler
        self.connect_button.setEnabled(True)

        msg = f"Connected: {settings['model_name']} SN {settings['serial_number']}"
        self.statusLabel.setText(f"Status: {msg}")

        # Update live status
        self.live_status_label.setText(f"Pixels: {settings['width']}x{settings['height']} | Stream: 0")

    @Slot(str)
    def on_connection_failed(self, error_msg):
        """Handle connection failure."""
        self.statusLabel.setText(f"Status: {error_msg}")
        self.connect_button.setText("Connect to Camera")
        self.connect_button.setEnabled(True)

    @Slot(np.ndarray, float, int)
    def on_frame_ready(self, frame, timestamp, count):
        """Handle new frame from worker."""
        # Apply orientation flips before display and storage
        frame = self._apply_flips(frame)

        # Store frame for mouse hover
        self.current_live_frame = frame

        # Calculate FPS using worker timestamp (always, even if display disabled)
        self.last_fps_value = self._calculate_fps(timestamp)

        # Throttle display updates (max 30 fps) and status updates
        import time
        now = time.time()
        should_update_display = (now - self.last_live_update >= 0.033)
        should_update_status = (now - self.last_status_update > 0.5)

        if should_update_display:
            self.last_live_update = now
            # Update display if enabled
            if self.state.camera_live_display_enabled:
                self.live_image_item.setImage(frame.T)

        # Update status (throttled to 0.5s)
        if should_update_status:
            self.live_status_label.setText(
                f"Pixels: {frame.shape[1]}x{frame.shape[0]} | "
                f"Stream: {count} | "
                f"FPS: {self.last_fps_value:.1f}"
            )
            self.last_status_update = now
            # Re-apply last known mouse position so coordinates stay visible
            # even when mouse is stationary (status label text was just replaced)
            if self._last_live_mouse_pos is not None:
                self._update_mouse_hover(self._last_live_mouse_pos,
                                         self.live_view_box, frame, True)

    @Slot(np.ndarray, int)
    def on_averaged_frame_ready(self, avg_frame, count):
        """Handle averaged frame from consumer."""
        # Apply orientation flips before display and storage
        avg_frame = self._apply_flips(avg_frame)

        # Store frame for mouse hover
        self.current_averaged_frame = avg_frame

        if self.state.camera_averaged_display_enabled or self.state.camera_is_saving:
            self.averaged_image_item.setImage(avg_frame.T)

        n_avg = self.state.camera_num_frames_to_average
        self.avg_status_label.setText(f"Averaged: {count}  (N={n_avg})")
        # Re-apply last known mouse position so coordinates stay visible
        # even when mouse is stationary (status label text was just replaced)
        if self._last_avg_mouse_pos is not None:
            self._update_mouse_hover(self._last_avg_mouse_pos,
                                     self.averaged_view_box, avg_frame, False)

    @Slot(bool, float)
    def on_saturation(self, is_saturated, max_val):
        """Handle saturation detection."""
        if is_saturated:
            self.saturation_label.setText(f"⚠ SATURATION: {max_val:.0f}")
            self.saturation_label.setStyleSheet("background-color: red; color: white; padding: 2px;")
        else:
            self.saturation_label.setText("")
            self.saturation_label.setStyleSheet("")

    @Slot(str, object)
    def on_parameter_set(self, param, value):
        """Handle parameter change confirmation."""
        pass  # Silent confirmation

    @Slot(int, int)
    def on_save_progress(self, current, total):
        """Handle save progress update."""
        self.save_button.setText(f"Saving... ({current}/{total})")

    @Slot(str)
    def on_save_completed(self, filepath):
        """Handle save completion."""
        self.save_button.setText("Begin Saving")
        self.save_button.setEnabled(True)
        self.state.camera_is_saving = False
        self.statusLabel.setText(f"Status: {filepath}")

    @Slot(str)
    def on_error(self, error_msg):
        """Handle error from threads."""
        self.statusLabel.setText(f"Status: ERROR - {error_msg}")

    @Slot(bool, str)
    def on_connection_changed(self, connected, sn):
        """React to connection state change."""
        if connected:
            self.connect_button.setText("Disconnect")
            self.start_button.setEnabled(True)
        else:
            self.connect_button.setText("Connect to Camera")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    @Slot(bool)
    def on_streaming_changed(self, streaming):
        """React to streaming state change."""
        self.start_button.setEnabled(not streaming and self.state.camera_is_connected)
        self.stop_button.setEnabled(streaming)

    # === UI Control Handlers ===

    @Slot(bool)
    def on_live_display_toggled(self, checked):
        """Handle live display toggle."""
        self.state.camera_live_display_enabled = checked

    @Slot(bool)
    def on_avg_display_toggled(self, checked):
        """Handle averaged display toggle."""
        self.state.camera_averaged_display_enabled = checked

    @Slot(int)
    def on_avg_frames_changed(self, value):
        """Handle frames to average change."""
        self.state.camera_num_frames_to_average = value

    @Slot(int)
    def on_exposure_slider_changed(self, slider_value):
        """Handle exposure slider movement.

        Converts slider position to exposure using semi-log mapping,
        then updates spinbox (which triggers camera update via on_exposure_changed).
        """
        exposure_us = self._slider_to_exposure(slider_value)

        # Block signals to avoid circular updates
        self.exposure_spinbox.blockSignals(True)
        self.exposure_spinbox.setValue(int(exposure_us))
        self.exposure_spinbox.blockSignals(False)

        # Manually trigger camera update
        self.on_exposure_changed(int(exposure_us))

    @Slot(int)
    def on_exposure_changed(self, value):
        """Handle exposure time change from spinbox or slider."""
        self.state.camera_exposure_us = float(value)

        # Sync slider position
        slider_pos = self._exposure_to_slider(value)
        self.exposure_slider.blockSignals(True)
        self.exposure_slider.setValue(slider_pos)
        self.exposure_slider.blockSignals(False)

        # Send command to camera
        if self.worker and self.state.camera_is_connected:
            self.worker.queue_command('set_exposure', value)

    @Slot()
    def on_binning_changed(self):
        """Handle binning change."""
        binning_x = int(self.binning_x_combo.currentText())
        binning_y = int(self.binning_y_combo.currentText())
        mode = self.binning_mode_combo.currentText()

        self.state.set_camera_binning(binning_x, binning_y)
        self.state.camera_binning_mode = mode

        if self.worker and self.state.camera_is_connected:
            self.worker.queue_command('set_binning', binning_x, binning_y, mode)

    @Slot(str)
    def on_binning_mode_changed(self, mode):
        """Handle binning mode change."""
        self.state.camera_binning_mode = mode
        if self.worker and self.state.camera_is_connected:
            binning_x = self.state.camera_binning_x
            binning_y = self.state.camera_binning_y
            self.worker.queue_command('set_binning', binning_x, binning_y, mode)

    @Slot(str)
    def _on_binning_mode_for_warning(self, mode):
        """Show/hide the sum-binning warning label."""
        self.sum_binning_warning.setVisible(mode == 'Sum')

    @Slot(str)
    def on_pixel_format_changed(self, pixel_format):
        """Handle pixel format change."""
        self.state.camera_pixel_format = pixel_format
        if self.worker and self.state.camera_is_connected:
            self.worker.queue_command('set_pixel_format', pixel_format)

    @Slot(bool)
    def on_flip_h_toggled(self, checked):
        """Handle horizontal flip toggle."""
        self.state.camera_flip_horizontal = checked

    @Slot(bool)
    def on_flip_v_toggled(self, checked):
        """Handle vertical flip toggle."""
        self.state.camera_flip_vertical = checked

    def _apply_flips(self, frame):
        """Return frame with active flip(s) applied.

        Flips are applied before display and saving so both paths
        see a consistently oriented image.

        Parameters
        ----------
        frame : np.ndarray
            2D image array (height, width)

        Returns
        -------
        np.ndarray
            Frame with flips applied (a view or copy)
        """
        if self.state.camera_flip_horizontal:
            frame = np.fliplr(frame)
        if self.state.camera_flip_vertical:
            frame = np.flipud(frame)
        return frame

    @Slot()
    def on_browse_dir(self):
        """Open directory browser."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Save Directory",
            self.save_dir_input.text()
        )
        if directory:
            self.save_dir_input.setText(directory)

    # === Configuration ===

    def save_config(self):
        """Save current configuration to file."""
        try:
            # Update state from UI
            self.state.camera_serial_number = self.serial_input.text()
            self.state.camera_save_dir = self.save_dir_input.text()
            self.state.camera_save_subfolder = self.subfolder_input.text()
            self.state.camera_save_filename_suffix = self.suffix_input.text()
            self.state.camera_save_append_timestamp = self.timestamp_checkbox.isChecked()

            # Parse format from combo box
            format_text = self.format_combo.currentText()
            if 'npy' in format_text:
                self.state.camera_save_format = 'npy'
            elif 'tiff' in format_text:
                self.state.camera_save_format = 'tiff'
            elif 'jpg' in format_text:
                self.state.camera_save_format = 'jpg'

            self.state.camera_num_images_to_save = self.save_num_spinbox.value()

            config = self.state.get_config()

            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            self.statusLabel.setText(f"Status: Configuration saved to {CONFIG_FILE}")

        except Exception as e:
            self.statusLabel.setText(f"Status: Error saving config - {str(e)}")

    def load_config(self):
        """Load configuration from file into state (call before init_ui)."""
        if not CONFIG_FILE.exists():
            return

        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            self.state.load_config(config)

        except Exception as e:
            print(f"Error loading config: {e}")

    def _apply_config_to_ui(self):
        """Sync UI widgets to match loaded state (call after init_ui)."""
        # Format combo box
        fmt_map = {'npy': 0, 'tiff': 1, 'jpg': 2}
        self.format_combo.setCurrentIndex(fmt_map.get(self.state.camera_save_format, 0))

        # Binning mode warning visibility
        self.sum_binning_warning.setVisible(self.state.camera_binning_mode == 'Sum')

        # Flip checkboxes
        self.flip_h_checkbox.setChecked(self.state.camera_flip_horizontal)
        self.flip_v_checkbox.setChecked(self.state.camera_flip_vertical)

    # === Helper Methods ===

    def _slider_to_exposure(self, slider_value):
        """Convert slider position to exposure time (microseconds).

        Piecewise mapping: 0→400 maps to 0→100000 µs
        - Linear 0-100: slider = exposure
        - Logarithmic 100-400: exposure = 10^((slider+100)/100)

        Key points: 0=0, 50=50, 100=100, 200=1000, 300=10000, 400=100000

        Parameters
        ----------
        slider_value : int
            Slider position (0-400)

        Returns
        -------
        float
            Exposure time in microseconds
        """
        if slider_value <= 100:
            # Linear range: 0-100 µs
            return float(slider_value)
        else:
            # Logarithmic range: 100-100000 µs
            # exposure = 10^((slider+100)/100)
            exposure = 10.0 ** ((slider_value + 100.0) / 100.0)
            return exposure

    def _exposure_to_slider(self, exposure_us):
        """Convert exposure time to slider position.

        Inverse of _slider_to_exposure().

        Parameters
        ----------
        exposure_us : float
            Exposure time in microseconds

        Returns
        -------
        int
            Slider position (0-400)
        """
        import numpy as np

        if exposure_us <= 0:
            return 0
        elif exposure_us <= 100:
            # Linear range
            return int(exposure_us)
        else:
            # Logarithmic range
            # exposure = 10^((slider+100)/100)
            # log10(exposure) = (slider+100)/100
            # slider = 100*log10(exposure) - 100
            slider_pos = 100.0 * np.log10(exposure_us) - 100.0
            return int(np.clip(slider_pos, 100, 400))

    def _calculate_fps(self, timestamp):
        """Calculate FPS from rolling window of timestamps.

        Parameters
        ----------
        timestamp : float
            Current frame timestamp (seconds since epoch)

        Returns
        -------
        float
            Calculated FPS, or 0.0 if insufficient data
        """
        # Add current timestamp to rolling window
        self.fps_timestamps.append(timestamp)

        # Maintain window size
        if len(self.fps_timestamps) > self.fps_window_size:
            self.fps_timestamps.pop(0)

        # Need at least 2 timestamps to calculate FPS
        if len(self.fps_timestamps) < 2:
            return 0.0

        # Calculate FPS: (num_intervals) / (time_elapsed)
        time_elapsed = self.fps_timestamps[-1] - self.fps_timestamps[0]
        if time_elapsed > 0:
            fps = (len(self.fps_timestamps) - 1) / time_elapsed
            return fps
        else:
            return 0.0

    def eventFilter(self, obj, event):
        """Capture mouse move/leave events for coordinate display."""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseMove:
            if obj == self.live_graphics_view.viewport():
                self._last_live_mouse_pos = event.pos()
                self._update_mouse_hover(event.pos(), self.live_view_box,
                                        self.current_live_frame, True)
            elif obj == self.averaged_graphics_view.viewport():
                self._last_avg_mouse_pos = event.pos()
                self._update_mouse_hover(event.pos(), self.averaged_view_box,
                                        self.current_averaged_frame, False)

        elif event.type() == QEvent.Leave:
            if obj == self.live_graphics_view.viewport():
                self._last_live_mouse_pos = None
                # Strip coordinate info from live status
                base_text = self.live_status_label.text()
                idx = base_text.find(' | X:')
                if idx != -1:
                    self.live_status_label.setText(base_text[:idx])
            elif obj == self.averaged_graphics_view.viewport():
                self._last_avg_mouse_pos = None
                base_text = self.avg_status_label.text()
                idx = base_text.find(' | X:')
                if idx != -1:
                    self.avg_status_label.setText(base_text[:idx])

        return super().eventFilter(obj, event)

    def _update_mouse_hover(self, widget_pos, view_box, frame, is_live):
        """Update status bar with mouse hover info.

        Parameters
        ----------
        widget_pos : QPoint
            Mouse position in widget coordinates
        view_box : pg.ViewBox
            ViewBox containing the image
        frame : np.ndarray or None
            Current frame data
        is_live : bool
            True for live panel, False for averaged panel
        """
        if frame is None:
            return

        # Convert widget coordinates to scene coordinates
        scene_pos = view_box.mapSceneToView(widget_pos)

        # Image coordinates (accounting for transpose)
        x = int(scene_pos.x())
        y = int(scene_pos.y())

        # Check bounds (frame is stored as (height, width))
        height, width = frame.shape
        if 0 <= x < width and 0 <= y < height:
            pixel_value = frame[y, x]

            if is_live:
                # Update live status with coordinate info
                # Preserve existing "Pixels: ... | Stream: ... | FPS: ..." and append hover info
                base_text = self.live_status_label.text()
                # Remove old hover info if present (find last occurrence of ' | X:')
                idx = base_text.find(' | X: ')
                if idx != -1:
                    base_text = base_text[:idx]
                new_text = f"{base_text} | X: {x} Y: {y} Val: {pixel_value:.0f}"
                self.live_status_label.setText(new_text)
            else:
                # Update averaged status with coordinate info
                base_text = self.avg_status_label.text()
                # Remove old hover info if present
                idx = base_text.find(' | X: ')
                if idx != -1:
                    base_text = base_text[:idx]
                new_text = f"{base_text} | X: {x} Y: {y} Val: {pixel_value:.0f}"
                self.avg_status_label.setText(new_text)
        else:
            # Mouse outside image bounds - clear coordinate info
            if is_live:
                base_text = self.live_status_label.text()
                idx = base_text.find(' | X: ')
                if idx != -1:
                    self.live_status_label.setText(base_text[:idx])
            else:
                base_text = self.avg_status_label.text()
                idx = base_text.find(' | X: ')
                if idx != -1:
                    self.avg_status_label.setText(base_text[:idx])

    def closeEvent(self, event):
        """Clean up when window is closed."""
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        if self.consumer:
            self.consumer.stop()
            self.consumer.wait()
        event.accept()


def main():
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = BaslerCameraApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
