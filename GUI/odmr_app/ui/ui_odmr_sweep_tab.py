# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_sweep_tab.ui'
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
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)
class Ui_sweep_tab_content(object):
    def setupUi(self, sweep_tab_content):
        if not sweep_tab_content.objectName():
            sweep_tab_content.setObjectName(u"sweep_tab_content")
        self.sweep_outer_hbox = QHBoxLayout(sweep_tab_content)
        self.sweep_outer_hbox.setSpacing(4)
        self.sweep_outer_hbox.setObjectName(u"sweep_outer_hbox")
        self.sweep_outer_hbox.setContentsMargins(4, 4, 4, 4)
        self.sweep_controls_panel = QWidget(sweep_tab_content)
        self.sweep_controls_panel.setObjectName(u"sweep_controls_panel")
        self.sweep_controls_panel.setMaximumWidth(320)
        self.sweep_controls_vbox = QVBoxLayout(self.sweep_controls_panel)
        self.sweep_controls_vbox.setObjectName(u"sweep_controls_vbox")
        self.sweep_controls_vbox.setContentsMargins(0, 0, 0, 0)
        self.sweep_trans1_group = QGroupBox(self.sweep_controls_panel)
        self.sweep_trans1_group.setObjectName(u"sweep_trans1_group")
        self.formLayout = QFormLayout(self.sweep_trans1_group)
        self.formLayout.setObjectName(u"formLayout")
        self.label = QLabel(self.sweep_trans1_group)
        self.label.setObjectName(u"label")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)

        self.sweep_freq1_start = QDoubleSpinBox(self.sweep_trans1_group)
        self.sweep_freq1_start.setObjectName(u"sweep_freq1_start")
        self.sweep_freq1_start.setDecimals(6)
        self.sweep_freq1_start.setMinimum(0.100000000000000)
        self.sweep_freq1_start.setMaximum(8.000000000000000)
        self.sweep_freq1_start.setValue(2.516000000000000)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.sweep_freq1_start)

        self.label1 = QLabel(self.sweep_trans1_group)
        self.label1.setObjectName(u"label1")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label1)

        self.sweep_freq1_end = QDoubleSpinBox(self.sweep_trans1_group)
        self.sweep_freq1_end.setObjectName(u"sweep_freq1_end")
        self.sweep_freq1_end.setDecimals(6)
        self.sweep_freq1_end.setMinimum(0.100000000000000)
        self.sweep_freq1_end.setMaximum(8.000000000000000)
        self.sweep_freq1_end.setValue(2.528000000000000)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.sweep_freq1_end)

        self.label2 = QLabel(self.sweep_trans1_group)
        self.label2.setObjectName(u"label2")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label2)

        self.sweep_freq1_steps = QSpinBox(self.sweep_trans1_group)
        self.sweep_freq1_steps.setObjectName(u"sweep_freq1_steps")
        self.sweep_freq1_steps.setMinimum(3)
        self.sweep_freq1_steps.setMaximum(2001)
        self.sweep_freq1_steps.setValue(201)

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.sweep_freq1_steps)


        self.sweep_controls_vbox.addWidget(self.sweep_trans1_group)

        self.sweep_trans2_group = QGroupBox(self.sweep_controls_panel)
        self.sweep_trans2_group.setObjectName(u"sweep_trans2_group")
        self.formLayout1 = QFormLayout(self.sweep_trans2_group)
        self.formLayout1.setObjectName(u"formLayout1")
        self.label3 = QLabel(self.sweep_trans2_group)
        self.label3.setObjectName(u"label3")

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label3)

        self.sweep_freq2_start = QDoubleSpinBox(self.sweep_trans2_group)
        self.sweep_freq2_start.setObjectName(u"sweep_freq2_start")
        self.sweep_freq2_start.setDecimals(6)
        self.sweep_freq2_start.setMinimum(0.100000000000000)
        self.sweep_freq2_start.setMaximum(8.000000000000000)
        self.sweep_freq2_start.setValue(3.210000000000000)

        self.formLayout1.setWidget(0, QFormLayout.ItemRole.FieldRole, self.sweep_freq2_start)

        self.label4 = QLabel(self.sweep_trans2_group)
        self.label4.setObjectName(u"label4")

        self.formLayout1.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label4)

        self.sweep_freq2_end = QDoubleSpinBox(self.sweep_trans2_group)
        self.sweep_freq2_end.setObjectName(u"sweep_freq2_end")
        self.sweep_freq2_end.setDecimals(6)
        self.sweep_freq2_end.setMinimum(0.100000000000000)
        self.sweep_freq2_end.setMaximum(8.000000000000000)
        self.sweep_freq2_end.setValue(3.222000000000000)

        self.formLayout1.setWidget(1, QFormLayout.ItemRole.FieldRole, self.sweep_freq2_end)

        self.label5 = QLabel(self.sweep_trans2_group)
        self.label5.setObjectName(u"label5")

        self.formLayout1.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label5)

        self.sweep_freq2_steps = QSpinBox(self.sweep_trans2_group)
        self.sweep_freq2_steps.setObjectName(u"sweep_freq2_steps")
        self.sweep_freq2_steps.setMinimum(3)
        self.sweep_freq2_steps.setMaximum(2001)
        self.sweep_freq2_steps.setValue(201)

        self.formLayout1.setWidget(2, QFormLayout.ItemRole.FieldRole, self.sweep_freq2_steps)


        self.sweep_controls_vbox.addWidget(self.sweep_trans2_group)

        self.sweep_params_group = QGroupBox(self.sweep_controls_panel)
        self.sweep_params_group.setObjectName(u"sweep_params_group")
        self.formLayout2 = QFormLayout(self.sweep_params_group)
        self.formLayout2.setObjectName(u"formLayout2")
        self.label6 = QLabel(self.sweep_params_group)
        self.label6.setObjectName(u"label6")

        self.formLayout2.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label6)

        self.sweep_ref_freq = QDoubleSpinBox(self.sweep_params_group)
        self.sweep_ref_freq.setObjectName(u"sweep_ref_freq")
        self.sweep_ref_freq.setDecimals(3)
        self.sweep_ref_freq.setMinimum(0.100000000000000)
        self.sweep_ref_freq.setMaximum(8.000000000000000)
        self.sweep_ref_freq.setValue(1.000000000000000)

        self.formLayout2.setWidget(0, QFormLayout.ItemRole.FieldRole, self.sweep_ref_freq)

        self.label7 = QLabel(self.sweep_params_group)
        self.label7.setObjectName(u"label7")

        self.formLayout2.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label7)

        self.sweep_num_sweeps = QSpinBox(self.sweep_params_group)
        self.sweep_num_sweeps.setObjectName(u"sweep_num_sweeps")
        self.sweep_num_sweeps.setMinimum(1)
        self.sweep_num_sweeps.setMaximum(1000)
        self.sweep_num_sweeps.setValue(5)

        self.formLayout2.setWidget(1, QFormLayout.ItemRole.FieldRole, self.sweep_num_sweeps)

        self.label8 = QLabel(self.sweep_params_group)
        self.label8.setObjectName(u"label8")

        self.formLayout2.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label8)

        self.sweep_n_lorentz = QSpinBox(self.sweep_params_group)
        self.sweep_n_lorentz.setObjectName(u"sweep_n_lorentz")
        self.sweep_n_lorentz.setMinimum(1)
        self.sweep_n_lorentz.setMaximum(4)
        self.sweep_n_lorentz.setValue(2)

        self.formLayout2.setWidget(2, QFormLayout.ItemRole.FieldRole, self.sweep_n_lorentz)


        self.sweep_controls_vbox.addWidget(self.sweep_params_group)

        self.sweep_run_group = QGroupBox(self.sweep_controls_panel)
        self.sweep_run_group.setObjectName(u"sweep_run_group")
        self.vboxLayout = QVBoxLayout(self.sweep_run_group)
        self.vboxLayout.setObjectName(u"vboxLayout")
        self.hboxLayout = QHBoxLayout()
        self.hboxLayout.setObjectName(u"hboxLayout")
        self.sweep_start_btn = QPushButton(self.sweep_run_group)
        self.sweep_start_btn.setObjectName(u"sweep_start_btn")

        self.hboxLayout.addWidget(self.sweep_start_btn)

        self.sweep_stop_btn = QPushButton(self.sweep_run_group)
        self.sweep_stop_btn.setObjectName(u"sweep_stop_btn")
        self.sweep_stop_btn.setEnabled(False)

        self.hboxLayout.addWidget(self.sweep_stop_btn)


        self.vboxLayout.addLayout(self.hboxLayout)

        self.sweep_progress_bar = QProgressBar(self.sweep_run_group)
        self.sweep_progress_bar.setObjectName(u"sweep_progress_bar")
        self.sweep_progress_bar.setValue(0)

        self.vboxLayout.addWidget(self.sweep_progress_bar)

        self.sweep_time_label = QLabel(self.sweep_run_group)
        self.sweep_time_label.setObjectName(u"sweep_time_label")

        self.vboxLayout.addWidget(self.sweep_time_label)

        self.sweep_send_to_mag_btn = QPushButton(self.sweep_run_group)
        self.sweep_send_to_mag_btn.setObjectName(u"sweep_send_to_mag_btn")
        self.sweep_send_to_mag_btn.setEnabled(False)

        self.vboxLayout.addWidget(self.sweep_send_to_mag_btn)


        self.sweep_controls_vbox.addWidget(self.sweep_run_group)

        self.sweep_save_group = QGroupBox(self.sweep_controls_panel)
        self.sweep_save_group.setObjectName(u"sweep_save_group")
        self.hboxLayout1 = QHBoxLayout(self.sweep_save_group)
        self.hboxLayout1.setObjectName(u"hboxLayout1")
        self.label9 = QLabel(self.sweep_save_group)
        self.label9.setObjectName(u"label9")

        self.hboxLayout1.addWidget(self.label9)

        self.sweep_prefix_edit = QLineEdit(self.sweep_save_group)
        self.sweep_prefix_edit.setObjectName(u"sweep_prefix_edit")

        self.hboxLayout1.addWidget(self.sweep_prefix_edit)

        self.sweep_save_npz_btn = QPushButton(self.sweep_save_group)
        self.sweep_save_npz_btn.setObjectName(u"sweep_save_npz_btn")

        self.hboxLayout1.addWidget(self.sweep_save_npz_btn)

        self.sweep_save_png_btn = QPushButton(self.sweep_save_group)
        self.sweep_save_png_btn.setObjectName(u"sweep_save_png_btn")

        self.hboxLayout1.addWidget(self.sweep_save_png_btn)


        self.sweep_controls_vbox.addWidget(self.sweep_save_group)

        self.spacerItem = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.sweep_controls_vbox.addItem(self.spacerItem)


        self.sweep_outer_hbox.addWidget(self.sweep_controls_panel)

        self.sweep_right_panel = QWidget(sweep_tab_content)
        self.sweep_right_panel.setObjectName(u"sweep_right_panel")
        self.sweep_right_vbox = QVBoxLayout(self.sweep_right_panel)
        self.sweep_right_vbox.setObjectName(u"sweep_right_vbox")
        self.sweep_right_vbox.setContentsMargins(0, 0, 0, 0)
        self.sweep_plot_widget = QWidget(self.sweep_right_panel)
        self.sweep_plot_widget.setObjectName(u"sweep_plot_widget")

        self.sweep_right_vbox.addWidget(self.sweep_plot_widget)

        self.sweep_inflection_table = QTableWidget(self.sweep_right_panel)
        self.sweep_inflection_table.setObjectName(u"sweep_inflection_table")
        self.sweep_inflection_table.setMaximumHeight(220)

        self.sweep_right_vbox.addWidget(self.sweep_inflection_table)


        self.sweep_outer_hbox.addWidget(self.sweep_right_panel)


        self.retranslateUi(sweep_tab_content)

        QMetaObject.connectSlotsByName(sweep_tab_content)
    # setupUi

    def retranslateUi(self, sweep_tab_content):
        self.sweep_trans1_group.setTitle(QCoreApplication.translate("sweep_tab_content", u"Transition 1 (lower, m=0 to -1)", None))
        self.label.setText(QCoreApplication.translate("sweep_tab_content", u"Start (GHz):", None))
        self.label1.setText(QCoreApplication.translate("sweep_tab_content", u"End (GHz):", None))
        self.label2.setText(QCoreApplication.translate("sweep_tab_content", u"Steps:", None))
        self.sweep_trans2_group.setTitle(QCoreApplication.translate("sweep_tab_content", u"Transition 2 (upper, m=0 to +1)", None))
        self.label3.setText(QCoreApplication.translate("sweep_tab_content", u"Start (GHz):", None))
        self.label4.setText(QCoreApplication.translate("sweep_tab_content", u"End (GHz):", None))
        self.label5.setText(QCoreApplication.translate("sweep_tab_content", u"Steps:", None))
        self.sweep_params_group.setTitle(QCoreApplication.translate("sweep_tab_content", u"Sweep Parameters", None))
        self.label6.setText(QCoreApplication.translate("sweep_tab_content", u"Ref freq (GHz):", None))
        self.label7.setText(QCoreApplication.translate("sweep_tab_content", u"Num sweeps:", None))
        self.label8.setText(QCoreApplication.translate("sweep_tab_content", u"N Lorentzians:", None))
        self.sweep_run_group.setTitle(QCoreApplication.translate("sweep_tab_content", u"Run", None))
        self.sweep_start_btn.setText(QCoreApplication.translate("sweep_tab_content", u"Start Sweep", None))
        self.sweep_stop_btn.setText(QCoreApplication.translate("sweep_tab_content", u"Stop", None))
        self.sweep_time_label.setText(QCoreApplication.translate("sweep_tab_content", u"\u2014", None))
        self.sweep_send_to_mag_btn.setText(QCoreApplication.translate("sweep_tab_content", u"Send to Magnetometry", None))
        self.sweep_save_group.setTitle(QCoreApplication.translate("sweep_tab_content", u"Save", None))
        self.label9.setText(QCoreApplication.translate("sweep_tab_content", u"Prefix:", None))
        self.sweep_prefix_edit.setPlaceholderText(QCoreApplication.translate("sweep_tab_content", u"optional prefix", None))
        self.sweep_save_npz_btn.setText(QCoreApplication.translate("sweep_tab_content", u".npz", None))
        self.sweep_save_png_btn.setText(QCoreApplication.translate("sweep_tab_content", u".png", None))
        pass
    # retranslateUi

