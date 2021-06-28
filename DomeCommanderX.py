import sys, enum, time, win32com.client, pythoncom

from socket import socket, AF_INET, SOCK_STREAM
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont
from pyqtgraph import TextItem
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation, SkyCoord, Angle
from datetime import datetime

import pyqtgraph as pg
import numpy as np
import pandas as pd

import time


# Blaauw Observatory location
LAT = 53.240243
LON = 6.53651
OBSERV_LOC = EarthLocation(lat=LAT*u.deg, lon=LON*u.deg)


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
    angle = float((pos.split(b'\n'))[0])
    
    if angle < 0.: angle = angle + 360.
    if angle > 360.: angle = angle % 360.

    return angle


def format_koepel_response(res):
    """
    Properly retrieve & decode the response 
    messages from KoepelX.
    """
    return (res.split(b'\n'))[1].decode("utf-8")


def is_dome_busy():
    """Return whether the dome is busy (moving)"""
    res = send_command('DOMEBUSY')
    busy = int((res.split(b'\n'))[0])

    return busy


# --------------------- #
#  Transformation stuff #
# --------------------- #


def vec4(x, y, z):
    """
    Return a 4-element vector, appropriate 
    for coordinate transformations.
    """
    return np.array([x, y, z, 1]) 


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

    H = H_01 @ H_12 @ H_23 @ rot_z(270) # TODO: maybe change the 270 once more?

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

    return (pos + 180) % 360


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
    exceeding_limits = pyqtSignal()
    update_dome_position = pyqtSignal(float, float)
    aperture_changed = pyqtSignal(TrackingState)
    telescope_data_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        self.telescope_data = None

        self.is_tracking = True
        self.dec_0 = None
        self.ha_0 = None
        self.ha_limit = None

        self.dome_az = None

        self.is_exceeding_limits = False

        self.azimuth_data = None # DataFrame w/ ha, dec, az, delta_ha
        self.tracking_state = TrackingState.default()

        self.aperture_changed.connect(self.on_aperture_changed)
        self.telescope_data_changed.connect(self.on_telescope_data_changed)

    def __del__(self):
        self.wait()
    
    def stop_tracking(self):
        """Exit the tracking (loop)"""
        self.is_tracking = False

    def setup(self, state=TrackingState.TELESCOPE):
        """Determine the object to track"""
        self.tracking_state = state
        self.set_azimuth_data(state)

    def run(self):
        while self.is_tracking:
            if self.telescope_data is not None:                
                if self.is_exceeding_limits or self.dome_az is None:

                    ha, dec = self._get_ha_dec()
                    az_new, ha_limit_new = None, None

                    try:
                        az_new, ha_limit_new = self._get_dome_azimuth(ha, dec)
                    except:
                        self.azimuth_error.emit()
                
                    is_ccd_inactive = True # TODO: communicate w/ main thread and only move when the CCD is not doing stuff!
                    if az_new is not None and is_ccd_inactive:
                        self.ha_0 = np.rint(ha*15)
                        self.dec_0 = np.rint(dec)
                        self.ha_limit = ha_limit_new
                        self.dome_az = (az_new + 180) % 360

                        self.is_exceeding_limits = False
                    
                        #print('Running goto?!')
                        self.update_dome_position.emit(self.dome_az, self.ha_limit)
                        send_command('goto ' + str(self.dome_az))
                
                # Check for any changes in the telescope orientation or object tracking
                try:
                    ha_cur, dec_cur = self._get_ha_dec()

                    ha_diff = np.rint(ha_cur - self.ha_0)*15 # Distance in HA (deg) since moving to the current azimuth

                    if not ha_cur is None and not dec_cur is None and self.dome_az is not None:

                        has_exceeded_ha_limit = ha_diff >= self.ha_limit and ha_diff > 0 # TODO: hope the 2nd 'and' fixes things...
                        is_dec_different = not np.isclose(self.dec_0, np.rint(dec_cur))

                        # Signal run(...) that the dome should got to a different azimuth! 
                        if not self.is_exceeding_limits and (has_exceeded_ha_limit or is_dec_different):
                            self.is_exceeding_limits = True
                            self.exceeding_limits.emit()
                except:
                    pass

                time.sleep(5) # TODO: larger time step? or remove? idk why I even added it anymore...

        print('finished tracking')

    # def tracking_status_watcher(self):
    #     """Check continuously whether the dome should move to a different position"""
    #     print('checking tracking status...')
    #     try:
    #         ha_cur, dec_cur = self._get_ha_dec()

    #         ha_diff = np.rint(ha_cur - self.ha_0)*15 # Distance in HA (deg) since moving to the current azimuth

    #         if not ha_cur is None and not dec_cur is None and self.dome_az is not None:
    #             #print('the HA limit is', self.ha_limit)

    #             has_exceeded_ha_limit = ha_diff >= self.ha_limit and ha_diff > 0 # TODO: hope the 2nd 'and' fixes things...
    #             is_dec_different = not np.isclose(self.dec_0, np.rint(dec_cur))

    #             # Signal run(...) that the dome should got to a different azimuth! 
    #             if not self.is_exceeding_limits and (has_exceeded_ha_limit or is_dec_different):
    #                 self.is_exceeding_limits = True
    #     except:
    #         pass
    
    def on_telescope_data_changed(self, data):
        self.telescope_data = data
        
        #print('retrieving data from the queue...', self.telescope_data)

    def on_aperture_changed(self, state):
        """Update the optimal azimuth data set"""
        self.set_azimuth_data(state)

    def set_azimuth_data(self, state=TrackingState.TELESCOPE):
        """Set the data set for the current aperture being tracked"""
        col_names = ['ha', 'dec', 'az', 'delta_ha']

        if state is TrackingState.TELESCOPE:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_telescope.csv', names=col_names)
        elif state is TrackingState.TELESCOPE_GUIDER:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_telescope.csv', names=col_names)
        elif state is TrackingState.FINDER:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_finder.csv', names=col_names)

        self.exceeding_limits.emit()
        self.is_exceeding_limits = True
    
    def _get_ha_dec(self):
        """
        Return the hour angle & dec of the current 
        target object, or that of the mount.
        """
        ha_cur, dec_cur = None, None

        if self.telescope_data['is_tracking']:
            ha_cur, dec_cur = self._get_current_target()
        else:
            ha_cur, dec_cur = self._get_current_orientation()

        # try:
        #     ha_cur, dec_cur = self._get_current_target()
        # except:
        #     pass
        
        # if not ha_cur and not dec_cur:
        #     ha_cur, dec_cur = self._get_current_orientation()

        if ha_cur < 0:
            ha_cur += 24
        
        return ha_cur, dec_cur


    def _get_current_target(self):
        """Return current target hour angle/dec"""
        sys.coinit_flags = 0
        pythoncom.CoInitialize()    

        tsxo = win32com.client.Dispatch("TheSkyXAdaptor.ObjectInformation")

        tsxo.Property(70)
        target_ha = tsxo.ObjInfoPropOut

        # TODO: remove these 2 lines?
        # tsxo.Property(54) # wrt current epoch; use 57 for J2000
        # target_ra = tsxo.ObjInfoPropOut

        tsxo.Property(56) # wrt current epoch; use 58 for J2000
        target_dec = tsxo.ObjInfoPropOut
        
        tsxo.CoUninitialize()

        # return target_ra, target_dec
        return target_ha, target_dec
    
    def _get_current_orientation(self):
        """Return the current hour angle/dec of the mount"""
        scope_ha = self.telescope_data['ha']
        scope_dec = self.telescope_data['dec']

        return scope_ha, scope_dec
    
    def _get_dome_azimuth(self, ha, dec):
        """Retrieve the optimal dome azimuth"""
        ha, dec = np.rint(ha*15), np.rint(dec)

        az_idx = np.isclose(self.azimuth_data['ha'], ha) & np.isclose(self.azimuth_data['dec'], dec)

        desired_az = self.azimuth_data['az'][az_idx].array[0]
        ha_dist = self.azimuth_data['delta_ha'][az_idx].array[0]

        return desired_az, ha_dist

