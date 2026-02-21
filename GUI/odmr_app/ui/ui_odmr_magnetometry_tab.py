# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_magnetometry_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
    QSpinBox, QVBoxLayout, QWidget)
class Ui_magnetometry_tab_content(object):
    def setupUi(self, magnetometry_tab_content):
        if not magnetometry_tab_content.objectName():
            magnetometry_tab_content.setObjectName(u"magnetometry_tab_content")
        self.mag_outer_hbox = QHBoxLayout(magnetometry_tab_content)
        self.mag_outer_hbox.setObjectName(u"mag_outer_hbox")
        self.mag_outer_hbox.setContentsMargins(4, 4, 4, 4)
        self.mag_controls_panel = QWidget(magnetometry_tab_content)
        self.mag_controls_panel.setObjectName(u"mag_controls_panel")
        self.mag_controls_panel.setMaximumWidth(380)
        self.mag_controls_vbox = QVBoxLayout(self.mag_controls_panel)
        self.mag_controls_vbox.setObjectName(u"mag_controls_vbox")
        self.mag_controls_vbox.setContentsMargins(0, 0, 0, 0)
        self.mag_preset_group = QGroupBox(self.mag_controls_panel)
        self.mag_preset_group.setObjectName(u"mag_preset_group")
        self.hboxLayout = QHBoxLayout(self.mag_preset_group)
        self.hboxLayout.setObjectName(u"hboxLayout")
        self.mag_preset_combo = QComboBox(self.mag_preset_group)
        self.mag_preset_combo.setObjectName(u"mag_preset_combo")

        self.hboxLayout.addWidget(self.mag_preset_combo)

        self.mag_preset_load_btn = QPushButton(self.mag_preset_group)
        self.mag_preset_load_btn.setObjectName(u"mag_preset_load_btn")

        self.hboxLayout.addWidget(self.mag_preset_load_btn)

        self.mag_preset_save_btn = QPushButton(self.mag_preset_group)
        self.mag_preset_save_btn.setObjectName(u"mag_preset_save_btn")

        self.hboxLayout.addWidget(self.mag_preset_save_btn)

        self.mag_preset_delete_btn = QPushButton(self.mag_preset_group)
        self.mag_preset_delete_btn.setObjectName(u"mag_preset_delete_btn")

        self.hboxLayout.addWidget(self.mag_preset_delete_btn)


        self.mag_controls_vbox.addWidget(self.mag_preset_group)

        self.mag_points_group = QGroupBox(self.mag_controls_panel)
        self.mag_points_group.setObjectName(u"mag_points_group")
        self.vboxLayout = QVBoxLayout(self.mag_points_group)
        self.vboxLayout.setObjectName(u"vboxLayout")
        self.hboxLayout1 = QHBoxLayout()
        self.hboxLayout1.setObjectName(u"hboxLayout1")
        self.mag_points_load_btn = QPushButton(self.mag_points_group)
        self.mag_points_load_btn.setObjectName(u"mag_points_load_btn")

        self.hboxLayout1.addWidget(self.mag_points_load_btn)

        self.mag_points_save_btn = QPushButton(self.mag_points_group)
        self.mag_points_save_btn.setObjectName(u"mag_points_save_btn")

        self.hboxLayout1.addWidget(self.mag_points_save_btn)


        self.vboxLayout.addLayout(self.hboxLayout1)

        self.mag_inflection_table_placeholder = QWidget(self.mag_points_group)
        self.mag_inflection_table_placeholder.setObjectName(u"mag_inflection_table_placeholder")

        self.vboxLayout.addWidget(self.mag_inflection_table_placeholder)


        self.mag_controls_vbox.addWidget(self.mag_points_group)

        self.mag_params_group = QGroupBox(self.mag_controls_panel)
        self.mag_params_group.setObjectName(u"mag_params_group")
        self.formLayout = QFormLayout(self.mag_params_group)
        self.formLayout.setObjectName(u"formLayout")
        self.label = QLabel(self.mag_params_group)
        self.label.setObjectName(u"label")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)

        self.mag_ref_freq_spin = QDoubleSpinBox(self.mag_params_group)
        self.mag_ref_freq_spin.setObjectName(u"mag_ref_freq_spin")
        self.mag_ref_freq_spin.setDecimals(3)
        self.mag_ref_freq_spin.setMinimum(0.100000000000000)
        self.mag_ref_freq_spin.setMaximum(8.000000000000000)
        self.mag_ref_freq_spin.setValue(1.000000000000000)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.mag_ref_freq_spin)

        self.label1 = QLabel(self.mag_params_group)
        self.label1.setObjectName(u"label1")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label1)

        self.hboxLayout2 = QHBoxLayout()
        self.hboxLayout2.setObjectName(u"hboxLayout2")
        self.mag_bin_x_spin = QSpinBox(self.mag_params_group)
        self.mag_bin_x_spin.setObjectName(u"mag_bin_x_spin")
        self.mag_bin_x_spin.setMinimum(1)
        self.mag_bin_x_spin.setMaximum(32)
        self.mag_bin_x_spin.setValue(1)

        self.hboxLayout2.addWidget(self.mag_bin_x_spin)

        self.label2 = QLabel(self.mag_params_group)
        self.label2.setObjectName(u"label2")

        self.hboxLayout2.addWidget(self.label2)

        self.mag_bin_y_spin = QSpinBox(self.mag_params_group)
        self.mag_bin_y_spin.setObjectName(u"mag_bin_y_spin")
        self.mag_bin_y_spin.setMinimum(1)
        self.mag_bin_y_spin.setMaximum(32)
        self.mag_bin_y_spin.setValue(1)

        self.hboxLayout2.addWidget(self.mag_bin_y_spin)


        self.formLayout.setLayout(1, QFormLayout.ItemRole.FieldRole, self.hboxLayout2)

        self.label3 = QLabel(self.mag_params_group)
        self.label3.setObjectName(u"label3")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label3)

        self.mag_num_samples_spin = QSpinBox(self.mag_params_group)
        self.mag_num_samples_spin.setObjectName(u"mag_num_samples_spin")
        self.mag_num_samples_spin.setMinimum(1)
        self.mag_num_samples_spin.setMaximum(100000)
        self.mag_num_samples_spin.setValue(200)

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.mag_num_samples_spin)

        self.label4 = QLabel(self.mag_params_group)
        self.label4.setObjectName(u"label4")

        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.label4)

        self.mag_live_interval_spin = QSpinBox(self.mag_params_group)
        self.mag_live_interval_spin.setObjectName(u"mag_live_interval_spin")
        self.mag_live_interval_spin.setMinimum(1)
        self.mag_live_interval_spin.setMaximum(1000)
        self.mag_live_interval_spin.setValue(10)

        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.mag_live_interval_spin)


        self.mag_controls_vbox.addWidget(self.mag_params_group)

        self.mag_run_group = QGroupBox(self.mag_controls_panel)
        self.mag_run_group.setObjectName(u"mag_run_group")
        self.vboxLayout1 = QVBoxLayout(self.mag_run_group)
        self.vboxLayout1.setObjectName(u"vboxLayout1")
        self.hboxLayout3 = QHBoxLayout()
        self.hboxLayout3.setObjectName(u"hboxLayout3")
        self.mag_start_btn = QPushButton(self.mag_run_group)
        self.mag_start_btn.setObjectName(u"mag_start_btn")

        self.hboxLayout3.addWidget(self.mag_start_btn)

        self.mag_stop_btn = QPushButton(self.mag_run_group)
        self.mag_stop_btn.setObjectName(u"mag_stop_btn")
        self.mag_stop_btn.setEnabled(False)

        self.hboxLayout3.addWidget(self.mag_stop_btn)


        self.vboxLayout1.addLayout(self.hboxLayout3)

        self.mag_progress_bar = QProgressBar(self.mag_run_group)
        self.mag_progress_bar.setObjectName(u"mag_progress_bar")
        self.mag_progress_bar.setValue(0)

        self.vboxLayout1.addWidget(self.mag_progress_bar)

        self.mag_time_label = QLabel(self.mag_run_group)
        self.mag_time_label.setObjectName(u"mag_time_label")

        self.vboxLayout1.addWidget(self.mag_time_label)


        self.mag_controls_vbox.addWidget(self.mag_run_group)

        self.mag_save_group = QGroupBox(self.mag_controls_panel)
        self.mag_save_group.setObjectName(u"mag_save_group")
        self.hboxLayout4 = QHBoxLayout(self.mag_save_group)
        self.hboxLayout4.setObjectName(u"hboxLayout4")
        self.label5 = QLabel(self.mag_save_group)
        self.label5.setObjectName(u"label5")

        self.hboxLayout4.addWidget(self.label5)

        self.mag_prefix_edit = QLineEdit(self.mag_save_group)
        self.mag_prefix_edit.setObjectName(u"mag_prefix_edit")

        self.hboxLayout4.addWidget(self.mag_prefix_edit)

        self.mag_save_npz_btn = QPushButton(self.mag_save_group)
        self.mag_save_npz_btn.setObjectName(u"mag_save_npz_btn")

        self.hboxLayout4.addWidget(self.mag_save_npz_btn)

        self.mag_save_png_btn = QPushButton(self.mag_save_group)
        self.mag_save_png_btn.setObjectName(u"mag_save_png_btn")

        self.hboxLayout4.addWidget(self.mag_save_png_btn)


        self.mag_controls_vbox.addWidget(self.mag_save_group)

        self.spacerItem = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.mag_controls_vbox.addItem(self.spacerItem)


        self.mag_outer_hbox.addWidget(self.mag_controls_panel)

        self.mag_preview_widget = QWidget(magnetometry_tab_content)
        self.mag_preview_widget.setObjectName(u"mag_preview_widget")

        self.mag_outer_hbox.addWidget(self.mag_preview_widget)


        self.retranslateUi(magnetometry_tab_content)

        QMetaObject.connectSlotsByName(magnetometry_tab_content)
    # setupUi

    def retranslateUi(self, magnetometry_tab_content):
        self.mag_preset_group.setTitle(QCoreApplication.translate("magnetometry_tab_content", u"Preset", None))
        self.mag_preset_load_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Load", None))
        self.mag_preset_save_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Save", None))
        self.mag_preset_delete_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Delete", None))
        self.mag_points_group.setTitle(QCoreApplication.translate("magnetometry_tab_content", u"Inflection Points", None))
        self.mag_points_load_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Load Points from File", None))
        self.mag_points_save_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Save Points to File", None))
        self.mag_params_group.setTitle(QCoreApplication.translate("magnetometry_tab_content", u"Measurement Parameters", None))
        self.label.setText(QCoreApplication.translate("magnetometry_tab_content", u"Ref freq (GHz):", None))
        self.label1.setText(QCoreApplication.translate("magnetometry_tab_content", u"Sw Bin (X / Y):", None))
        self.label2.setText(QCoreApplication.translate("magnetometry_tab_content", u"/", None))
        self.label3.setText(QCoreApplication.translate("magnetometry_tab_content", u"Num samples:", None))
        self.label4.setText(QCoreApplication.translate("magnetometry_tab_content", u"Live update every:", None))
        self.mag_run_group.setTitle(QCoreApplication.translate("magnetometry_tab_content", u"Run", None))
        self.mag_start_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Start", None))
        self.mag_stop_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u"Stop", None))
        self.mag_time_label.setText(QCoreApplication.translate("magnetometry_tab_content", u"\u2014", None))
        self.mag_save_group.setTitle(QCoreApplication.translate("magnetometry_tab_content", u"Save", None))
        self.label5.setText(QCoreApplication.translate("magnetometry_tab_content", u"Prefix:", None))
        self.mag_prefix_edit.setPlaceholderText(QCoreApplication.translate("magnetometry_tab_content", u"optional prefix", None))
        self.mag_save_npz_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u".npz", None))
        self.mag_save_png_btn.setText(QCoreApplication.translate("magnetometry_tab_content", u".png", None))
        pass
    # retranslateUi

