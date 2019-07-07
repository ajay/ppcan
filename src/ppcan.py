#!/usr/bin/python3

###############################################################################

import binascii
import curses
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

import can
import caneton
import colorama

###############################################################################

canData     = {}
canDataLock = threading.Lock()
pause       = False

###############################################################################

class CanMsg:
    def __init__(self, id, data, dlc, name=None, signals=[]):
        self.id      = id
        self.name    = name
        self.count   = 0
        self.time    = time.time()

        self.update(data=data, dlc=dlc, signals=signals)

    @staticmethod
    def bytearrayToAscii(data : bytearray, sep='.') -> str:
        return ''.join([chr(b) if 32 < b < 127 else sep for b in data])

    @staticmethod
    def headerStrs() -> str:
        return (['   ID   | L |               Name                 |                Data / Value                |  Ascii   |  Count  |     Time      | Delta (ms)',
                 '--------|---|------------------------------------|--------------------------------------------|----------|---------|---------------|-----------'])

    def __str__(self):
        dataStr = binascii.hexlify(self.data).decode().upper()
        dataStr = ' '.join(dataStr[i:i+2] for i in range(0, len(dataStr), 2))

        classStr  = ' {:6} | {:1} | {:34.34} | {:42} | {:8} | {:7} | {:.2f} | {:8.2f}'.format(hex(self.id), self.dlc, str(self.name) if self.name else '', dataStr, self.ascii, self.count, self.time, self.delta)
        classStr += '\n' + '\n'.join([str(s) for s in self.signals]) + ('\n' if self.signals else '')

        return classStr

    def update(self, data, dlc, signals):
        currTime     = time.time()
        self.delta   = (currTime - self.time) * 1000 # ms
        self.time    = currTime
        self.count  += 1

        self.data    = data
        self.ascii   = self.bytearrayToAscii(self.data)
        self.dlc     = dlc
        self.signals = signals


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

        return ' {:6} | {:1} | ↳ {:32.32} | {:<33.33} {:>8} |'.format('', '', self.name, valueStr, self.unit if self.unit else '')

    def decodeEnums(self):
        if self.enums:
            value = str(int(self.value))

            if value in self.enums:
                self.value = self.enums[value]


class CanDbcJson:
    def __init__(self, dbcPath):
        self.dbcPath = dbcPath

        origCwd = os.getcwd()

        tempUtf8Dbc = tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8')
        tempUtf8Dbc.write(open(self.dbcPath).read())

        tempDbcJson = tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8')
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        subprocess.call(['./dbc2json', tempUtf8Dbc.name, tempDbcJson.name], stdout=open(os.devnull, 'wb'))

        os.chdir(origCwd)

        self.data = json.loads(open(tempDbcJson.name).read())

    def msgData(self, msgId : int):
        return self.data['messages'][str(msgId)]

    def signalData(self, msgId : int, signal : str):
        return self.msgData(msgId)['signals'][signal]

    def signalEnums(self, msgId : int, signal : str):
        signalData = self.signalData(msgId, signal)
        return signalData['enums'] if 'enums' in signalData else None


class GoSequence:
    # def __init__(self, interval, seq=['-', '\\', '|', '/']):
    # def __init__(self, interval, seq=['▖', '▘', '▝', '▗']):
    # def __init__(self, interval, seq=['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█', '▇', '▆', '▅', '▄', '▃', '▁']):
    # def __init__(self, interval, seq=['┤', '┘', '┴', '└', '├', '┌', '┬', '┐']):
    # def __init__(self, interval, seq=['◢', '◣', '◤', '◥']):
    # def __init__(self, interval, seq=['◡◡', '⊙⊙', '◠◠']):
    # def __init__(self, interval, seq=['▉', '▊', '▋', '▌', '▍', '▎', '▏', '▎', '▍', '▌', '▋', '▊', '▉']):
    # def __init__(self, interval, seq=['◴', '◷', '◶', '◵']):
    # def __init__(self, interval, seq=['◐', '◓', '◑', '◒']):
    def __init__(self, interval, seq=['⠁', '⠂', '⠄', '⡀', '⢀', '⠠', '⠐', '⠈']):
        self.interval = interval # ms
        self.seq      = seq
        self.timer    = time.time()
        self.index    = 0

    def get(self):
        currTime = time.time()
        if ((currTime - self.timer) * 1000) > self.interval:
            self.timer = currTime
            self.index = (self.index + 1) % len(self.seq)
        return self.getLast()

    def getLast(self):
        return self.seq[self.index]

