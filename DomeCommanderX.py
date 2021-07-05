import sys, enum, time, win32com.client, pythoncom

from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation, SkyCoord, Angle
from datetime import datetime

import pyqtgraph as pg
import numpy as np
import pandas as pd

from DomeCommanderX_Helpers import (
    LAT, 
    LON, 
    send_command, 
    get_dome_pos, 
    is_dome_busy,
    format_koepel_response, 
    rot_z,
    get_telescope_position, 
    altitude,
    justify, 
    polar_to_cart
)


OBSERV_LOC = EarthLocation(lat=LAT*u.deg, lon=LON*u.deg)


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


class TrackingThread(QThread):
    """
    Control thread, for the dome tracking the telescope.

    Public methods
    --------------

    stop_tracking: gracefully exit the thread
    """
    azimuth_error = pyqtSignal()
    exceeding_limits = pyqtSignal()
    update_dome_position = pyqtSignal(float, float)
    aperture_changed = pyqtSignal(TrackingState)
    telescope_data_changed = pyqtSignal(dict)
    update_ha_dist = pyqtSignal(float)

    def __init__(self, state=TrackingState.TELESCOPE):
        """
        Initialise the tracking thread.

        Parameters
        ----------
        state (TrackingState): aperture to track
        """
        super().__init__()

        self.telescope_data = None

        self.is_tracking = True
        self.dec_0 = None
        self.ha_0 = None
        self.ha_limit = None

        self.dome_az = None

        self.is_exceeding_limits = False

        self.azimuth_data = None # DataFrame w/ ha, dec, az, delta_ha
        self.tracking_state = state

        self.set_azimuth_data(state)

        self.aperture_changed.connect(self.on_aperture_changed)
        self.telescope_data_changed.connect(self.on_telescope_data_changed)

    def __del__(self):
        self.wait()
    
    def stop_tracking(self):
        """Exit the tracking loop."""
        self.is_tracking = False

    def run(self):
        """Track the selected aperture and checks whenever the dome should move, every 5 seconds."""
        while self.is_tracking:
            if self.telescope_data is not None:                
                if (self.is_exceeding_limits or self.dome_az is None) and not self.telescope_data['is_slewing']:

                    ha, dec = self._get_ha_dec()
                    az_new, ha_limit_new = None, None

                    try:
                        az_new, ha_limit_new = self._get_dome_azimuth(ha, dec)
                    except:
                        self.azimuth_error.emit()
                
                    is_ccd_inactive = True # TODO: communicate w/ main thread and only move when the CCD is not doing stuff!
                    if az_new is not None and is_ccd_inactive:
                        self.ha_0 = ha*15
                        self.dec_0 = dec
                        self.ha_limit = ha_limit_new
                        self.dome_az = (az_new + 180) % 360

                        print('moving @ HA', ha, '& Dec', dec)
                           
                        self.is_exceeding_limits = False
                    
                        #print('Running goto?!')
                        msg = send_command('goto ' + str(self.dome_az))
                        self.update_dome_position.emit(self.dome_az, self.ha_limit)
                
                # Check for any changes in the telescope orientation or object tracking
                try:
                    ha_cur, dec_cur = self._get_ha_dec()

                    ha_diff = ha_cur*15 - self.ha_0 # Distance in HA (deg) since moving to the current azimuth
                    #print('limit =', self.ha_limit, 'deg vs. current HA difference =', ha_diff, 'deg', )
                    self.update_ha_dist.emit((self.ha_limit - ha_diff)/15 * 60)

                    if not ha_cur is None and not dec_cur is None and self.dome_az is not None:

                        has_exceeded_ha_limit = ha_diff > self.ha_limit and ha_diff > 0 # TODO: hope the 2nd 'and' fixes things...
                        is_dec_different = not np.isclose(np.rint(self.dec_0), np.rint(dec_cur))

                        # Signal run(...) that the dome should got to a different azimuth! 
                        if not self.is_exceeding_limits and (has_exceeded_ha_limit or is_dec_different):
                            self.is_exceeding_limits = True
                            self.exceeding_limits.emit()
                except:
                    pass

                time.sleep(5) # TODO: larger time step? or remove? idk why I even added it anymore...

        print('finished tracking')
    
    def on_telescope_data_changed(self, data):
        """
        Set relevant telescope info.

        Parameters
        ----------
        data (dict): dictionary of telescope info (ha, dec, lst, etc...)
        """
        self.telescope_data = data

    def on_aperture_changed(self, state):
        """
        Set the azimuth data when the aperture has been 
        changed in the dropdown menu.

        Parameters
        ----------
        state (TrackingState): aperture to track
        """
        self.set_azimuth_data(state)

    def set_azimuth_data(self, state=TrackingState.TELESCOPE):
        """
        Load & set the tracking data set.

        Parameters
        ----------
        state (TrackingState): aperture to track
        """
        col_names = ['ha', 'dec', 'az', 'delta_ha']

        if state is TrackingState.TELESCOPE:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_telescope.csv', names=col_names)
        elif state is TrackingState.TELESCOPE_GUIDER:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_telescope.csv', names=col_names)
        elif state is TrackingState.FINDER:
            self.azimuth_data = pd.read_csv('resources/optimal_azimuth_finder.csv', names=col_names)

        # Signal that the limits are exceeded to force run() to update the dome position
        self.exceeding_limits.emit()
        self.is_exceeding_limits = True
    
    def _get_ha_dec(self):
        """
        Get the HA/Dec of the object currently being tracked by TheSkyX
        or the current telescope orientation when the former is not available.

        Returns
        -------
        ha_cur, dec_cur (float, float): the HA (hours) and Dec (deg)
        """
        ha_cur, dec_cur = None, None

        try:
            ha_cur, dec_cur = self._get_current_target()
        except:
            ha_cur, dec_cur = self._get_current_orientation()

        if ha_cur < 0:
            ha_cur += 24
        
        return ha_cur, dec_cur


    def _get_current_target(self):
        """
        Get the HA/Dec of the object currently being tracked by TheSkyX.

        Returns
        -------
        target_ha, target_dec (float, float): the HA (hours) and Dec (deg)
        """
        sys.coinit_flags = 0
        pythoncom.CoInitialize()    

        tsxo = win32com.client.Dispatch("TheSkyXAdaptor.ObjectInformation")

        tsxo.Property(70)
        target_ha = tsxo.ObjInfoPropOut

        tsxo.Property(56) # wrt current epoch; use 58 for J2000
        target_dec = tsxo.ObjInfoPropOut
        
        tsxo.CoUninitialize()

        return target_ha, target_dec
    
    def _get_current_orientation(self):
        """
        Get the HA/Dec of the mount.

        Returns
        -------
        scope_ha, scope_dec (float, float): the HA (hours) and Dec (deg)
        """
        scope_ha = self.telescope_data['ha']
        scope_dec = self.telescope_data['dec']

        return scope_ha, scope_dec
    
    def _get_dome_azimuth(self, ha, dec):
        """
        Select the optimal azimuth from the data file for the selected aperture(s).

        Parameters
        ----------
        ha (float): current HA (deg)
        dec (float): current Dec (deg)

        Returns
        -------
        desired_az (float): the optimal dome azimuth (deg)
        ha_dist (float): the time (in hours) the dome can remain at the 'optimal' position
        """
        ha, dec = np.rint(ha*15), np.rint(dec) # round off so that they can be used w/ the grid

        az_idx = np.isclose(self.azimuth_data['ha'], ha) & np.isclose(self.azimuth_data['dec'], dec)

        desired_az = self.azimuth_data['az'][az_idx].array[0]
        ha_dist = self.azimuth_data['delta_ha'][az_idx].array[0]

        return desired_az, ha_dist

