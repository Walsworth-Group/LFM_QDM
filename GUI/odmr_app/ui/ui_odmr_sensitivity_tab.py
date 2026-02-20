# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_sensitivity_tab.ui'
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
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)
class Ui_sensitivity_tab_content(object):
    def setupUi(self, sensitivity_tab_content):
        if not sensitivity_tab_content.objectName():
            sensitivity_tab_content.setObjectName(u"sensitivity_tab_content")
        self.sensitivity_outer_vbox = QVBoxLayout(sensitivity_tab_content)
        self.sensitivity_outer_vbox.setObjectName(u"sensitivity_outer_vbox")
        self.sensitivity_outer_vbox.setContentsMargins(4)
        self.hboxLayout = QHBoxLayout()
        self.hboxLayout.setObjectName(u"hboxLayout")
        self.sensitivity_map_widget = QWidget(sensitivity_tab_content)
        self.sensitivity_map_widget.setObjectName(u"sensitivity_map_widget")

        self.hboxLayout.addWidget(self.sensitivity_map_widget)

        self.sensitivity_allan_widget = QWidget(sensitivity_tab_content)
        self.sensitivity_allan_widget.setObjectName(u"sensitivity_allan_widget")

        self.hboxLayout.addWidget(self.sensitivity_allan_widget)


        self.sensitivity_outer_vbox.addLayout(self.hboxLayout)

        self.sensitivity_controls_group = QGroupBox(sensitivity_tab_content)
        self.sensitivity_controls_group.setObjectName(u"sensitivity_controls_group")
        self.sensitivity_controls_group.setMaximumHeight(90)
        self.hboxLayout1 = QHBoxLayout(self.sensitivity_controls_group)
        self.hboxLayout1.setObjectName(u"hboxLayout1")
        self.formLayout = QFormLayout()
        self.formLayout.setObjectName(u"formLayout")
        self.label = QLabel(self.sensitivity_controls_group)
        self.label.setObjectName(u"label")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)

        self.sensitivity_time_override_spin = QDoubleSpinBox(self.sensitivity_controls_group)
        self.sensitivity_time_override_spin.setObjectName(u"sensitivity_time_override_spin")
        self.sensitivity_time_override_spin.setDecimals(4)
        self.sensitivity_time_override_spin.setMinimum(0.000000000000000)
        self.sensitivity_time_override_spin.setMaximum(100.000000000000000)
        self.sensitivity_time_override_spin.setValue(0.000000000000000)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.sensitivity_time_override_spin)

        self.label1 = QLabel(self.sensitivity_controls_group)
        self.label1.setObjectName(u"label1")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label1)

        self.sensitivity_slope_override_spin = QDoubleSpinBox(self.sensitivity_controls_group)
        self.sensitivity_slope_override_spin.setObjectName(u"sensitivity_slope_override_spin")
        self.sensitivity_slope_override_spin.setDecimals(2)
        self.sensitivity_slope_override_spin.setMinimum(0.000000000000000)
        self.sensitivity_slope_override_spin.setMaximum(1000.000000000000000)
        self.sensitivity_slope_override_spin.setValue(0.000000000000000)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.sensitivity_slope_override_spin)


        self.hboxLayout1.addLayout(self.formLayout)

        self.sensitivity_run_btn = QPushButton(self.sensitivity_controls_group)
        self.sensitivity_run_btn.setObjectName(u"sensitivity_run_btn")

        self.hboxLayout1.addWidget(self.sensitivity_run_btn)

        self.sensitivity_allan_btn = QPushButton(self.sensitivity_controls_group)
        self.sensitivity_allan_btn.setObjectName(u"sensitivity_allan_btn")

        self.hboxLayout1.addWidget(self.sensitivity_allan_btn)

        self.sensitivity_stats_label = QLabel(self.sensitivity_controls_group)
        self.sensitivity_stats_label.setObjectName(u"sensitivity_stats_label")

        self.hboxLayout1.addWidget(self.sensitivity_stats_label)

        self.hboxLayout2 = QHBoxLayout()
        self.hboxLayout2.setObjectName(u"hboxLayout2")
        self.label2 = QLabel(self.sensitivity_controls_group)
        self.label2.setObjectName(u"label2")

        self.hboxLayout2.addWidget(self.label2)

        self.sensitivity_prefix_edit = QLineEdit(self.sensitivity_controls_group)
        self.sensitivity_prefix_edit.setObjectName(u"sensitivity_prefix_edit")

        self.hboxLayout2.addWidget(self.sensitivity_prefix_edit)

        self.sensitivity_save_npz_btn = QPushButton(self.sensitivity_controls_group)
        self.sensitivity_save_npz_btn.setObjectName(u"sensitivity_save_npz_btn")

        self.hboxLayout2.addWidget(self.sensitivity_save_npz_btn)

        self.sensitivity_save_png_btn = QPushButton(self.sensitivity_controls_group)
        self.sensitivity_save_png_btn.setObjectName(u"sensitivity_save_png_btn")

        self.hboxLayout2.addWidget(self.sensitivity_save_png_btn)


        self.hboxLayout1.addLayout(self.hboxLayout2)

        self.spacerItem = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hboxLayout1.addItem(self.spacerItem)


        self.sensitivity_outer_vbox.addWidget(self.sensitivity_controls_group)


        self.retranslateUi(sensitivity_tab_content)

        QMetaObject.connectSlotsByName(sensitivity_tab_content)
    # setupUi

    def retranslateUi(self, sensitivity_tab_content):
        self.sensitivity_controls_group.setTitle(QCoreApplication.translate("sensitivity_tab_content", u"Controls", None))
        self.label.setText(QCoreApplication.translate("sensitivity_tab_content", u"Time/point override (s):", None))
        self.sensitivity_time_override_spin.setSpecialValueText(QCoreApplication.translate("sensitivity_tab_content", u"Auto", None))
        self.label1.setText(QCoreApplication.translate("sensitivity_tab_content", u"Slope override (GHz\u207b\u00b9):", None))
        self.sensitivity_slope_override_spin.setSpecialValueText(QCoreApplication.translate("sensitivity_tab_content", u"Auto", None))
        self.sensitivity_run_btn.setText(QCoreApplication.translate("sensitivity_tab_content", u"Compute Sensitivity", None))
        self.sensitivity_allan_btn.setText(QCoreApplication.translate("sensitivity_tab_content", u"Allan Deviation", None))
        self.sensitivity_stats_label.setText(QCoreApplication.translate("sensitivity_tab_content", u"\u2014", None))
        self.label2.setText(QCoreApplication.translate("sensitivity_tab_content", u"Prefix:", None))
        self.sensitivity_prefix_edit.setPlaceholderText(QCoreApplication.translate("sensitivity_tab_content", u"optional prefix", None))
        self.sensitivity_save_npz_btn.setText(QCoreApplication.translate("sensitivity_tab_content", u".npz", None))
        self.sensitivity_save_png_btn.setText(QCoreApplication.translate("sensitivity_tab_content", u".png", None))
        pass
    # retranslateUi

