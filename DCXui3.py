# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'DomeCommanderX3.ui'
#
# Created by: PyQt5 UI code generator 5.13.0
#
# WARNING! All changes made in this file will be lost!


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(549, 87)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        MainWindow.setSizePolicy(sizePolicy)
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap("domecommand.ico"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        MainWindow.setWindowIcon(icon)
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.lineEdit = QtWidgets.QLineEdit(self.centralwidget)
        self.lineEdit.setGeometry(QtCore.QRect(450, 10, 91, 31))
        self.lineEdit.setObjectName("lineEdit")
        self.gotoButton = QtWidgets.QPushButton(self.centralwidget)
        self.gotoButton.setGeometry(QtCore.QRect(470, 40, 51, 21))
        self.gotoButton.setStyleSheet("background-color: rgb(85, 255, 127);\n"
"selection-background-color: rgb(170, 85, 127);")
        self.gotoButton.setObjectName("gotoButton")
        self.initButton = QtWidgets.QPushButton(self.centralwidget)
        self.initButton.setGeometry(QtCore.QRect(10, 10, 51, 51))
        self.initButton.setStyleSheet("background-color: rgb(0, 170, 255);\n"
"selection-background-color: rgb(170, 85, 127);")
        self.initButton.setObjectName("initButton")
        self.calibButton = QtWidgets.QPushButton(self.centralwidget)
        self.calibButton.setGeometry(QtCore.QRect(70, 10, 51, 51))
        self.calibButton.setStyleSheet("background-color: rgb(0, 170, 255);\n"
"selection-background-color: rgb(170, 85, 127);")
        self.calibButton.setObjectName("calibButton")
        self.trackButton = QtWidgets.QPushButton(self.centralwidget)
        self.trackButton.setGeometry(QtCore.QRect(190, 10, 121, 21))
        self.trackButton.setStyleSheet("background-color: rgb(255, 255, 127);\n"
"selection-background-color: rgb(170, 85, 127);")
        self.trackButton.setObjectName("trackButton")
        self.parkButton = QtWidgets.QPushButton(self.centralwidget)
        self.parkButton.setGeometry(QtCore.QRect(130, 10, 51, 51))
        self.parkButton.setStyleSheet("background-color: rgb(0, 170, 255);\n"
"selection-background-color: rgb(170, 85, 127);")
        self.parkButton.setObjectName("parkButton")
        self.stopButton = QtWidgets.QPushButton(self.centralwidget)
        self.stopButton.setGeometry(QtCore.QRect(320, 10, 121, 21))
        self.stopButton.setStyleSheet("background-color: rgb(255, 85, 0);\n"
"selection-background-color: rgb(255, 0, 255);\n"
"font: 75 8pt \"MS Shell Dlg 2\";\n"
"color: rgb(255, 255, 127);")
        self.stopButton.setObjectName("stopButton")
        self.progressBar = QtWidgets.QProgressBar(self.centralwidget)
        self.progressBar.setGeometry(QtCore.QRect(190, 40, 121, 21))
        self.progressBar.setMaximum(360)
        self.progressBar.setProperty("value", 68)
        self.progressBar.setObjectName("progressBar")
        self.radioButton = QtWidgets.QRadioButton(self.centralwidget)
        self.radioButton.setGeometry(QtCore.QRect(320, 40, 121, 21))
        self.radioButton.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.radioButton.setStyleSheet("selection-color: rgb(255, 0, 0);")
        self.radioButton.setCheckable(True)
        self.radioButton.setChecked(False)
        self.radioButton.setObjectName("radioButton")
        self.gm5Button = QtWidgets.QPushButton(self.centralwidget)
        self.gm5Button.setGeometry(QtCore.QRect(450, 40, 21, 21))
        font = QtGui.QFont()
        font.setFamily("Wingdings 3")
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.gm5Button.setFont(font)
        self.gm5Button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.gm5Button.setStyleSheet("background-color: rgb(0, 85, 0);\n"
"color: rgb(255, 255, 255);")
        self.gm5Button.setObjectName("gm5Button")
        self.gp5Button = QtWidgets.QPushButton(self.centralwidget)
        self.gp5Button.setGeometry(QtCore.QRect(520, 40, 21, 21))
        font = QtGui.QFont()
        font.setFamily("Wingdings 3")
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.gp5Button.setFont(font)
        self.gp5Button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.gp5Button.setStyleSheet("background-color: rgb(0, 85, 0);\n"
"color: rgb(255, 255, 255);")
        self.gp5Button.setObjectName("gp5Button")
        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setSizeGripEnabled(False)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "DomeCommanderX"))
        self.gotoButton.setText(_translate("MainWindow", "GoTo"))
        self.initButton.setText(_translate("MainWindow", "Initialize"))
        self.calibButton.setText(_translate("MainWindow", "Calibrate"))
        self.trackButton.setText(_translate("MainWindow", "Track"))
        self.parkButton.setText(_translate("MainWindow", "Park"))
        self.stopButton.setText(_translate("MainWindow", "STOP"))
        self.progressBar.setFormat(_translate("MainWindow", "%v°"))
        self.radioButton.setText(_translate("MainWindow", "Dome Busy"))
        self.gm5Button.setToolTip(_translate("MainWindow", "Goto -5"))
        self.gm5Button.setText(_translate("MainWindow", "Q"))
        self.gp5Button.setToolTip(_translate("MainWindow", "Goto +5"))
        self.gp5Button.setText(_translate("MainWindow", "P"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec_())
