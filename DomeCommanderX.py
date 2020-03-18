from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from DCXui3 import Ui_MainWindow
import sys, time
from socket import *

def sendcommand(command):
    #Function to comunicate with KoeppelX and issue commands
    HOST = 'Hercules'
    PORT = 65000
    BUFSIZ = 1024
    ADDR = (HOST, PORT)

    tcpCliSock = socket(AF_INET, SOCK_STREAM)
    tcpCliSock.connect(ADDR)

    tcpCliSock.send(command.encode('utf-8'))
    response = tcpCliSock.recv(BUFSIZ)
    tcpCliSock.close()

    return response

def domestatus():
    #Function to grab dome position and status
    info = sendcommand('POSITION')
    angle = float((info.split('\n'))[0])
    if angle < 0.: angle = angle + 360.
    if angle > 360.: angle = angle % 360.
    info = sendcommand('DOMEBUSY')
    status = int((info.split('\n'))[0])
    return (angle,status)

class initThread(QThread):
    #Class to run the initialization procedure moving the dome to +35 and calibrating
    def __init__(self):
        QThread.__init__(self)

    def __del__(self):
        self.wait()

    def run(self):
        jnk = sendcommand('goto +40')
        time.sleep(1)
        while domestatus()[1] == 1:
            time.sleep(1)
        jnk = sendcommand('calibrate')
        time.sleep(1)
        while domestatus()[1] == 1:
            time.sleep(1)


class parkThread(QThread):
    #Class to execute comands to park the dome at -30 from the calibrate point
    def __init__(self):
        QThread.__init__(self)

    def __del__(self):
        self.wait()

    def run(self):
        jnk = sendcommand('calibrate')
        time.sleep(1)
        while domestatus()[1] == 1:
            time.sleep(1)
        jnk = sendcommand('goto -30')
        time.sleep(1)
        while domestatus()[1] == 1:
            time.sleep(1)


class mywindow(QtWidgets.QMainWindow):
    #Main GUI for the dome commander, listens to Signals and activates Slots
    def __init__(self):
 
        #Initiate the GUI
        super(mywindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
 
        #Listeners for all control button signals, connects them to slots
        self.ui.initButton.clicked.connect(self.initClicked)
        self.ui.calibButton.clicked.connect(self.calibClicked)
        self.ui.parkButton.clicked.connect(self.parkClicked)
        self.ui.trackButton.clicked.connect(self.trackClicked)
        self.ui.stopButton.clicked.connect(self.stopClicked)
        self.ui.gotoButton.clicked.connect(self.gotoClicked)
        self.ui.lineEdit.returnPressed.connect(self.gotoClicked)
        self.ui.gp5Button.clicked.connect(self.gp5Clicked)
        self.ui.gm5Button.clicked.connect(self.gm5Clicked)

        #This loops the posBar procedure every timer cycle in ms
        timer=QTimer(self)
        timer.timeout.connect(self.posBar)
        timer.start(500)

    def initClicked(self):
        #Actions once Initialize is clicked (uses new threaded class)
        self.statusBar().showMessage('Initializing Dome')
        try:
            if self.myThread.isRunning(): 
                    self.myThread.terminate()
        except:
            pass
        self.myThread = initThread()
        self.myThread.finished.connect(lambda: self.statusBar().showMessage('Initialized!'))
        self.myThread.start()

    def calibClicked(self):
        #Actions when Calibrate is Clicked (functions built into KoepelX)
        self.statusBar().showMessage(sendcommand('calibrate'))

    def parkClicked(self):
        #Actions once Park is clicked (uses new threaded class)
        self.statusBar().showMessage('Parking Dome')
        try:
            if self.myThread.isRunning(): 
                    self.myThread.terminate()
        except:
            pass
        self.myThread = parkThread()
        self.myThread.finished.connect(lambda: self.statusBar().showMessage('Parked!'))
        self.myThread.start()

    def trackClicked(self):
        #Actions once Track is clicked (functions built into KoepelX)
        self.statusBar().showMessage(sendcommand('track'))

    def stopClicked(self):
        #Actions once Stop is clicked (informs KoepelX and tries to stop other threads)
        try:
            if self.myThread.isRunning(): 
                    self.myThread.terminate()
        except:
            pass
        self.statusBar().showMessage(sendcommand('stop'))

    def gotoClicked(self):
        #Actions when GoTo is clicked (sends contents of list box, checks first that somewhere)
        if self.ui.lineEdit.text() == '':
            self.statusBar().showMessage('Nowhere to GoTo!')
        else:
            self.statusBar().showMessage(sendcommand('goto '+self.ui.lineEdit.text()))
            self.ui.lineEdit.setText('')


    def gp5Clicked(self):
        #Actions when rotate plus 5 button is clicked
        self.statusBar().showMessage(sendcommand('goto +5'))

    def gm5Clicked(self):
        #Actions when rotate miuns 5 button is clicked
        self.statusBar().showMessage(sendcommand('goto -5'))

    def posBar(self):
        #Cycle to update postition bar and status indicator (blinks if active)
        status = domestatus()
        self.ui.progressBar.setValue(status[0])

        if status[1] == 1:
            if self.ui.radioButton.isChecked():
                self.ui.radioButton.setChecked(False)
            else:
                self.ui.radioButton.setChecked(True)
        else:
            self.ui.radioButton.setChecked(False)

#Run the application
app = QtWidgets.QApplication([])
 
application = mywindow()
application.setFixedSize(application.size())
application.show()

sys.exit(app.exec_())