###############################################################################

def receiveCan(canChannel, dbcFile):

    def canetonSignalsToObj(msgId : int, rawSignals : list, dbcJson : CanDbcJson) -> list:
        return [CanSignal(name=s['name'], value=s['value'], unit=s['unit'], enums=dbcJson.signalEnums(msgId=msgId, signal=s['name'])) for s in filter(lambda x: x, rawSignals)]

    bus     = can.interfaces.socketcan.SocketcanBus(channel=canChannel)
    dbcJson = CanDbcJson(dbcPath=dbcFile)

    while True:
        if pause:
            continue

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
                                                 dlc=msg.dlc,
                                                 name=decodedMsg['name'],
                                                 signals=canetonSignalsToObj(msgId=decodedMsg['id'], rawSignals=decodedMsg['signals'], dbcJson=dbcJson))
        else:
            canData[msg.arbitration_id].update(data=decodedMsg['raw_data'],
                                               dlc=msg.dlc,
                                               signals=canetonSignalsToObj(msgId=decodedMsg['id'], rawSignals=decodedMsg['signals'], dbcJson=dbcJson))

        canDataLock.release()

###############################################################################

def pcanCursesGui(stdscr):
    global pause

    badKeys      = [-1, 0, ord('\t'), ord('\r'), ord('\n')]
    titleStr     = 'Python PCAN!'
    padHeight    = 5000
    headerStrIdx = 2

    padY  = 0
    key   = 0
    goSeq = GoSequence(interval=100)

    stdscr.clear()
    stdscr.refresh()

    curses.halfdelay(1)

    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN,  curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED,   curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)

    while (key != ord('q')):

        height, width = stdscr.getmaxyx()

        key = stdscr.getch()

        if   key == curses.KEY_RESIZE:
            continue
        elif key == curses.KEY_DOWN:
            padY += 1
        elif key == curses.KEY_UP:
            padY -= 1
        elif key == curses.KEY_RIGHT or key == curses.KEY_NPAGE or key == ord(' '):
            padY += height
        elif key == curses.KEY_LEFT  or key == curses.KEY_PPAGE:
            padY -= height
        elif key == ord('p'):
            pause = True
        elif key == ord('r'):
            pause = False

        padY = max(0, min(padHeight-height, padY))

        key = ord('0') if key in badKeys else key

        statusbarStr = " {} | Press 'q' to quit | {:19} | {} / {} | '{}' ({})".format(goSeq.getLast()       if pause else goSeq.get(),
                                                                                      "Press 'r' to resume" if pause else "Press 'p' to pause",
                                                                                      padY, padHeight,
                                                                                      chr(key), key)

        # Top status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(0, 0, titleStr.ljust(width), width)
        stdscr.attroff(curses.color_pair(3))

        # Header
        for i in range(headerStrIdx, headerStrIdx + len(CanMsg.headerStrs())):
            stdscr.addnstr(i, 0, CanMsg.headerStrs()[i-headerStrIdx], width)

        # Bottom status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(height-1, 0, statusbarStr.ljust(width-1), width)
        stdscr.attroff(curses.color_pair(3))

        pad = curses.newpad(padHeight, 200)

        canDataLock.acquire()
        pad.addstr(''.join([str(canData[id]) for id in sorted(canData.keys())]))
        canDataLock.release()

        pad.refresh(padY,0, 4,0, height-3,width-1)
        stdscr.refresh()

###############################################################################

def sigIntHandler(signal, frame):
    print('{}{}\n\nExiting {} ...\n{}'.format(colorama.Fore.BLUE, colorama.Style.BRIGHT, str(__file__), colorama.Style.RESET_ALL))
    exit(0)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Python PCAN!')
    requiredArgs = parser.add_argument_group('required arguments')
    requiredArgs.add_argument('-c', '--can_channel', help='Initialized SocketCAN CAN channel (i.e. can0, can1, vcan0, etc...)', required=True)
    requiredArgs.add_argument('-d', '--can_dbc',     help='CAN DBC file',                                                       required=True)

    args = parser.parse_args()

    signal.signal(signal.SIGINT, sigIntHandler)

    receiveCanThread = threading.Thread(target=receiveCan, daemon=True, args=(args.can_channel, args.can_dbc))
    receiveCanThread.start()

    curses.wrapper(pcanCursesGui)


if __name__ =='__main__':
    main()
