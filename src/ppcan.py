#!/usr/bin/python3

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


canData     = {}
canDataLock = threading.Lock()


class CanMsg:
    def __init__(self, id, data, name=None, signals=[]):
        self.id      = id
        self.data    = data
        self.name    = name
        self.signals = signals
        self.delta   = 0
        self.time    = time.time()

    @staticmethod
    def indexStr() -> str:
        return ('  ID   |               Name               |           Data / Value           |     Time      | Delta (ms)\n' +
                '-------|----------------------------------|----------------------------------|---------------|-----------')

    def __str__(self):
        dataStr = binascii.hexlify(self.data).decode().upper()
        dataStr = ' '.join(dataStr[i:i+2] for i in range(0, len(dataStr), 2))

        classStr  = '{:6} | {:32} | {:32} | {:.2f} | {:8.2f}'.format(hex(self.id), str(self.name) if self.name else '', dataStr, self.time, self.delta)
        classStr += '\n' + '\n'.join([str(s) for s in self.signals]) + ('\n' if self.signals else '')

        return classStr

    def update(self, data, signals):
        self.data    = data
        self.signals = signals

        currTime     = time.time()
        self.delta   = (currTime - self.time) * 1000 # ms
        self.time    = currTime


class CanSignal:
    def __init__(self, name, value, unit=None):
        self.name  = name
        self.value = value
        self.unit  = unit

    def __str__(self):
        valueStr = '{:0.2f}'.format(self.value) if isinstance(self.value, float) else str(self.value)

        return ' [sig] | {:32} | {:<23} {:>8} |'.format(self.name, valueStr, self.unit if self.unit else '')


def run(stdscr):
    badKeys  = [-1, 0, ord('\t'), ord('\r'), ord('\n')]
    titleStr = 'Python PCAN!'

    padY = 0
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

        padY = max(0, min(2000-height, padY))

        key = ord('0') if key in badKeys else key

        statusbarStr = "Press 'q' to quit | {} / {} | '{}' ({})".format(padY, 2000, chr(key), key)

        # Top status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(0, 0, titleStr.ljust(width), width)
        stdscr.attroff(curses.color_pair(3))

        stdscr.addstr(2, 0, CanMsg.indexStr())

        # Bottom status bar
        stdscr.attron(curses.color_pair(3))
        stdscr.addnstr(height-1, 0, statusbarStr.ljust(width-1), width)
        stdscr.attroff(curses.color_pair(3))

        pad = curses.newpad(2000, 200)

        canDataLock.acquire()
        pad.addstr(''.join([str(canData[id]) for id in sorted(canData.keys())]))
        canDataLock.release()

        pad.refresh(padY,0, 4,0, height-3,200)
        stdscr.refresh()


def receiveCan(canChannel, dbcJson):

    def canetonSignalsToObj(rawSignals : list) -> list:
        return [CanSignal(name=s['name'], value=s['value'], unit=s['unit']) for s in filter(lambda x: x, rawSignals)]

    bus     = can.interfaces.socketcan.SocketcanBus(channel=canChannel)
    dbcJson = json.loads(open(dbcJson).read())

    while True:
        msg = bus.recv()

        try:
            decodedMsg = caneton.message_decode(message_id=msg.arbitration_id,
                                                message_length=msg.dlc,
                                                message_data=msg.data,
                                                dbc_json=dbcJson)
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
                                                 signals=canetonSignalsToObj(decodedMsg['signals']))
        else:
            canData[msg.arbitration_id].update(data=decodedMsg['raw_data'],
                                               signals=canetonSignalsToObj(decodedMsg['signals']))

        canDataLock.release()


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

    curses.wrapper(run)


if __name__ =='__main__':
    main()
