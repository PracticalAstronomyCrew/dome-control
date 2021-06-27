import threading, time, socket, logging, Queue, sys, win32com.client
from configobj import ConfigObj
from validate import Validator

# Used globals
currentPos = 0.0                  # Starting position
domeBusy = False                # Boolean for movement of dome
configfile = 'resources/config.ini'       # Config file
configspecfile = 'resources/configspec.ini' # Config file specification
calibrating = False             # Indicator if the current state is 'calibrating'

# Read and write functions are defined here
# For usage with a different library or os, only the section below needs to be modified to access the printerport in a proper way
# pportWrite(portaddress, value)
# pportRead(portaddress)
from ctypes import windll
pportWrite = windll.inpoutx64.DlPortWritePortUchar
pportRead = windll.inpoutx64.DlPortReadPortUchar

class Position(threading.Thread):
# Class used for the tracking of the position of the dome
    lastActivity = -1           # Time of last activity, start inactive

    def run(self):
    # Main function for measuring the pulses from rotary encoder. 
    # Also auto-calibrates when passing zeroPoint
    
            # Used global parameters
            global cfg
            global currentPos
            global calibrating
            
            lastWrittenPos = 0          # Last position written to file
            
            pportWrite(int(cfg['ctrlReg']), 12) # Set data register to output mode
            statregold = pportRead(int(cfg['statusReg'])) # Last status of port
            
            # Reading current position from file
            f = open(cfg['currentPosFile'], mode='r+')
            try:
                tmp = f.read()
                if tmp == '':
                    # Catch the case when file is empty
                    currentPos = float(cfg['zeroAngle']) * float(cfg['pulsesPerDegree'])
                    logging.error('Empty positioning-file. Current position defined as zeroAngle (%s).' % (float(cfg['zeroAngle']),))
                else:
                    currentPos = float(tmp)
                    lastWrittenPos = currentPos
            except (IOError, ValueError):
                # In case of reading a string or IOerror, truncate file and define position as zeroAngle
                f.seek(0)
                f.truncate()
                currentPos = float(cfg['zeroAngle']) * float(cfg['pulsesPerDegree'])
                logging.error('Invalid positioning-file. Current position defined as zeroAngle (%s).' % (float(cfg['zeroAngle']),))
            
            try:
                while 1:
                    statreg = pportRead(int(cfg['statusReg']))

                    if ((statreg & int(cfg['bitA'])) and (~statregold & int(cfg['bitA']))):
                        # New pulse
                        self.lastActivity = time.clock()
                        currentPos += ((statreg & int(cfg['bitB']))/int(cfg['bitB'])*2 - 1) * (int(cfg['invDirection'])*2 - 1)
			
                    
                    statregold = statreg

                    if not (statreg & int(cfg['zeroBit'])):
                        # Zero point has been reached
                        if calibrating:
                            # stop calibration if calibration is in progress
                            calibrating = False 
#                        elif cfg["autoCalibrate"]:
#                            currentPos = float(cfg['zeroAngle']) * float(cfg['pulsesPerDegree'])
#			    print('DANGER SETB AT AUTOCLAIB POSITION')
                    
                    if time.clock() - self.lastActivity < float(cfg['activeTime']):
                        # Active; high processor usage
                        time.sleep(float(cfg['sleepTimeAct']))
                    else:
                        # Passive; low processor usage
                        if lastWrittenPos != currentPos:
                            # Write to file
                            f.seek(0)
                            f.truncate()
                            f.write(str(currentPos))
                            f.flush()
                            lastWrittenPos = currentPos
                            
                        time.sleep(float(cfg['sleepTimePas']))
            except:
                # Write mose recent value and close position-file in case of exception
                f.truncate(0)
                f.write(str(currentPos))
                f.flush()
                f.close()
                logging.error("Error in reading port, class Position closed")
                raise

    def makeActive(self):
        # Make the current position reading state active
        self.lastActivity = time.clock()
    
