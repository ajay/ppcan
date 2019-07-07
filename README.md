# PPCAN - Python PCAN

## Installation / Dependencies
#### `dbc2json` (from [libcanardbc](https://github.com/Polyconseil/libcanardbc)) deps:
`sudo apt install automake autoconf libtool flex bison libjson-glib-dev`

#### `ppcan` deps:
`python3 -m pip install -r requirements.txt`

## Usage
```
usage: ppcan [-h] -c CAN_CHANNEL -d CAN_DBC

Python PCAN!

optional arguments:
  -h, --help            show this help message and exit

required arguments:
  -c CAN_CHANNEL, --can_channel CAN_CHANNEL
                        Initialized SocketCAN CAN channel (i.e. can0, can1,
                        vcan0, etc...)
  -d CAN_DBC, --can_dbc CAN_DBC
                        CAN DBC file
```
