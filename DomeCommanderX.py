import sys, enum, time, win32com.client, pythoncom

from socket import socket, AF_INET, SOCK_STREAM
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from pyqtgraph import TextItem
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import EarthLocation, SkyCoord
from datetime import datetime

import pyqtgraph as pg
import numpy as np
import pandas as pd 

# Blaauw Observatory location
LAT = 53.240243
LON = 6.53651
OBSERV_LOC = EarthLocation(lat=LAT*u.deg, lon=LON*u.deg)

# Connect to the telescope / TheSkyXInformation (for the target position) / CCD (for exposure status) 
sys.coinit_flags = 0
pythoncom.CoInitialize()    

telescope = win32com.client.Dispatch("TheSkyXAdaptor.RASCOMTele")
telescope.Connect()

tsxo = win32com.client.Dispatch("TheSkyXAdaptor.ObjectInformation")
tsxo.connect()

ccd = win32com.client.Dispatch("CCDSoft2XAdaptor.ccdsoft5Camera")
ccd.Connect()

def send_command(command):
    """Send a command to KoepelX"""
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

def get_dome_pos():
    """Get the dome position (azimuth)"""
    pos = send_command('POSITION')
    angle = float((pos.split('\n'))[0])
    
    if angle < 0.: angle = angle + 360.
    if angle > 360.: angle = angle % 360.

    return angle

def is_dome_busy():
    """Return whether the dome is busy (moving)"""
    res = send_command('DOMEBUSY')
    busy = int((res.split('\n'))[0])

    return busy

# --------------------- #
#  Transformation stuff #
# --------------------- #

def vec4(x, y, z):
    """
    Return a 4-element vector, appropriate 
    for coordinate transformations.
    """
    return np.array([x, y, z, 1]) #np.array([x, y, z, 1]).reshape((4,1))

def vec3(v4):
    """
    Convert a 4-element vector to a 3-element vector.
    """
    v3 = v4[:3].reshape(3)

    return v3

def transform(x, y, z):
    """Transform a vector (x', y', z', 1)."""
    return np.array([
        [1, 0, 0, x],
        [0, 1, 0, y],
        [0, 0, 1, z],
        [0, 0, 0, 1],
    ])

def rot_x(angle):
    """
    Rotate a vector (x, y, z, 1) about the x-axis 
    in a right-handed coordinate system.
    """
    angle = np.radians(angle)

    return np.array([
        [1,             0,              0, 0],
        [0, np.cos(angle), -np.sin(angle), 0],
        [0, np.sin(angle),  np.cos(angle), 0],
        [0,             0,              0, 1],
    ])

def rot_y(angle):
    """
    Rotate a vector (x, y, z, 1) about the y-axis 
    in a right-handed coordinate system.
    """
    angle = np.radians(angle)

    return np.array([
        [np.cos(angle),  0,  -np.sin(angle), 0],
        [0,              1,               0, 0],
        [-np.sin(angle), 0,   np.cos(angle), 0],
        [0,              0,               0, 1],
    ])

def rot_z(angle):
    """
    Rotate a vector (x, y, z, 1) about the z-axis 
    in a right-handed coordinate system.
    """
    angle = np.radians(angle)

    return np.array([
        [np.cos(angle),  -np.sin(angle), 0, 0],
        [np.sin(angle),  np.cos(angle), 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ])

def get_telescope_position(ha, dec):
    H_01 = transform(0, 0, 0.26)
    H_12 = rot_x(90-LAT) @ rot_z(-ha) @ transform(0, 0, 0.35)
    H_23 = rot_x(dec) @ transform(-0.14, 0, 0)

    H = H_01 @ H_12 @ H_23

    H_unit = transform(0, 1, 0)

    H_diff = H @ H_unit - H

    ap_pos = H @ vec4(0, 0, 0)
    direction = H_diff @ vec4(0, 0, 0)

    return vec3(ap_pos), vec3(direction)

def polar_to_cart(radius, theta):
    """
    Convert polar to cartesian coordinates,
    since Qt can't draw polar graphs :(
    """
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)

    return x, y

def justify(pos):
    """
    Adjust the polar graph, s.t. 0 deg is north, 
    90 deg is east, 180 south, and 270 west.
    """
    pos = 360 - pos
    pos += 90

    if pos >= 360:
        pos %= 360

    if pos < 0:
        pos += 360

    return pos