class Movement(threading.Thread):
    # Movement functions: tracking, goto, calibrate, left, right, clearmove.
    # _<function>_ are only called internally

    nextAction = ''
    nextPosition = 0
    
    def track(self):
        # Tracking the telescope using COM-interface of TheSky
        
        global domeBusy
        
        if domeBusy:
            return 0
        else:
            self.nextAction='track'
            return 1
    
    def _track_(self):
        global domeBusy
        global currentPos
        global cfg
        global ObjTele
        
        domeBusy = True
        
        # Python Com-interface needs to be re-initialized for seperate thread
        import pythoncom
        sys.coinit_flags = 0
        pythoncom.CoInitialize()
        
        logging.info("Tracking telescope.")
        oldPos = currentPos
        tmpTime = time.clock()

        ObjTele = win32com.client.Dispatch("TheSkyXAdaptor.RASCOMTele")
        
        try:
            ObjTele.Connect()
        except:
            logging.error("Cannot connect to telescope.")
            domeBusy = False
            
        if ObjTele.IsConnected == 0:
            domeBusy = False
        
        movingLeft = False
        movingRight = False
            
        while domeBusy:
            try:
                # Get Azimuth angle of telescope
                ObjTele.GetAzAlt()
            except:
                logging.error("Connection to telescope lost.")
                domeBusy = False
                break
            
            # calculate difference between telescope and dome opening (middle)
            dif = ((180. + ObjTele.dAz) * float(cfg['pulsesPerDegree']) - currentPos) % (360. * float(cfg['pulsesPerDegree']))
    
            if (dif < (180. - 0.5 * float(cfg['domeOpeningAngle'])) * float(cfg['pulsesPerDegree']) and not movingLeft):
                # Move to left
                self.clearmove(keepBusyState = True)
                self.setleft(isTracking = True)
                movingLeft = True
                movingRight = False
                oldTime = time.clock()
                oldPos = currentPos
                
            if (dif > (180. + 0.5 * float(cfg['domeOpeningAngle'])) * float(cfg['pulsesPerDegree']) and not movingRight):
                # Move to right
                self.clearmove(keepBusyState = True)
                self.setright(isTracking = True)
                movingRight = True
                movingLeft = False
                oldTime = time.clock()
                oldPos = currentPos
            
            # check movement of dome to left
            if movingLeft:
                if (time.clock() - oldTime > float(cfg['moveTimeout'])):
                    if (oldPos == currentPos):
                        # Raise error
                        logging.error("Timeout occured in moving dome.")
                        domeBusy = False
                        break
                    else:
                        oldTime = time.clock()
                        oldPos = currentPos
                
                # wait for telescope tot arrive at lefthandside of dome opening
                if (dif > (180. - 0.55 * float(cfg['domeOpeningAngle'])) * float(cfg['pulsesPerDegree'])):
                    logging.info("Dome followed telecope")
                    movingLeft = False
                    movingRight = False
                    self.clearmove(keepBusyState = True)
                    
            # check movement of dome to left
            if movingRight:
                if (time.clock() - oldTime > float(cfg['moveTimeout'])):
                    if (oldPos == currentPos):
                        # Raise error
                        logging.error("Timeout occured in moving dome.")
                        domeBusy = False
                        break
                    else:
                        oldTime = time.clock()
                        oldPos = currentPos
                        
                # wait for telescope tot arrive at lefthandside of dome opening
                if (dif < (180. - 0.45 * float(cfg['domeOpeningAngle'])) * float(cfg['pulsesPerDegree'])):
                    logging.info("Dome followed telecope")
                    movingLeft = False
                    movingRight = False
                    self.clearmove(keepBusyState = True)
            
            # set measuring timeout
            if movingLeft or movingRight:
                time.sleep(float(cfg['checkInterval']))
            else:
                time.sleep(float(cfg['trackInterval']))
        
        # Uninitialize Com interface
        pythoncom.CoUninitialize()

    def goto(self, position):
        # Goto function for telescope to rotate to a given angle
        # [x] Error checking on degree number
        global domeBusy
        
        if domeBusy:
            return 0
        else:
            self.nextPosition=position
            self.nextAction='goto'
            return 1
        
    def _goto_(self, position):
        global domeBusy
        global currentPos
        global cfg
        
        logging.info("Moving from degree %s to %s" % (currentPos/float(cfg['pulsesPerDegree']),position))
        oldPos = currentPos
        tmpTime = time.clock()
        
        if (currentPos / float(cfg['pulsesPerDegree']) - position) % 360. < 180.:
            # Move left
            self.setleft()
            
            # Loop till dome has reached given position
            while (currentPos - position * float(cfg['pulsesPerDegree'])) % (360. * float(cfg['pulsesPerDegree'])) < 180. * float(cfg['pulsesPerDegree']) and domeBusy:
                time.sleep(float(cfg['checkInterval']))
                if (time.clock() - tmpTime > float(cfg['moveTimeout'])):
                    if (oldPos == currentPos):
                        # Raise error
                        logging.error("Timeout occured in moving dome to left.")
                        break
                    else:
                        tmpTime = time.clock()
                        oldPos = currentPos
            
            if domeBusy:
                self.clearmove()
        else:
            # Move right
            self.setright()
            
            # Loop till dome has reached given position
            while (currentPos - position * float(cfg['pulsesPerDegree'])) % (360. * float(cfg['pulsesPerDegree'])) > 180. * float(cfg['pulsesPerDegree']) and domeBusy:
                time.sleep(float(cfg['checkInterval']))
                if (time.clock() - tmpTime > float(cfg['moveTimeout'])):
                    if (oldPos == currentPos):
                        # Raise error
                        logging.error("Timeout occured in moving dome to right.")
                        break
                    else:
                        tmpTime = time.clock()
                        oldPos = currentPos
            
            if domeBusy:
                self.clearmove()
        
    def calibrate(self):    
        # Calibration function, dome moves to zeroPoint and stops (in Position class)
        
        global domeBusy
        
        if domeBusy:
            return 0
        else:
            self.nextAction = 'calibrate'
            return 1
        
    def _calibrate_(self):
        global cfg
        global currentPos
        global domeBusy
        global calibrating
        
        logging.info("Calibrating zero-point of dome.")
        
        if (currentPos / float(cfg['pulsesPerDegree']) - float(cfg['zeroAngle'])) % 360. < 180.:
            # Left is the shortest way
            self.setleft()
        else:
            # Right is the shortest way
            self.setright()
        
        calibrating = True
        oldPos = currentPos
        tmpTime1 = time.clock()
        tmpTime2 = time.clock()
        
        # check movement of dome during calibration
        while calibrating and domeBusy:
            if time.clock() - tmpTime1 > float(cfg['calibrateTimeOut']):
                # Raise error
                logging.error("Timeout in calibration dome, previous position (now being set to 0): %s." % currentPos/float(cfg['pulsesPerDegree']))
                break

            if (time.clock() - tmpTime2 > float(cfg['moveTimeout'])):
                if (oldPos == currentPos):
                    # Raise error
                    logging.error("Timeout occured in moving dome.")
                    domeBusy = False
                    break
                else:
                    tmpTime2 = time.clock()
                    oldPos = currentPos
            
            time.sleep(float(cfg['checkInterval']))
        
        # dome reached zeroPoint or error occured
        if domeBusy:
            self.clearmove()
            currentPos = float(cfg['zeroAngle']) * float(cfg['pulsesPerDegree'])
            logging.info("Finished calibration.")
        else:
            logging.info("Movement cleared before zero point was reached.")
        
        calibrating = False
    
    def setleft(self, isTracking = False):
        # Function to move dome to left
        
        global cfg
        global domeBusy
        
        # check difference between internal call of movement (by tracking) of external
        if domeBusy == False or isTracking:
            domeBusy = True
            logging.info("Moving dome to left.")
            pportWrite(int(cfg['dataReg']), int(cfg['leftBit']))
            time.sleep(float(cfg['pulseTime']))
            pportWrite(int(cfg['dataReg']), 0)
            return 1
        else:
            return 0

    def clearmove(self, keepBusyState = False):
        # stop movement of dome
        
        global cfg
        global domeBusy
	global currentPos
        
        logging.info("Stop movement of dome.")
        pportWrite(int(cfg['dataReg']), int(cfg['clearBit']))
        time.sleep(float(cfg['pulseTime']))
        pportWrite(int(cfg['dataReg']), 0)
        
        # set domeBusy to false if stop call was external (keep busy if tracking)
        if not keepBusyState:
            domeBusy = False        
            
    def setright(self, isTracking = False):
        # move dome to right
        
        global cfg
        global domeBusy
        
        # check difference between internal call of movement (by tracking) of external
        if domeBusy == False or isTracking:
            domeBusy = True
            logging.info("Moving dome to right.")
            pportWrite(int(cfg['dataReg']), int(cfg['rightBit']))
            time.sleep(float(cfg['pulseTime']))
            pportWrite(int(cfg['dataReg']), 0)
            return 1
        else:
            return 0

    def run(self):
        # function which handles next actions for movement
        while 1:
            if self.nextAction != '':
                if self.nextAction == 'goto':
                    self._goto_(self.nextPosition)
                if self.nextAction == 'calibrate':
                    self._calibrate_()
                if self.nextAction == 'track':
                    self._track_()
                    
                self.nextAction = ''
            time.sleep(float(cfg['checkNextAction']))
            
