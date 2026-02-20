# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_settings_tab.ui'
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
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QSpinBox, QVBoxLayout,
    QWidget)
class Ui_settings_tab_content(object):
    def setupUi(self, settings_tab_content):
        if not settings_tab_content.objectName():
            settings_tab_content.setObjectName(u"settings_tab_content")
        self.settings_outer_vbox = QVBoxLayout(settings_tab_content)
        self.settings_outer_vbox.setObjectName(u"settings_outer_vbox")
        self.settings_outer_vbox.setContentsMargins(8, 8, 8, 8)
        self.settings_instrument_group = QGroupBox(settings_tab_content)
        self.settings_instrument_group.setObjectName(u"settings_instrument_group")
        self.formLayout = QFormLayout(self.settings_instrument_group)
        self.formLayout.setObjectName(u"formLayout")
        self.label = QLabel(self.settings_instrument_group)
        self.label.setObjectName(u"label")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)

        self.settings_sg384_address_edit = QLineEdit(self.settings_instrument_group)
        self.settings_sg384_address_edit.setObjectName(u"settings_sg384_address_edit")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.settings_sg384_address_edit)

        self.label1 = QLabel(self.settings_instrument_group)
        self.label1.setObjectName(u"label1")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label1)

        self.settings_camera_serial_edit = QLineEdit(self.settings_instrument_group)
        self.settings_camera_serial_edit.setObjectName(u"settings_camera_serial_edit")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.settings_camera_serial_edit)

        self.label2 = QLabel(self.settings_instrument_group)
        self.label2.setObjectName(u"label2")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label2)

        self.settings_sg384_amplitude_spin = QDoubleSpinBox(self.settings_instrument_group)
        self.settings_sg384_amplitude_spin.setObjectName(u"settings_sg384_amplitude_spin")
        self.settings_sg384_amplitude_spin.setDecimals(1)
        self.settings_sg384_amplitude_spin.setMinimum(-110.000000000000000)
        self.settings_sg384_amplitude_spin.setMaximum(16.500000000000000)
        self.settings_sg384_amplitude_spin.setValue(-10.000000000000000)

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.settings_sg384_amplitude_spin)


        self.settings_outer_vbox.addWidget(self.settings_instrument_group)

        self.settings_perf_group = QGroupBox(settings_tab_content)
        self.settings_perf_group.setObjectName(u"settings_perf_group")
        self.formLayout1 = QFormLayout(self.settings_perf_group)
        self.formLayout1.setObjectName(u"formLayout1")
        self.label3 = QLabel(self.settings_perf_group)
        self.label3.setObjectName(u"label3")

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label3)

        self.perf_rf_poll_spin = QDoubleSpinBox(self.settings_perf_group)
        self.perf_rf_poll_spin.setObjectName(u"perf_rf_poll_spin")
        self.perf_rf_poll_spin.setDecimals(3)
        self.perf_rf_poll_spin.setMinimum(0.050000000000000)
        self.perf_rf_poll_spin.setMaximum(10.000000000000000)
        self.perf_rf_poll_spin.setValue(0.500000000000000)

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.FieldRole, self.perf_rf_poll_spin)

        self.label4 = QLabel(self.settings_perf_group)
        self.label4.setObjectName(u"label4")

        self.formLayout1.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label4)

        self.perf_settling_spin = QDoubleSpinBox(self.settings_perf_group)
        self.perf_settling_spin.setObjectName(u"perf_settling_spin")
        self.perf_settling_spin.setDecimals(4)
        self.perf_settling_spin.setMinimum(0.000000000000000)
        self.perf_settling_spin.setMaximum(1.000000000000000)
        self.perf_settling_spin.setValue(0.010000000000000)

        self.formLayout1.setWidget(1, QFormLayout.ItemRole.FieldRole, self.perf_settling_spin)

        self.label5 = QLabel(self.settings_perf_group)
        self.label5.setObjectName(u"label5")

        self.formLayout1.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label5)

        self.perf_flush_frames_spin = QSpinBox(self.settings_perf_group)
        self.perf_flush_frames_spin.setObjectName(u"perf_flush_frames_spin")
        self.perf_flush_frames_spin.setMinimum(0)
        self.perf_flush_frames_spin.setMaximum(20)
        self.perf_flush_frames_spin.setValue(1)

        self.formLayout1.setWidget(2, QFormLayout.ItemRole.FieldRole, self.perf_flush_frames_spin)

        self.label6 = QLabel(self.settings_perf_group)
        self.label6.setObjectName(u"label6")

        self.formLayout1.setWidget(3, QFormLayout.ItemRole.LabelRole, self.label6)

        self.perf_n_frames_spin = QSpinBox(self.settings_perf_group)
        self.perf_n_frames_spin.setObjectName(u"perf_n_frames_spin")
        self.perf_n_frames_spin.setMinimum(1)
        self.perf_n_frames_spin.setMaximum(100)
        self.perf_n_frames_spin.setValue(5)

        self.formLayout1.setWidget(3, QFormLayout.ItemRole.FieldRole, self.perf_n_frames_spin)

        self.label7 = QLabel(self.settings_perf_group)
        self.label7.setObjectName(u"label7")

        self.formLayout1.setWidget(4, QFormLayout.ItemRole.LabelRole, self.label7)

        self.perf_loop_sleep_spin = QDoubleSpinBox(self.settings_perf_group)
        self.perf_loop_sleep_spin.setObjectName(u"perf_loop_sleep_spin")
        self.perf_loop_sleep_spin.setDecimals(4)
        self.perf_loop_sleep_spin.setMinimum(0.001000000000000)
        self.perf_loop_sleep_spin.setMaximum(0.100000000000000)
        self.perf_loop_sleep_spin.setValue(0.005000000000000)

        self.formLayout1.setWidget(4, QFormLayout.ItemRole.FieldRole, self.perf_loop_sleep_spin)

        self.label8 = QLabel(self.settings_perf_group)
        self.label8.setObjectName(u"label8")

        self.formLayout1.setWidget(5, QFormLayout.ItemRole.LabelRole, self.label8)

        self.perf_emit_every_spin = QSpinBox(self.settings_perf_group)
        self.perf_emit_every_spin.setObjectName(u"perf_emit_every_spin")
        self.perf_emit_every_spin.setMinimum(1)
        self.perf_emit_every_spin.setMaximum(100)
        self.perf_emit_every_spin.setValue(1)

        self.formLayout1.setWidget(5, QFormLayout.ItemRole.FieldRole, self.perf_emit_every_spin)

        self.label9 = QLabel(self.settings_perf_group)
        self.label9.setObjectName(u"label9")

        self.formLayout1.setWidget(6, QFormLayout.ItemRole.LabelRole, self.label9)

        self.perf_live_avg_spin = QSpinBox(self.settings_perf_group)
        self.perf_live_avg_spin.setObjectName(u"perf_live_avg_spin")
        self.perf_live_avg_spin.setMinimum(1)
        self.perf_live_avg_spin.setMaximum(1000)
        self.perf_live_avg_spin.setValue(10)

        self.formLayout1.setWidget(6, QFormLayout.ItemRole.FieldRole, self.perf_live_avg_spin)

        self.label10 = QLabel(self.settings_perf_group)
        self.label10.setObjectName(u"label10")

        self.formLayout1.setWidget(7, QFormLayout.ItemRole.LabelRole, self.label10)

        self.perf_autosave_spin = QSpinBox(self.settings_perf_group)
        self.perf_autosave_spin.setObjectName(u"perf_autosave_spin")
        self.perf_autosave_spin.setMinimum(1)
        self.perf_autosave_spin.setMaximum(10000)
        self.perf_autosave_spin.setValue(50)

        self.formLayout1.setWidget(7, QFormLayout.ItemRole.FieldRole, self.perf_autosave_spin)


        self.settings_outer_vbox.addWidget(self.settings_perf_group)

        self.hboxLayout = QHBoxLayout()
        self.hboxLayout.setObjectName(u"hboxLayout")
        self.settings_reset_btn = QPushButton(settings_tab_content)
        self.settings_reset_btn.setObjectName(u"settings_reset_btn")

        self.hboxLayout.addWidget(self.settings_reset_btn)

        self.spacerItem = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hboxLayout.addItem(self.spacerItem)


        self.settings_outer_vbox.addLayout(self.hboxLayout)

        self.spacerItem1 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.settings_outer_vbox.addItem(self.spacerItem1)


        self.retranslateUi(settings_tab_content)

        QMetaObject.connectSlotsByName(settings_tab_content)
    # setupUi

    def retranslateUi(self, settings_tab_content):
        self.settings_instrument_group.setTitle(QCoreApplication.translate("settings_tab_content", u"Instrument Settings", None))
        self.label.setText(QCoreApplication.translate("settings_tab_content", u"SG384 IP address:", None))
        self.settings_sg384_address_edit.setText(QCoreApplication.translate("settings_tab_content", u"192.168.1.100", None))
        self.label1.setText(QCoreApplication.translate("settings_tab_content", u"ODMR camera serial:", None))
        self.label2.setText(QCoreApplication.translate("settings_tab_content", u"RF amplitude (dBm):", None))
        self.settings_perf_group.setTitle(QCoreApplication.translate("settings_tab_content", u"Performance / Timing", None))
        self.label3.setText(QCoreApplication.translate("settings_tab_content", u"RF poll interval (s):", None))
        self.label4.setText(QCoreApplication.translate("settings_tab_content", u"MW settling time (s):", None))
        self.label5.setText(QCoreApplication.translate("settings_tab_content", u"Camera flush frames:", None))
        self.label6.setText(QCoreApplication.translate("settings_tab_content", u"Frames per point:", None))
        self.label7.setText(QCoreApplication.translate("settings_tab_content", u"Worker loop sleep (s):", None))
        self.label8.setText(QCoreApplication.translate("settings_tab_content", u"Emit spectrum every N sweeps:", None))
        self.label9.setText(QCoreApplication.translate("settings_tab_content", u"Live avg update interval (samples):", None))
        self.label10.setText(QCoreApplication.translate("settings_tab_content", u"Autosave interval (samples):", None))
        self.settings_reset_btn.setText(QCoreApplication.translate("settings_tab_content", u"Reset Performance to Defaults", None))
        pass
    # retranslateUi

