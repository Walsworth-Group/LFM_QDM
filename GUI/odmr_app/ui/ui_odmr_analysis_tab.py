# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_analysis_tab.ui'
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
    QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout,
    QWidget)
class Ui_analysis_tab_content(object):
    def setupUi(self, analysis_tab_content):
        if not analysis_tab_content.objectName():
            analysis_tab_content.setObjectName(u"analysis_tab_content")
        self.analysis_outer_vbox = QVBoxLayout(analysis_tab_content)
        self.analysis_outer_vbox.setObjectName(u"analysis_outer_vbox")
        self.analysis_outer_vbox.setContentsMargins(4)
        self.analysis_display_placeholder = QWidget(analysis_tab_content)
        self.analysis_display_placeholder.setObjectName(u"analysis_display_placeholder")

        self.analysis_outer_vbox.addWidget(self.analysis_display_placeholder)

        self.analysis_controls_group = QGroupBox(analysis_tab_content)
        self.analysis_controls_group.setObjectName(u"analysis_controls_group")
        self.analysis_controls_group.setMaximumHeight(110)
        self.hboxLayout = QHBoxLayout(self.analysis_controls_group)
        self.hboxLayout.setObjectName(u"hboxLayout")
        self.formLayout = QFormLayout()
        self.formLayout.setObjectName(u"formLayout")
        self.label = QLabel(self.analysis_controls_group)
        self.label.setObjectName(u"label")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)

        self.analysis_denoise_combo = QComboBox(self.analysis_controls_group)
        self.analysis_denoise_combo.setObjectName(u"analysis_denoise_combo")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.analysis_denoise_combo)

        self.label1 = QLabel(self.analysis_controls_group)
        self.label1.setObjectName(u"label1")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label1)

        self.analysis_sigma_spin = QDoubleSpinBox(self.analysis_controls_group)
        self.analysis_sigma_spin.setObjectName(u"analysis_sigma_spin")
        self.analysis_sigma_spin.setMinimum(0.100000000000000)
        self.analysis_sigma_spin.setMaximum(100.000000000000000)
        self.analysis_sigma_spin.setValue(15.000000000000000)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.analysis_sigma_spin)

        self.label2 = QLabel(self.analysis_controls_group)
        self.label2.setObjectName(u"label2")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label2)

        self.analysis_outlier_spin = QDoubleSpinBox(self.analysis_controls_group)
        self.analysis_outlier_spin.setObjectName(u"analysis_outlier_spin")
        self.analysis_outlier_spin.setMinimum(1.000000000000000)
        self.analysis_outlier_spin.setMaximum(20.000000000000000)
        self.analysis_outlier_spin.setValue(4.000000000000000)

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.analysis_outlier_spin)


        self.hboxLayout.addLayout(self.formLayout)

        self.formLayout1 = QFormLayout()
        self.formLayout1.setObjectName(u"formLayout1")
        self.label3 = QLabel(self.analysis_controls_group)
        self.label3.setObjectName(u"label3")

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label3)

        self.analysis_reference_combo = QComboBox(self.analysis_controls_group)
        self.analysis_reference_combo.setObjectName(u"analysis_reference_combo")

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.FieldRole, self.analysis_reference_combo)


        self.hboxLayout.addLayout(self.formLayout1)

        self.analysis_reanalyze_btn = QPushButton(self.analysis_controls_group)
        self.analysis_reanalyze_btn.setObjectName(u"analysis_reanalyze_btn")

        self.hboxLayout.addWidget(self.analysis_reanalyze_btn)

        self.analysis_stats_label = QLabel(self.analysis_controls_group)
        self.analysis_stats_label.setObjectName(u"analysis_stats_label")

        self.hboxLayout.addWidget(self.analysis_stats_label)

        self.hboxLayout1 = QHBoxLayout()
        self.hboxLayout1.setObjectName(u"hboxLayout1")
        self.label4 = QLabel(self.analysis_controls_group)
        self.label4.setObjectName(u"label4")

        self.hboxLayout1.addWidget(self.label4)

        self.analysis_prefix_edit = QLineEdit(self.analysis_controls_group)
        self.analysis_prefix_edit.setObjectName(u"analysis_prefix_edit")

        self.hboxLayout1.addWidget(self.analysis_prefix_edit)

        self.analysis_save_npz_btn = QPushButton(self.analysis_controls_group)
        self.analysis_save_npz_btn.setObjectName(u"analysis_save_npz_btn")

        self.hboxLayout1.addWidget(self.analysis_save_npz_btn)

        self.analysis_save_png_btn = QPushButton(self.analysis_controls_group)
        self.analysis_save_png_btn.setObjectName(u"analysis_save_png_btn")

        self.hboxLayout1.addWidget(self.analysis_save_png_btn)


        self.hboxLayout.addLayout(self.hboxLayout1)

        self.spacerItem = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hboxLayout.addItem(self.spacerItem)


        self.analysis_outer_vbox.addWidget(self.analysis_controls_group)


        self.retranslateUi(analysis_tab_content)

        QMetaObject.connectSlotsByName(analysis_tab_content)
    # setupUi

    def retranslateUi(self, analysis_tab_content):
        self.analysis_controls_group.setTitle(QCoreApplication.translate("analysis_tab_content", u"Reanalysis Controls", None))
        self.label.setText(QCoreApplication.translate("analysis_tab_content", u"Denoise:", None))
        self.label1.setText(QCoreApplication.translate("analysis_tab_content", u"Gaussian sigma:", None))
        self.label2.setText(QCoreApplication.translate("analysis_tab_content", u"Outlier sigma:", None))
        self.label3.setText(QCoreApplication.translate("analysis_tab_content", u"Reference mode:", None))
        self.analysis_reanalyze_btn.setText(QCoreApplication.translate("analysis_tab_content", u"Reanalyze", None))
        self.analysis_stats_label.setText(QCoreApplication.translate("analysis_tab_content", u"\u2014", None))
        self.label4.setText(QCoreApplication.translate("analysis_tab_content", u"Prefix:", None))
        self.analysis_prefix_edit.setPlaceholderText(QCoreApplication.translate("analysis_tab_content", u"optional prefix", None))
        self.analysis_save_npz_btn.setText(QCoreApplication.translate("analysis_tab_content", u".npz", None))
        self.analysis_save_png_btn.setText(QCoreApplication.translate("analysis_tab_content", u".png", None))
        pass
    # retranslateUi

