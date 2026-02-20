# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'odmr_app_main.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMenuBar, QPushButton, QSizePolicy,
    QSpacerItem, QStatusBar, QTabWidget, QVBoxLayout,
    QWidget)
class Ui_ODMRMainWindow(object):
    def setupUi(self, ODMRMainWindow):
        if not ODMRMainWindow.objectName():
            ODMRMainWindow.setObjectName(u"ODMRMainWindow")
        ODMRMainWindow.resize(1600, 1000)
        self.action_save_config = QAction(ODMRMainWindow)
        self.action_save_config.setObjectName(u"action_save_config")
        self.action_save_config_as = QAction(ODMRMainWindow)
        self.action_save_config_as.setObjectName(u"action_save_config_as")
        self.action_load_config = QAction(ODMRMainWindow)
        self.action_load_config.setObjectName(u"action_load_config")
        self.action_reset_defaults = QAction(ODMRMainWindow)
        self.action_reset_defaults.setObjectName(u"action_reset_defaults")
        self.centralwidget = QWidget(ODMRMainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.main_vbox = QVBoxLayout(self.centralwidget)
        self.main_vbox.setSpacing(4)
        self.main_vbox.setObjectName(u"main_vbox")
        self.main_vbox.setContentsMargins(4, 4, 4, 4)
        self.rf_group = QGroupBox(self.centralwidget)
        self.rf_group.setObjectName(u"rf_group")
        self.rf_group.setMaximumHeight(80)
        self.rf_hbox = QHBoxLayout(self.rf_group)
        self.rf_hbox.setObjectName(u"rf_hbox")
        self.rf_status_label = QLabel(self.rf_group)
        self.rf_status_label.setObjectName(u"rf_status_label")

        self.rf_hbox.addWidget(self.rf_status_label)

        self.rf_freq_label = QLabel(self.rf_group)
        self.rf_freq_label.setObjectName(u"rf_freq_label")

        self.rf_hbox.addWidget(self.rf_freq_label)

        self.rf_freq_spinbox = QDoubleSpinBox(self.rf_group)
        self.rf_freq_spinbox.setObjectName(u"rf_freq_spinbox")
        self.rf_freq_spinbox.setDecimals(6)
        self.rf_freq_spinbox.setMinimum(0.000000000000000)
        self.rf_freq_spinbox.setMaximum(8.000000000000000)
        self.rf_freq_spinbox.setValue(2.870000000000000)

        self.rf_hbox.addWidget(self.rf_freq_spinbox)

        self.rf_set_btn = QPushButton(self.rf_group)
        self.rf_set_btn.setObjectName(u"rf_set_btn")

        self.rf_hbox.addWidget(self.rf_set_btn)

        self.rf_amp_label = QLabel(self.rf_group)
        self.rf_amp_label.setObjectName(u"rf_amp_label")

        self.rf_hbox.addWidget(self.rf_amp_label)

        self.rf_connect_btn = QPushButton(self.rf_group)
        self.rf_connect_btn.setObjectName(u"rf_connect_btn")

        self.rf_hbox.addWidget(self.rf_connect_btn)

        self.rf_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.rf_hbox.addItem(self.rf_spacer)


        self.main_vbox.addWidget(self.rf_group)

        self.tab_widget = QTabWidget(self.centralwidget)
        self.tab_widget.setObjectName(u"tab_widget")
        self.camera_tab = QWidget()
        self.camera_tab.setObjectName(u"camera_tab")
        self.tab_widget.addTab(self.camera_tab, "")
        self.sweep_tab = QWidget()
        self.sweep_tab.setObjectName(u"sweep_tab")
        self.tab_widget.addTab(self.sweep_tab, "")
        self.magnetometry_tab = QWidget()
        self.magnetometry_tab.setObjectName(u"magnetometry_tab")
        self.tab_widget.addTab(self.magnetometry_tab, "")
        self.analysis_tab = QWidget()
        self.analysis_tab.setObjectName(u"analysis_tab")
        self.tab_widget.addTab(self.analysis_tab, "")
        self.sensitivity_tab = QWidget()
        self.sensitivity_tab.setObjectName(u"sensitivity_tab")
        self.tab_widget.addTab(self.sensitivity_tab, "")
        self.settings_tab = QWidget()
        self.settings_tab.setObjectName(u"settings_tab")
        self.tab_widget.addTab(self.settings_tab, "")

        self.main_vbox.addWidget(self.tab_widget)

        self.save_bar_group = QGroupBox(self.centralwidget)
        self.save_bar_group.setObjectName(u"save_bar_group")
        self.save_bar_group.setMaximumHeight(70)
        self.save_hbox = QHBoxLayout(self.save_bar_group)
        self.save_hbox.setObjectName(u"save_hbox")
        self.label = QLabel(self.save_bar_group)
        self.label.setObjectName(u"label")

        self.save_hbox.addWidget(self.label)

        self.save_base_path_edit = QLineEdit(self.save_bar_group)
        self.save_base_path_edit.setObjectName(u"save_base_path_edit")

        self.save_hbox.addWidget(self.save_base_path_edit)

        self.save_browse_btn = QPushButton(self.save_bar_group)
        self.save_browse_btn.setObjectName(u"save_browse_btn")

        self.save_hbox.addWidget(self.save_browse_btn)

        self.label1 = QLabel(self.save_bar_group)
        self.label1.setObjectName(u"label1")

        self.save_hbox.addWidget(self.label1)

        self.save_subfolder_edit = QLineEdit(self.save_bar_group)
        self.save_subfolder_edit.setObjectName(u"save_subfolder_edit")

        self.save_hbox.addWidget(self.save_subfolder_edit)

        self.save_timestamp_chk = QCheckBox(self.save_bar_group)
        self.save_timestamp_chk.setObjectName(u"save_timestamp_chk")
        self.save_timestamp_chk.setChecked(True)

        self.save_hbox.addWidget(self.save_timestamp_chk)

        self.save_all_btn = QPushButton(self.save_bar_group)
        self.save_all_btn.setObjectName(u"save_all_btn")

        self.save_hbox.addWidget(self.save_all_btn)


        self.main_vbox.addWidget(self.save_bar_group)

        ODMRMainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(ODMRMainWindow)
        self.statusbar.setObjectName(u"statusbar")
        ODMRMainWindow.setStatusBar(self.statusbar)
        self.menubar = QMenuBar(ODMRMainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menu_file = QMenu(self.menubar)
        self.menu_file.setObjectName(u"menu_file")
        ODMRMainWindow.setMenuBar(self.menubar)

        self.menu_file.addAction(self.action_save_config)
        self.menu_file.addAction(self.action_save_config_as)
        self.menu_file.addAction(self.action_load_config)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.action_reset_defaults)

        self.retranslateUi(ODMRMainWindow)

        QMetaObject.connectSlotsByName(ODMRMainWindow)
    # setupUi

    def retranslateUi(self, ODMRMainWindow):
        ODMRMainWindow.setWindowTitle(QCoreApplication.translate("ODMRMainWindow", u"CW ODMR Magnetometry", None))
        self.action_save_config.setText(QCoreApplication.translate("ODMRMainWindow", u"Save Config", None))
#if QT_CONFIG(shortcut)
        self.action_save_config.setShortcut(QCoreApplication.translate("ODMRMainWindow", u"Ctrl+S", None))
#endif // QT_CONFIG(shortcut)
        self.action_save_config_as.setText(QCoreApplication.translate("ODMRMainWindow", u"Save Config As...", None))
        self.action_load_config.setText(QCoreApplication.translate("ODMRMainWindow", u"Load Config...", None))
        self.action_reset_defaults.setText(QCoreApplication.translate("ODMRMainWindow", u"Reset to Defaults", None))
        self.rf_group.setTitle(QCoreApplication.translate("ODMRMainWindow", u"MW Generator (SRS SG384)", None))
        self.rf_status_label.setText(QCoreApplication.translate("ODMRMainWindow", u"\u25cf Disconnected", None))
        self.rf_freq_label.setText(QCoreApplication.translate("ODMRMainWindow", u"Freq: \u2014 GHz", None))
        self.rf_freq_spinbox.setSuffix(QCoreApplication.translate("ODMRMainWindow", u" GHz", None))
        self.rf_set_btn.setText(QCoreApplication.translate("ODMRMainWindow", u"Set Freq", None))
        self.rf_amp_label.setText(QCoreApplication.translate("ODMRMainWindow", u"Amp: \u2014 dBm", None))
        self.rf_connect_btn.setText(QCoreApplication.translate("ODMRMainWindow", u"Connect RF", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.camera_tab), QCoreApplication.translate("ODMRMainWindow", u"Camera", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.sweep_tab), QCoreApplication.translate("ODMRMainWindow", u"ODMR Sweep", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.magnetometry_tab), QCoreApplication.translate("ODMRMainWindow", u"Magnetometry", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.analysis_tab), QCoreApplication.translate("ODMRMainWindow", u"Analysis", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.sensitivity_tab), QCoreApplication.translate("ODMRMainWindow", u"Sensitivity", None))
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.settings_tab), QCoreApplication.translate("ODMRMainWindow", u"Settings", None))
        self.save_bar_group.setTitle(QCoreApplication.translate("ODMRMainWindow", u"Save", None))
        self.label.setText(QCoreApplication.translate("ODMRMainWindow", u"Base path:", None))
        self.save_browse_btn.setText(QCoreApplication.translate("ODMRMainWindow", u"Browse", None))
        self.label1.setText(QCoreApplication.translate("ODMRMainWindow", u"Subfolder:", None))
        self.save_timestamp_chk.setText(QCoreApplication.translate("ODMRMainWindow", u"Timestamp", None))
        self.save_all_btn.setText(QCoreApplication.translate("ODMRMainWindow", u"Save All", None))
        self.menu_file.setTitle(QCoreApplication.translate("ODMRMainWindow", u"File", None))
    # retranslateUi

