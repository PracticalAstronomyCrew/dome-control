import numpy as np
from socket import socket, AF_INET, SOCK_STREAM


# ------------------------------- #
#            Constants            #
# ------------------------------- #


LAT = 53.240243
LON = 6.53651


# ------------------------------- #
#    Communication w/ KoepelX     #
# ------------------------------- #


def send_command(command):
    """
    Send a command to KoepelX

    Parameters
    ----------
    command (str): the command sent to the dome server
    """
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
    """Returns the dome position (azimuth in deg)"""
    pos = send_command('POSITION')
    angle = float((pos.split(b'\n'))[0])
    
    if angle < 0.: angle = angle + 360.
    if angle > 360.: angle = angle % 360.

    return angle


def is_dome_busy():
    """Return whether the dome is busy (moving)"""
    res = send_command('DOMEBUSY')
    busy = int((res.split(b'\n'))[0])

    return busy


def format_koepel_response(res):
    """
    Properly retrieve & decode the response 
    messages from KoepelX.
    """
    return (res.split(b'\n'))[1].decode("utf-8")


# ------------------------------------------------ #
#   Functions for plotting the telescope & dome    #
# ------------------------------------------------ #


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
    """
    Get the position of the aperture along the RA axis and 
    the pointing direction of the telescope.

    Parameters
    ----------
    ha (float): hour angle in degrees
    dec (float): declination in degrees
    """
    H_01 = transform(0, 0, 0.26)
    H_12 = rot_x(90-LAT) @ rot_z(-ha) @ transform(0, 0, 0.35)
    H_23 = rot_x(dec) @ transform(-0.14, 0, 0)

    H = rot_z(180) @ H_01 @ H_12 @ H_23

    H_unit = transform(0, 1, 0)

    H_diff = H @ H_unit - H

    ap_pos = H @ vec4(0, 0, 0)
    direction = H_diff @ vec4(0, 0, 0)

    return vec3(ap_pos), vec3(direction)


def altitude(ha, dec):
    """
    Returns altitude in radians.

    Parameters
    ----------
    ha (float): hour angle in degrees
    dec (float): declination in degrees
    """
    lat = np.radians(53.24)
    dec = np.radians(dec)
    ha  = np.radians(ha)
    
    sin_a = np.sin(dec)*np.sin(lat) + np.cos(dec)*np.cos(lat)*np.cos(ha)

    return np.arcsin(sin_a)


def polar_to_cart(radius, theta):
    """
    Convert polar to cartesian coordinates,
    since Qt can't draw polar graphs :(

    Parameters
    ----------
    radius (float): the radius of the circle
    theta (float): a particular angle or array of angles

    Return
    ------
    x,y (float, float): the cartesian coordinates
    """
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)

    return x, y


def justify(pos):
    """
    Adjust the polar graph, s.t. 0 deg is north, 
    90 deg is east, 180 south, and 270 west.

    Parameters
    ----------
    pos (float): dome azimuth in degrees

    Returns
    -------
    pos_corrected (float): the adjusted azimuth
    """
    pos = 360 - pos
    pos += 90

    if pos >= 360:
        pos %= 360

    if pos < 0:
        pos += 360

    pos_corrected = (pos + 180) % 360

    return pos_corrected