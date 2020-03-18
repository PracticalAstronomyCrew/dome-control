from socket import *
import numpy as np
import matplotlib
matplotlib.use('wxagg')
import matplotlib.pyplot as plt
import time
import win32com.client
import pythoncom
import sys

HOST = 'Hercules'
PORT = 65000
BUFSIZ = 1024
ADDR = (HOST, PORT)

slit_size = 5.

sys.coinit_flags = 0
pythoncom.CoInitialize()    
ObjTele = win32com.client.Dispatch("TheSkyXAdaptor.RASCOMTele")
ObjTele.Connect()
    
while 1:

    tcpCliSock = socket(AF_INET, SOCK_STREAM)
    tcpCliSock.connect(ADDR)
    tcpCliSock.send('POSITION')
    POPO = tcpCliSock.recv(BUFSIZ)
    position = float(POPO.split('\n')[0])
    if position < 0.: position = position + 360.
    if position > 360.: position = position % 360.
    tcpCliSock.close()

    tcpCliSock = socket(AF_INET, SOCK_STREAM)
    tcpCliSock.connect(ADDR)
    tcpCliSock.send('DOMEBUSY')
    DOSO = tcpCliSock.recv(BUFSIZ)
    dome_status = int(DOSO.split('\n')[0])
    tcpCliSock.close()

    ObjTele.GetAzAlt()   
    scope_az = ObjTele.dAz

    theta = np.arange((position-(slit_size/2.))/180.*np.pi,(position+(slit_size/2.))/180.*np.pi,0.01)
    r = [1.] * len(theta)

    tr = np.arange(0.,1.1,0.1)
    tthe = [scope_az/180.*np.pi] * len(tr)

    plt.rcParams['toolbar'] = 'None'

    fig = plt.figure("Dome Monitor 9000",figsize=(3,3.5))
    
    ax = plt.subplot(111,projection='polar')

    if dome_status == 1.:
        bars = ax.bar(position/180.*np.pi,1.0,width=slit_size*2.5/180.*np.pi,color="green")
        bars = ax.bar(position/180.*np.pi,1.0,width=slit_size/180.*np.pi,color="lightgreen")
    else:
        bars = ax.bar(position/180.*np.pi,1.0,width=slit_size*2.5/180.*np.pi,color="grey")
        bars = ax.bar(position/180.*np.pi,1.0,width=slit_size/180.*np.pi,color="lightgrey")

    if (scope_az <= position-(slit_size/2.)) or (scope_az >= position+(slit_size/2.)):
        ax.plot(theta,r,linewidth=12,color="red")
        ax.plot(tthe,tr,linewidth=3,linestyle=':',color="red")    
    else:
        ax.plot(theta,r,linewidth=12,color="green")
        ax.plot(tthe,tr,linewidth=3,linestyle='--',color="green")

    ax.set_rmax(1.)
    ax.set_rticks([])
    ax.set_rlabel_position(-22.5)
    ax.grid(True)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    plt.title("Telescope: {:4.2f} Dome: {:4.2f} Active: {:1d}".format(scope_az,position,dome_status),y=-0.2,size=10)

    plt.pause(0.5)
    ax.clear()

