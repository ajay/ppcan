#!/usr/bin/python3

###############################################################################

import binascii
import curses
import json
import os
import signal
import sys
import threading
import time

import can
import caneton
import colorama

###############################################################################

canData     = {}
canDataLock = threading.Lock()

###############################################################################

class CanMsg:
    def __init__(self, id, data, name=None, signals=[]):
        self.id      = id
        self.data    = data
        self.name    = name
        self.signals = signals
        self.delta   = 0
        self.time    = time.time()
        self.count   = 1

    @staticmethod
    def indexStr() -> str:
        return ('  ID   |               Name               |                Data / Value                |  Count  |     Time      | Delta (ms)\n' +
                '-------|----------------------------------|--------------------------------------------|---------|---------------|-----------')
    def __str__(self):
        dataStr = binascii.hexlify(self.data).decode().upper()
        dataStr = ' '.join(dataStr[i:i+2] for i in range(0, len(dataStr), 2))

        classStr  = '{:6} | {:32} | {:42} | {:7} | {:.2f} | {:8.2f}'.format(hex(self.id), str(self.name) if self.name else '', dataStr, self.count, self.time, self.delta)
        classStr += '\n' + '\n'.join([str(s) for s in self.signals]) + ('\n' if self.signals else '')

        return classStr

    def update(self, data, signals):
        self.data    = data
        self.signals = signals

        currTime     = time.time()
        self.delta   = (currTime - self.time) * 1000 # ms
        self.time    = currTime
        self.count  += 1


class CanSignal:
    def __init__(self, name, value, unit=None, enums=None):
        self.name  = name
        self.value = value
        self.raw   = value
        self.unit  = unit
        self.enums = enums

        self.decodeEnums()

    def __str__(self):
        valueStr = '{:0.2f}'.format(self.value) if isinstance(self.value, float) else str(self.value)

        return ' [sig] | {:32} | {:<33} {:>8} |'.format(self.name, valueStr, self.unit if self.unit else '')

    def decodeEnums(self):
        if self.enums:
            value = str(int(self.value))

            if value in self.enums:
                self.value = self.enums[value]


class CanDbcJson:
    def __init__(self, path):
        self.path = path
        self.data = json.loads(open(self.path).read())

    def msgData(self, msgId : int):
        return self.data['messages'][str(msgId)]

    def signalData(self, msgId : int, signal : str):
        return self.msgData(msgId)['signals'][signal]

    def signalEnums(self, msgId : int, signal : str):
        signalData = self.signalData(msgId, signal)
        return signalData['enums'] if 'enums' in signalData else None

###############################################################################

def receiveCan(canChannel, dbcJsonFile):

    def canetonSignalsToObj(msgId : int, rawSignals : list, dbcJson : CanDbcJson) -> list:
        return [CanSignal(name=s['name'], value=s['value'], unit=s['unit'], enums=dbcJson.signalEnums(msgId=msgId, signal=s['name'])) for s in filter(lambda x: x, rawSignals)]

    bus     = can.interfaces.socketcan.SocketcanBus(channel=canChannel)
    dbcJson = CanDbcJson(path=dbcJsonFile)

    while True:
        msg = bus.recv()

        try:
            decodedMsg = caneton.message_decode(message_id=msg.arbitration_id,
                                                message_length=msg.dlc,
                                                message_data=msg.data,
                                                dbc_json=dbcJson.data)
        except (caneton.exceptions.MessageNotFound, caneton.exceptions.DecodingError):
            decodedMsg = {
                'id'                : msg.arbitration_id,
                'multiplexing_mode' : None,
                'name'              : None,
                'raw_data'          : msg.data,
                'signals'           : [None]
            }

        canDataLock.acquire()

        if msg.arbitration_id not in canData:
            canData[msg.arbitration_id] = CanMsg(id=decodedMsg['id'],
                                                 data=decodedMsg['raw_data'],
                                                 name=decodedMsg['name'],
                                                 signals=canetonSignalsToObj(msgId=decodedMsg['id'], rawSignals=decodedMsg['signals'], dbcJson=dbcJson))
        else:
            canData[msg.arbitration_id].update(data=decodedMsg['raw_data'],
                                               signals=canetonSignalsToObj(msgId=decodedMsg['id'], rawSignals=decodedMsg['signals'], dbcJson=dbcJson))

        canDataLock.release()

###############################################################################

def pcanCursesGui(stdscr):
    badKeys  = [-1, 0, ord('\t'), ord('\r'), ord('\n')]
    titleStr = 'Python PCAN!'

    padY      = 0
    padHeight = 5000

    key  = 0

    stdscr.clear()
    stdscr.refresh()

    curses.halfdelay(1)

    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN,  curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED,   curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)

    while (key != ord('q') and key != 27): # 27 is escape, not defined in curses

        height, width = stdscr.getmaxyx()

        key = stdscr.getch()

        if   key == curses.KEY_DOWN:
            padY += 1
        elif key == curses.KEY_UP:
            padY -= 1
        elif key == curses.KEY_RIGHT or key == curses.KEY_NPAGE or key == ord(' '):
            padY += height
        elif key == curses.KEY_LEFT  or key == curses.KEY_PPAGE:
            padY -= height

        padY = max(0, min(padHeight-height, padY))

        key = ord('0') if key in badKeys else key

        statusbarStr = "Press 'q' to quit | {} / {} | '{}' ({})".format(padY, padHeight, chr(key), key)

        # Top status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(0, 0, titleStr.ljust(width), width)
        stdscr.attroff(curses.color_pair(3))

        stdscr.addstr(2, 0, CanMsg.indexStr())

        # Bottom status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(height-1, 0, statusbarStr.ljust(width-1), width)
        stdscr.attroff(curses.color_pair(3))

        pad = curses.newpad(padHeight, 200)

        canDataLock.acquire()
        pad.addstr(''.join([str(canData[id]) for id in sorted(canData.keys())]))
        canDataLock.release()

        pad.refresh(padY,0, 4,0, height-3,200)
        stdscr.refresh()

###############################################################################

def sigIntHandler(signal, frame):
    print('{}{}\n\nExiting {} ...\n{}'.format(colorama.Fore.BLUE, colorama.Style.BRIGHT, str(__file__), colorama.Style.RESET_ALL))
    exit(0)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Python PCAN')
    parser.add_argument('-c', '--can_channel',  help='SocketCAN can channel',            required=True)
    parser.add_argument('-j', '--can_dbc_json', help='JSON generated from CAN dbc file', required=True)

    args = parser.parse_args()

    signal.signal(signal.SIGINT, sigIntHandler)

    receiveCanThread = threading.Thread(target=receiveCan, daemon=True, args=(args.can_channel, args.can_dbc_json))
    receiveCanThread.start()

    curses.wrapper(pcanCursesGui)


if __name__ =='__main__':
    main()