class DataRetrieverThread(QThread):
    """Thread keeping track of changes in the telescope/dome status."""
    update_telescope_status = pyqtSignal(dict)
    update_dome_status = pyqtSignal(dict)
    update_dome_radar = pyqtSignal()

    def __init__(self, cooldown=1):
        """
        Initialise the data retriever.

        Parameters
        ----------
        cooldown (int): the interval (in seconds) on which the telescope/dome data should be updated
        """
        super().__init__()

        self.ui_is_running = True
        self.cooldown = cooldown
    
    def __del__(self):
        self.ui_is_running = False
        self.wait()

    def run(self):
        """Update the telescope/dome status periodically"""
        while self.ui_is_running:
            self.retrieve_dome_status()
            self.retrieve_telescope_status()

            self.update_dome_radar.emit()

            time.sleep(self.cooldown)
       
    def retrieve_dome_status(self):
        """Retrieve dome status from KoepelX"""
        dome_az = get_dome_pos()
        is_busy = is_dome_busy()

        self.update_dome_status.emit({
          'az': dome_az,
          'is_busy': is_busy
        })

    def retrieve_telescope_status(self):
        """Retrieve telescope status from TheSkyX"""
        sys.coinit_flags = 0
        pythoncom.CoInitialize()    

        telescope = win32com.client.Dispatch("TheSkyXAdaptor.RASCOMTele")
        telescope.Connect() 
        
        # TODO: add support for the CCD exposure status
        #ccd = win32com.client.Dispatch("CCDSoft2XAdaptor.ccdsoft5Camera")
        #ccd.Connect()

        ccd_status = 'TBD'#ccd.ExposureStatus
        
        is_tracking = telescope.IsTracking
        is_slewing = telescope.IsSlewComplete == 0

        telescope.GetRaDec()
        scope_ra  = telescope.dRA
        scope_dec = telescope.dDec

        observing_time = Time(datetime.now(), scale='utc', location=OBSERV_LOC)
        lst = observing_time.sidereal_time('mean').hour

        ha = lst - scope_ra

        self.update_telescope_status.emit({
            'ra': scope_ra,
            'dec': scope_dec,
            'is_tracking': is_tracking,
            'lst': lst,
            'ha': ha,
            'is_slewing': is_slewing,
            'ccd': ccd_status
        })

        pythoncom.CoUninitialize()