class DataRetrieverThread(QThread):
    """Thread keeping track of changed in the widgets"""
    update_telescope_status = pyqtSignal(dict)
    update_dome_status = pyqtSignal(dict)
    update_dome_radar = pyqtSignal()

    def __init__(self, cooldown):
        super().__init__()

        self.ui_is_running = True
        self.cooldown = cooldown
    
    def __del__(self):
        self.ui_is_running = False
        self.wait()

    def run(self):
        while self.ui_is_running:
            self.retrieve_dome_status()
            self.retrieve_telescope_status()

            self.update_dome_radar.emit()

            time.sleep(self.cooldown)
       
    def retrieve_dome_status(self):
        dome_az = get_dome_pos()
        is_busy = is_dome_busy()

        self.update_dome_status.emit({
          'az': dome_az,
          'is_busy': is_busy
        })

    def retrieve_telescope_status(self):
        sys.coinit_flags = 0
        pythoncom.CoInitialize()    

        self.telescope = win32com.client.Dispatch("TheSkyXAdaptor.RASCOMTele")
        self.telescope.Connect()
        
        is_tracking = self.telescope.IsTracking

        self.telescope.GetRaDec()
        scope_ra  = self.telescope.dRA
        scope_dec = self.telescope.dDec

        observing_time = Time(datetime.now(), scale='utc', location=OBSERV_LOC)
        lst = observing_time.sidereal_time('mean').hour

        ha = lst - scope_ra

        self.update_telescope_status.emit({
            'ra': scope_ra,
            'dec': scope_dec,
            'is_tracking': is_tracking,
            'lst': lst,
            'ha': ha,
            'ccd': 'Error...' #ccd.ExposureStatus
        })

        pythoncom.CoUninitialize()

