# Blaauw Observatory Dome Control

This repository contains the dome control software for the [Blaauw Observatory](https://www.rug.nl/research/kapteyn/sterrenwacht/?lang=en).

## Usage

The control software is split up in multiple scripts:

- `KoepelX.py`: handles commands sent to the dome, i.e. moving it to a certain azimuth.
- `DomeCommanderX.py`: the dome control user interface.
- `domemon9000.py`: draws an interactive plot of the dome and telescope orientation.

To start the dome control software, run the `DOmeStarter2.ps1`. 