class ClientThread(threading.Thread):
    # Class which handles commands from every client connecting via server
    
    def handlecommand(self, string):
        global domeBusy
        
        # The commands are defined below
        commandList = {'POSITION': ((currentPos/float(cfg["pulsesPerDegree"])), "The current position is %s" % (int(currentPos/float(cfg["pulsesPerDegree"]),))),
                       'PULSEPOSITION': (currentPos, "The current position in pulses is %s" % (currentPos,)),
                       'DOMEBUSY': (int(domeBusy),domeBusy),
                       'GOTO': 'self.goto(args[0])',
                       'CALIBRATE': 'self.calibrate()',
                       'LEFT': 'self.setleft()',
                       'RIGHT': 'self.setright()',
                       'STOP': '(1,"Movement cleared."); Move.clearmove()',
                       'UPDATECONFIG': 'self.updateconfig()',
                       'TRACK': 'self.track()'}
        
        command = string.split()[0]
        args = string.split()[1:]
        
        exec("res = %s" % (commandList.get(command.upper(), "(0,'Command doesn`t exist')"),))
        return res
    
    def goto(self, strdegree):
        # check difference between goto a relative angle (+ or -) or a absolute angle
        if strdegree[0] == '+' or strdegree[0] == '-':
            try:
                degree = currentPos/float(cfg["pulsesPerDegree"]) + float(strdegree)
            except TypeError:
                return (0, "Invalid degree number: %s" % strdegree)
        else:
            try:
                degree = float(strdegree)
            except TypeError:
                return (0, "Invalid degree number: %s" % strdegree)
        
        if Move.goto(degree):
            return (1,"Moving dome to %s." % int(degree))
        else: 
            return (0,"Dome is busy")
        
    def calibrate(self):
        if Move.calibrate():
            return (1,"Calibrating dome.")
        else:
            return (0,"Dome is busy")

    def setleft(self):
        if not Move.setleft():
            return (0,"Dome is busy")
        else:
            return (1,"Moving dome to left.")

    def setright(self):
        if not Move.setright():
            return (0,"Dome is busy")
        else:
            return (1,"Moving dome to right.")
    
    def updateconfig(self):
        if updateconfig():
            return (1, 'Config file read.')
        else:
            return (0, 'Error in reading config file')
    
    def track(self):
        if not Move.track():
            return (0, 'Dome is busy.')
        else:
            return (1, 'Tracking telescope.') 
            
    def run(self):
        global cfg
        global clientPool
        
        while True:
            client = clientPool.get()
            
            if client != None:
                logging.info('Connection received from %s on port %s' % client[1])
                command = client[0].recv(int(cfg['bufferSize']))
                if command == '':
                    logging.info('Connection with %s lost' % (client[1][0],))
                else:
                    logging.info('Command given from %s: %s' % (client[1][0], command))
                    res = self.handlecommand(command)
                    client[0].send("%s\n%s\n" % (res[0],res[1]))
                    logging.info('Returned to %s: %s, code: %o' % (client[1][0], res[1], res[0]))
                    client[0].close()
                    logging.info('Connection to %s closed' % (client[1][0],))
                    