class MainWindow(QtWidgets.QMainWindow):
    
    aperture_switched = pyqtSignal(TrackingState)
    lst_changed = pyqtSignal(float)

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

        self.data_worker = DataRetrieverThread()
        self.data_worker.finished.connect(lambda: self._log_message('Somehow the DataRetriever stopped working...'))
        self.data_worker.update_dome_status.connect(self.on_dome_status_changed)
        self.data_worker.update_telescope_status.connect(self.on_telescope_status_changed)
        self.data_worker.update_dome_radar.connect(self.draw_dome_radar)
        self.data_worker.start()
        
        self.telescope_status = dict()
        self.dome_status = dict()
        self.ha_bar_timestamp = 0

    def draw_dome_radar(self):
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

        if self.dome_status:
            slit_size = 34 # slit width in degrees at the horizon

            az_corrected = justify(self.dome_status['az'] + 180)  # 180 to fix the orientation wrt NESW
            slit_az = np.arange(np.radians(az_corrected - slit_size/2), np.radians(az_corrected + slit_size/2), 0.01)
            dome_radius = np.ones(slit_az.size)

            # Transform to cartesian and plot
            slit_coords = polar_to_cart(dome_radius, slit_az)
            self.domeRadar.plot(*slit_coords, pen=pg.mkPen(width=5))

        if self.telescope_status:
            aperture, direction = get_telescope_position(self.telescope_status['ha'] * 15, self.telescope_status['dec'])

            scope_coords = np.array([[0, 0], aperture[:2], aperture[:2] + 1.4*direction[:2]])
            self.domeRadar.plot(scope_coords[:, 0], scope_coords[:, 1], pen=pg.mkPen(color='r', width=3))
    
    def _init_routine(self):
        """To run when the GUI starts."""
        self._log_message('Starting dome control software...')

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

    def on_dome_status_changed(self, status):
        # Update dome position
        self.azIndicator.setProperty('text', '{:.1f} deg'.format(status['az']))

        # Update tracking status
        is_tracking = False
        try:
            is_tracking = self.thread.isRunning() and hasattr(self.thread, 'is_tracking')
        except:
            pass

        tracking_status = 'Active' if is_tracking else 'Inactive'
        self.trackingIndicator.setProperty('text', tracking_status)
        
        # Update movement info
        idle_status = 'Yes' if not status['is_busy'] else 'No'
        self.movingIndicator.setProperty('text', idle_status)

        self.dome_status = status

    def on_telescope_status_changed(self, status):
        scope_coords = SkyCoord(ra=status['ra']*u.hour, dec=status['dec']*u.degree)

        ra_fmt, dec_fmt = scope_coords.to_string('hmsdms').split(' ')
        self.raIndicator.setProperty('text', ra_fmt)
        self.decIndicator.setProperty('text', dec_fmt)
        
        lst_fmt = Angle(status['lst'], unit='hourangle').hms
        self.lstIndicator.setProperty('text', '{}h{}m{}s'.format(lst_fmt.h, lst_fmt.m, lst_fmt.s)) # TODO: maybe fix?
        
        scope_ha = status['lst'] - status['ra']
        ha_fmt = Angle(scope_ha, unit='hourangle').hms
        self.haIndicator.setProperty('text', '{}h{}m{}s'.format(ha_fmt.h, ha_fmt.m, ha_fmt.s))

        try:
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.telescope_data_changed.emit(status) 
        except:
            pass
        
        self.telescope_status = status

        delta_t = status['list'] - self.ha_bar_timestamp
        self.haBar.setValue(int(delta_t * 60))

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
        self._log_message(format_koepel_response(msg))

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
        
        self._log_message('Dome is preparing to track the telescope')

        try:
            if self.thread.isRunning(): 
                    self.thread.terminate()
        except:
            pass
        
        self.thread = TrackingThread()
        self.thread.azimuth_error.connect(self.on_azimuth_error)
        self.thread.exceeding_limits.connect(self.on_limits_exceeded)
        self.thread.update_dome_position.connect(self.on_dome_moving)
        self.thread.setup(state=self._get_tracking_state())
        self.thread.finished.connect(self.on_tracking_finished)
        self.thread.start()

    def on_tracking_finished(self):
        self._log_message('Disengaged telescope tracking!')
        self.haBar.setMaximum(0)
    
    def on_limits_exceeded(self):
        self._log_message('Dome is looking for a new position... Moving in ~5 seconds!')

    def on_dome_moving(self, az, ha_limit):
        self._log_message('Slewing the dome to {:.1f} degrees'.format(az))
        self.update_ha_progress_bar_limits(ha_limit)

    def update_ha_progress_bar_limits(self, ha_dist):
        self.timestamp = self.telescope_status['lst'] # hours
        self.haBar.setMaximum(int(ha_dist/15 * 60)) # convert to minutes and round off, cuz the bar doesn't do decimals
        self.setValue(0)

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
        self._log_message(format_koepel_response(msg))

    def goto_clicked(self):
        """Go to azimuth (deg) input via azEdit"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
               self.thread.terminate()
        except:
            pass

        if self.azEdit.text() == '':
            self._log_message('Dome has nowhere to go to!')
        else:
            msg = send_command('goto ' + self.azEdit.text())
            self._log_message(format_koepel_response(msg))
            
            # Reset the TextEdit
            self.azEdit.setText('')

    def plus_5_clicked(self):
        """Move the azimuth by +5 deg"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
               self.thread.terminate()
        except:
            pass

        msg = send_command('goto +5')
        self._log_message(format_koepel_response(msg))

    def min_5_clicked(self):
        """Move the azimuth by -5 deg"""
        try:
            # Stop tracking when trying to position the dome manually
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.stop_tracking()
               self.thread.terminate()
        except:
            pass

        msg = send_command('goto -5')
        self._log_message(format_koepel_response(msg))

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
                           Dome remains at {:.0f} degrees for now...'.format(get_dome_pos()))


def main():
    """Launching the Qt app"""
    app = QtWidgets.QApplication([])
    main = MainWindow()
    main.show()

    sys.exit(app.exec_())


if __name__ == '__main__':         
    main()