class InitThread(QThread):
    """
    Thread to run the initialization procedure: 
    moving the dome to +35 and calibrating.
    """
    def __init__(self):
        super().__init__()

    def __del__(self):
        self.wait()

    def run(self):
        jnk = send_command('goto +40')

        time.sleep(1)
        
        while is_dome_busy() == 1:
            time.sleep(1)
        
        jnk = send_command('calibrate')
        time.sleep(1)
        
        while is_dome_busy() == 1:
            time.sleep(1)


class ParkThread(QThread):
    """
    Thread to execute commands to park the dome at 
    -30 deg from the calibration point.
    """
    def __init__(self):
        super().__init__()

    def __del__(self):
        self.wait()

    def run(self):
        jnk = send_command('calibrate')
        time.sleep(1)
        
        while is_dome_busy() == 1:
            time.sleep(1)
        
        jnk = send_command('goto -30')
        time.sleep(1)
        
        while is_dome_busy() == 1:
            time.sleep(1)

class TrackingState(enum.Enum):
    """
    Enum signifying which (combination) of 
    aperture(s) is being tracked.
    """
    TELESCOPE = 1
    TELESCOPE_GUIDER = 2
    FINDER = 3

    @classmethod
    def default(obj):
        return obj.TELESCOPE

class TrackingThread(QThread):
    """
    Control thread, for the dome tracking the telescope.
    """
    azimuth_error = pyqtSignal()
    aperture_changed = pyqtSignal(TrackingState)

    def __init__(self):
        super().__init__()

        self.is_tracking = True
        self.dec_0 = None
        self.ha_0 = None
        self.ha_limit = None

        self.dome_az = None

        self.is_exceeding_limits = False

        self.data = None # DataFrame w/ ha, dec, az, delta_ha
        self.tracking_state = TrackingState.default()

        self.aperture_changed.connect(self.on_aperture_changed)

        # Run a timer that verifies that an object is being tracked!
        tracking_timer = QTimer(self)
        tracking_timer.timeout.connect(self.tracking_status_watcher)
        tracking_timer.start(5000) # TODO: change as appropriate

    def __del__(self):
        self.wait()
    
    def stop_tracking(self):
        """Stop the tracking (loop) and the timer"""
        self.is_tracking = False
        self.tracking_timer.stop()

    def setup(self, state=TrackingState.TELESCOPE):
        """Determine the object to track"""
        try:
            ha, dec = self._get_ha_dec()
        except:
            ha, dec = 0, 0

        self.ha_0 = ha
        self.dec = dec
        self.tracking_state = state

        self.set_azimuth_data(state)

    def run(self):
        while self.is_tracking:
            if self.is_exceeding_limits or self.dome_az is None:
                ha, dec = self._get_ha_dec()
                az_new, ha_limit_new = None, None

                try:
                    az_new, ha_limit_new = self._get_dome_azimuth(ha, dec)
                except:
                    self.azimuth_error.emit()
                
                if az_new is not None:
                    self.ha_0 = ha
                    self.dec_0 = dec
                    self.ha_limit = ha_limit_new
                    self.dome_az = az_new

                    self.is_exceeding_limits = False
                    
                    send_command('goto ' + str(self.dome_az))

            time.sleep(10) # TODO: larger time step? or remove? idk why I even added it anymore...
    
    def tracking_status_watcher(self):
        """Check continuously whether the dome should move to a different position"""
        ha_cur, dec_cur = self._get_ha_dec()
        ha_diff = ha_cur - self.ha_0 # Distance in HA since moving to the current azimuth

        if not ha_cur is None and not dec_cur is None and self.dome_az is not None:
            print(self.ha_limit)
            has_exceeded_ha_limit = ha_diff >= self.ha_limit
            is_dec_different = not np.isclose(self.dec_0, np.rint(dec_cur))

            # Signal run(...) that the dome should got to a different azimuth! 
            if not self.is_exceeding_limits and (has_exceeded_ha_limit or is_dec_different):
                self.is_exceeding_limits = True
            
    def on_aperture_changed(self, state):
        """Update the optimal azimuth data set"""
        self.set_azimuth_data(state)

    def set_azimuth_data(self, state=TrackingState.TELESCOPE):
        """Set the data set for the current aperture being tracked"""
        col_names = ['ha', 'dec', 'az', 'delta_ha']

        if state is TrackingState.TELESCOPE:
            self.data = pd.read_csv('optimal_azimuth_telescope_16_Jun_2021.csv', names=col_names)
        elif state is TrackingState.TELESCOPE_GUIDER:
            self.data = pd.read_csv('optimal_azimuth_telescope_16_Jun_2021.csv', names=col_names)
        elif state is TrackingState.FINDER:
            self.data = pd.read_csv('optimal_azimuth_finder_16_Jun_2021.csv', names=col_names)

        return self.data
    
    def _get_ha_dec(self):
        """
        Return the hour angle & dec of the current 
        target object, or that of the mount.
        """
        ha_cur, dec_cur = None, None

        if telescope.IsTracking:
            ha_cur, dec_cur = self._get_current_target()
        else:
            ha_cur, dec_cur = self._get_current_orientation()
            
        # try:
        #     ha_cur, dec_cur = self._get_current_target()
        # except:
        #     pass
        
        # if not ha_cur and not dec_cur:
        #     ha_cur, dec_cur = self._get_current_orientation()
        
        return ha_cur, dec_cur


    def _get_current_target(self):
        """Return current target hour angle/dec"""
        tsxo.Property(70)
        target_ha = tsxo.ObjInfoPropOut

        # TODO: remove these 2 lines?
        # tsxo.Property(54) # wrt current epoch; use 57 for J2000
        # target_ra = tsxo.ObjInfoPropOut

        tsxo.Property(56) # wrt current epoch; use 58 for J2000
        target_dec = tsxo.ObjInfoPropOut

        # return target_ra, target_dec
        return target_ha, target_dec
    
    def _get_current_orientation(self):
        """Return the current hour angle/dec of the mount"""
        observing_time = Time(datetime.now(), scale='utc', location=OBSERV_LOC)
        lst = observing_time.sidereal_time('mean')

        telescope.GetRaDec()   
        scope_ra  = telescope.dRa
        scope_dec = telescope.dDec
        
        scope_ha = lst.hour - scope_ra

        return scope_ha, scope_dec
    
    def _get_dome_azimuth(self, ha, dec):
        """Retrieve the optimal dome azimuth"""
        ha, dec = np.rint(ha*15), np.rint(dec)

        az_idx = np.isclose(self.data['ha'], ha) & np.isclose(self.data['dec'], dec)

        desired_az = self.data['az'][az_idx].array[0]
        ha_dist = self.data['delta_ha'][az_idx].array[0]

        return desired_az, ha_dist