class ServerThread(threading.Thread):
    # Class for setting up a server
    # Server handles incoming connection requests
    
    def run(self):
        global cfg
        global clientPool
        
        # Create client pool and threads
        clientPool = Queue.Queue(int(cfg['maxQueueSize']))
        for x in xrange(int(cfg['clientThreads'])):
            ClientThread().start()
        
        # Set up the server:
        server = socket.socket ( socket.AF_INET, socket.SOCK_STREAM )
        server.bind ( ( socket.gethostname(), int(cfg['serverPort']) ) )
        server.listen ( int(cfg['maxConnections']) )
        
        while True:
            clientPool.put ( server.accept() )
            
                       
def updateconfig():
    # Function to update the config file when called on by a client
    
    global cfg
    global val
    
    try:
        cfg.reload()
    except ReloadError:
        logging.error("Error reading configfile")
        return 0
    
    if not (cfg.validate(val)):
        logging.error("Error in configfile")
        return 0
    
    logging.info("Config file read.")
    return 1


# Read configfile
cfg = ConfigObj(configfile, configspec=configspecfile)
cfg.stringify = True
val = Validator()
if not (cfg.validate(val)):
    print("Error in configfile")
    import sys
    sys.exit()

# Set logging config
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S',
                    filename=cfg['logfile'],
                    filemode='a')          

# Spawn threads
Position().start()
ServerThread().start()
Move = Movement()
Move.start()