class MainWindow(QtWidgets.QMainWindow):
    """Qt's main window providing control over the GUI."""
    
    aperture_switched = pyqtSignal(TrackingState)
    lst_changed = pyqtSignal(float)

    def __init__(self, *args, **kwargs):
        """
        Initialise the main window, e.g. setting the listeners for the input (buttons/textboxes)"""
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

        self.data_worker = DataRetrieverThread(cooldown=1)
        self.data_worker.finished.connect(lambda: self._log_message('Somehow the DataRetriever stopped working...'))
        self.data_worker.update_dome_status.connect(self.on_dome_status_changed)
        self.data_worker.update_telescope_status.connect(self.on_telescope_status_changed)
        self.data_worker.update_dome_radar.connect(self.draw_dome_radar)
        self.data_worker.start()
        
        # Telescope & dome status
        self.telescope_status = dict()
        self.dome_status = dict()
        self.ha_bar_timestamp = 0

    def draw_dome_radar(self):
        """
        Plot a polar graph w/ the telescope & dome, given the 
        dome position and telescope orientation.
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

        north = pg.TextItem('N', anchor=(0.5, 0.5))
        self.domeRadar.addItem(north)
        north.setPos(0, 1.25)
        north.setFont(nesw_font)

        east = pg.TextItem('E', anchor=(0.5, 0.5))
        self.domeRadar.addItem(east)
        east.setPos(1.25, 0)
        east.setFont(nesw_font)
        
        south = pg.TextItem('S', anchor=(0.5, 0.5))
        self.domeRadar.addItem(south)
        south.setPos(0, -1.25)
        south.setFont(nesw_font)
        
        west = pg.TextItem('W', anchor=(0.5, 0.5))
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

            # Compute the dome rectangle border
            dome_border = np.array([[-0.3, -0.26, 0, 1], [0.3, -0.26, 0, 1], [0.3, 1, 0, 1], [-0.3, 1, 0, 1], [-0.3, -0.26, 0, 1]]).T
            dome_coords = (rot_z(-self.dome_status['az']) @  dome_border).T

            self.domeRadar.plot(dome_coords[:, 0], dome_coords[:, 1], pen=pg.mkPen(width=2))

        if self.telescope_status:
            aperture, direction = get_telescope_position(self.telescope_status['ha'] * 15, self.telescope_status['dec'])
            ap_x = -aperture[0]
            ap_y = -aperture[1]
            aperture = np.array([ap_x, ap_y])
            
            alt_r = np.cos(altitude(self.telescope_status['ha']*15, self.telescope_status['dec']))

            scope_coords = np.array([[0, 0], aperture[:2], aperture + alt_r*direction[:2]/np.sqrt(direction[0]**2+direction[1]**2)])
            self.domeRadar.plot(scope_coords[:, 0], scope_coords[:, 1], pen=pg.mkPen(color='r', width=3))

            alt_angles = np.arange(0, 2*np.pi, 0.01)
            radii = alt_r*np.ones(alt_angles.size)

            # Transform to cartesian and plot
            alt_x, alt_y = polar_to_cart(radii, alt_angles)
            offset_x, offset_y = aperture[0], aperture[1]

            alt_x = offset_x + alt_x
            alt_y = offset_y + alt_y

            self.domeRadar.plot(alt_x, alt_y, pen=pg.mkPen(color='r', width=0.4))
    
    def _init_routine(self):
        """To run when the GUI starts."""
        self._log_message('Starting dome control software...')
        
        self.domeRadar.clear()

        self.domeRadar.hideAxis('left')
        self.domeRadar.hideAxis('bottom')

    def _log_message(self, msg):
        """
        Add a timestamped status message to the log box.

        Parameters
        ----------
        msg (str): the message
        """
        timestamp = datetime.now().strftime('%H:%M:%S')
        text = '[{}] {}'.format(timestamp, msg)

        self.log.append(text)

    def _get_tracking_state(self):
        """
        Return the tracking state based on the item selected in the aperture dropdown.

        Returns
        -------
        target (TrackingState): the (target) aperture; the aperture to track
        """
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
        """
        Listen to any changes in the dome status and update the UI.

        Parameters
        ----------
        status (dict): the dome status (azimuth, whether it's tracking, whether it's moving)
        """
        self.azIndicator.setProperty('text', '{:.1f} deg'.format(status['az'])) # Update dome position

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
        """
        Listen to any changes in the telescope status and update the UI.

        Parameters
        ----------
        status (dict): the dome status (ra, ha, dec, lst, ccd status, etc...)
        """
        scope_coords = SkyCoord(ra=status['ra']*u.hour, dec=status['dec']*u.degree)

        ra_fmt, dec_fmt = scope_coords.to_string('hmsdms').split(' ')
        self.raIndicator.setProperty('text', ra_fmt)
        self.decIndicator.setProperty('text', dec_fmt)
        
        self.ccdIndicator.setProperty('text', status['ccd'])

        lst_fmt = Angle(status['lst'], unit='hourangle').hms
        self.lstIndicator.setProperty('text', '{:02.0f}h{:02.0f}m{:02.0f}s'.format(lst_fmt.h, np.abs(lst_fmt.m), np.abs(lst_fmt.s))) # TODO: maybe fix?
        
        scope_ha = status['lst'] - status['ra']
        ha_fmt = Angle(scope_ha, unit='hourangle').hms
        self.haIndicator.setProperty('text', '{:02.0f}h{:02.0f}m{:02.0f}s'.format(ha_fmt.h, np.abs(ha_fmt.m), np.abs(ha_fmt.s)))

        try:
            if self.thread.isRunning() and hasattr(self.thread, 'is_tracking'):
               self.thread.telescope_data_changed.emit(status) 
        except:
            pass
        
        self.telescope_status = status

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
        """
        Init. telescope tracking using KoepelX and spawn a tracking thread"""
        
        self._log_message('Dome is preparing to track the telescope')

        try:
            if self.thread.isRunning(): 
                    self.thread.terminate()
        except:
            pass
        
        self.thread = TrackingThread(state=self._get_tracking_state())
        self.thread.azimuth_error.connect(self.on_azimuth_error)
        self.thread.exceeding_limits.connect(self.on_limits_exceeded)
        self.thread.update_ha_dist.connect(self.update_ha_progress_bar)
        self.thread.update_dome_position.connect(self.on_dome_moving)
        self.thread.finished.connect(self.on_tracking_finished)
        self.thread.start()

    def on_tracking_finished(self):
        """Reset the HA progress bar when the tracking has been disengaged"""
        self._log_message('Disengaged telescope tracking!')
        self.haBar.setMaximum(0)
    
    def on_limits_exceeded(self):
        """
        Listen to when the limits (HA dist. or when the aperture changes) are
        exceeded and send a message that the dome will soon move, since the dome 
        updates/checks its position only every 5 seconds.
        """
        self._log_message('Dome is looking for a new position... Moving in ~5 seconds!')

    def on_dome_moving(self, az, ha_limit):
        """Update the HA progress bar whenever the dome moves to a new position"""
        self._log_message('Slewing the dome to {:.1f} degrees'.format(az))
        
        self.ha_bar_timestamp = self.telescope_status['lst'] # hours
        
        remaining = int(ha_limit/15 * 60) # convert to minutes and round off, cuz the bar doesn't do decimals
        
        self.haBar.setMaximum(remaining) 
        self.haBar.setValue(remaining)

    def update_ha_progress_bar(self, current_time_remaining):
        """Set the HA progress bar's value, which decreases over time"""
        self.haBar.setValue(int(current_time_remaining))

    def stop_clicked(self):
        """
        Informs KoepelX and tries to stop other threads, and if
        the dome is tracking the telescope: stop the tracking.
        """
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
        """Move the dome to a specific azimuth (deg), input via azEdit"""
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
        """Move the dome azimuth by +5 deg"""
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
        """Move the dome azimuth by -5 deg"""
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
        Run when the aperture selection combobox state is changed 
        and signal the tracking thread if it's running.
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