class MainWindow(QtWidgets.QMainWindow):

    aperture_switched = pyqtSignal(TrackingState)

    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)
        
        # Load the UI
        uic.loadUi('resources/DomeCommanderX.ui', self)

        self._init_routine()

        # Listeners for the control buttons
        self.initButton.clicked.connect(self.init_clicked)
        self.calibrateButton.clicked.connect(self.calibrate_clicked)
        self.parkButton.clicked.connect(self.park_clicked)
        self.trackButton.clicked.connect(self.track_clicked)
        self.stopButton.clicked.connect(self.stop_clicked)

        self.gotoButton.clicked.connect(self.goto_clicked)
        self.azEdit.returnPressed.connect(self.goto_clicked)
        self.gm5Button.clicked.connect(self.plus_5_clicked)
        self.gp5Button.clicked.connect(self.min_5_clicked)

        self.apertureSelector.currentTextChanged.connect(self.on_aperture_changed)

        # Update outputs periodically (every 200 ms)
        update_timer = QTimer(self)
        update_timer.timeout.connect(self.update_widgets)
        update_timer.start(200)

    def plot_dome(self, dome_pos, scope_pos):
        """
        Plot a polar graph w/ the telescope & dome, given the 
        dome position (azimuth) and telescope position (ha, dec).
        """
        self.domeRadar.clear()

        self.domeRadar.hideAxis('left')
        self.domeRadar.hideAxis('bottom')

        self.domeRadar.setLimits(xMin=-1.5, xMax=1.5, yMin=-1.5, yMax=1.5)

        self.domeRadar.addLine(x=0, pen=0.2, bounds=(-1, 1))
        self.domeRadar.addLine(y=0, pen=0.2, bounds=(-1, 1))

        self.domeRadar.addLine(angle=45, pen=0.2, bounds=(-1, 1))
        self.domeRadar.addLine(angle=-45, pen=0.2, bounds=(-1, 1))
    
        # Add Alt/Az horizon markers
        nesw_font = QFont()
        nesw_font.setPixelSize(14)
        nesw_font.setBold(True)

        north = TextItem('N', anchor=(0.5, 0.5))
        self.domeRadar.addItem(north)
        north.setPos(0, 1.25)
        north.setFont(nesw_font)

        east = TextItem('E', anchor=(0.5, 0.5))
        self.domeRadar.addItem(east)
        east.setPos(1.25, 0)
        east.setFont(nesw_font)
        
        south = TextItem('S', anchor=(0.5, 0.5))
        self.domeRadar.addItem(south)
        # south.setPos(-0.2, -1.2)
        south.setPos(0, -1.25)
        south.setFont(nesw_font)

        west = TextItem('W', anchor=(0.5, 0.5))
        self.domeRadar.addItem(west)
        west.setPos(-1.25, 0)
        west.setFont(nesw_font)
    
        dome_r = 1
        mount_r = 0.05
        
        mount = pg.QtGui.QGraphicsEllipseItem(-mount_r, -mount_r, mount_r * 2, 2*mount_r)
        mount.setPen(pg.mkPen(color='r', width=10))
        self.domeRadar.addItem(mount)

        dome = pg.QtGui.QGraphicsEllipseItem(-dome_r, -dome_r, dome_r * 2, 2*dome_r)
        dome.setPen(pg.mkPen(0.2))
        self.domeRadar.addItem(dome)

        # Generate dome/scope data
        slit_size = 34 # slit in degrees at the horizon
        
        dome_az = np.arange(np.radians(dome_pos - slit_size/2), np.radians(dome_pos + slit_size/2), 0.01)
        dome_radius = np.ones(dome_az.size)

        # Transform to cartesian and plot
        dome_coords = polar_to_cart(dome_radius, dome_az)

        self.domeRadar.plot(*dome_coords, pen=pg.mkPen(width=5))

        aperture, direction = get_telescope_position(scope_pos[0] * 15, scope_pos[1])

        scope_coords = np.array([aperture[:2], 1.2*direction[:2]])
        self.domeRadar.plot(*scope_coords, pen=pg.mkPen(color='r', width=3))
    
    def _init_routine(self):
        """To run when the GUI starts."""
        self._log_message('Started dome control software...')

        # TODO: Get the default tracking aperture

    def _log_message(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        text = '[{}] {}'.format(timestamp, msg)

        self.log.append(text)

    def _get_tracking_state(self):
        aperture = self.apertureSelector.currentText()

        if aperture == 'Telescope':
            target = TrackingState.TELESCOPE
        elif aperture == 'Telescope + Guider':
            target = TrackingState.TELESCOPE_GUIDER
        elif aperture == 'Finder':
            target = TrackingState.FINDER
        else:
            self._log_message('ERROR... Unknown aperture selected for tracking! Setting it to the default: telescope...')
            target = TrackingState.TELESCOPE
        
        return target

    def update_widgets(self):
        """
        Get the current dome/telescope position/status 
        and update the counter and the graph.
        """
        dome_az = get_dome_pos()

        telescope.GetAzAlt()   
        scope_az  = telescope.dAz
        scope_alt = telescope.dAlt

        telescope.GetRaDec()   
        scope_ra  = telescope.dRa
        scope_dec = telescope.dDec

        scope_coords = SkyCoord(ra=scope_ra*u.hour, dec=scope_dec*u.degree)

        # Update dome position
        self.azIndicator.setProperty('text', '{:.1f} deg'.format(dome_az))

        # Update tracking status
        is_tracking = False # TODO: retrieve tracking status
        tracking_status = 'Active' if True else 'Inactive'
        self.trackingIndicator.setProperty('text', tracking_status)
        
        # Update movement info
        idle_status = 'Yes' if not is_dome_busy() else 'No'
        self.movingIndicator.setProperty('text', idle_status)

        # Update telescope status
        ra_fmt, dec_fmt = scope_coords.to_string('hmsdms').split(' ')
        self.raIndicator.setProperty('text', ra_fmt)
        self.decIndicator.setProperty('text', dec_fmt)

        observing_time = Time(datetime.now(), scale='utc', location=OBSERV_LOC)
        lst = observing_time.sidereal_time('mean').hour
        
        scope_ha = lst - scope_ra
        self.lstIndicator.setProperty('text', '{:.2f} h'.format(lst))
        self.haIndicator.setProperty('text', '{:.2f} h'.format(scope_ha))

        # Update the plot
        self.plot_dome(justify(dome_az), (scope_ha, scope_dec))

        # Update CCD info (useful for displaying when the dome should not move!)
        ccd_status = ccd.ExposureStatus # TODO: use status to now move the dome when the CCD is exposed or reading out
        self.ccdIndicator.setProperty('text', ccd_status)

    def init_clicked(self):
        """Initialize & run the dome calibration routine"""
        self._log_message('Initializing the dome...')
        try:
            if self.thread.isRunning(): 
                    self.thread.terminate()
        except:
            pass
        
        self.thread = InitThread()
        self.thread.finished.connect(lambda: self._log_message('Dome initialized!'))
        self.thread.start()

    def calibrate_clicked(self):
        """Run KoepelX's calibration routine"""
        msg = send_command('calibrate')
        self._log_message(msg)

    def park_clicked(self):
        """Park the dome"""
        self._log_message('Parking dome')

        try:
            if self.thread.isRunning(): 
                    self.thread.terminate()
        except:
            pass
        
        self.thread = ParkThread()
        self.thread.finished.connect(lambda: self._log_message('Dome is parked!'))
        self.thread.start()

    def track_clicked(self):
        """Init. telescope tracking using KoepelX"""
        
        self._log_message('Dome is now tracking the telescope')

        try:
            if self.thread.isRunning(): 
                    self.thread.terminate()
        except:
            pass
        
        self.thread = TrackingThread()
        self.thread.azimuth_error.connect(self.on_azimuth_error)
        self.thread.setup(state=self._get_tracking_state())
        self.thread.finished.connect(lambda: self._log_message('Disengaged telescope tracking!'))
        self.thread.start()

    def stop_clicked(self):
        """Informs KoepelX and tries to stop other threads"""
        try:
            if self.thread.isRunning():
                if  hasattr(self.thread, 'is_tracking'):
                    self.thread.stop_tracking()
                
                self.thread.terminate()
        except:
            pass
        
        msg = send_command('stop')
        self._log_message(msg)

    def goto_clicked(self):
        """Go to azimuth (deg) input via azEdit"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
        except:
            pass

        if self.azEdit.text() == '':
            self._log_message('Dome has nowhere to go to!')
        else:
            msg = send_command('goto ' + self.azEdit.text())
            self._log_message(msg)
            
            # Reset the TextEdit
            self.azEdit.setText('')

    def plus_5_clicked(self):
        """Move the azimuth by +5 deg"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
        except:
            pass

        msg = send_command('goto +5')
        self._log_message(msg)

    def min_5_clicked(self):
        """Move the azimuth by -5 deg"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
        except:
            pass

        msg = send_command('goto -5')
        self._log_message(msg)

    def on_aperture_changed(self):
        """
        Ran when the aperture selection combobox 
        state is changed.
        """
        target_aperture = self._get_tracking_state()

        if target_aperture is TrackingState.TELESCOPE:
            self._log_message('Change tracking to focus on the telescope..!')
        elif target_aperture is TrackingState.TELESCOPE_GUIDER:
            self._log_message('Change tracking to focus on the telescope & autoguider..!')
        elif target_aperture is TrackingState.FINDER:
            self._log_message('Change tracking to focus on the finder..!')
        
        try:
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.aperture_changed.emit(target_aperture) 
        except:
            pass
        
    def on_azimuth_error(self):
        """Log error when no azimuth can be found for the current hour angle/dec"""
        self._log_message('ERROR... No azimuth available for the current telescope orientation! \
                           Dome remains at an azimuth of {:.0f} degrees for now...'.format(get_dome_pos()))

def main():
    """Launching the Qt app"""
    app = QtWidgets.QApplication([])
    main = MainWindow()
    main.show()

    sys.exit(app.exec_())

if __name__ == '__main__':         
    main()