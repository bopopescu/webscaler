#!/usr/bin/env python
#
# Copyright (C) 2010 John Feuerstein <john@feurix.com>
#
#   Project URL: http://feurix.org/projects/hatop/
#    Mirror URL: http://code.google.com/p/hatop/
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
'''\
HATop is an interactive ncurses client for the HAProxy unix socket
==================================================================

HATop's appearance is similar to top(1). It supports various modes
for detailed statistics of all configured proxies and services in near
realtime. In addition, it features an interactive CLI for the haproxy
unix socket. This allows administrators to control the given haproxy
instance (change server weight, put servers into maintenance mode, ...)
directly out of hatop and monitor the results immediately.

Note: It is important to understand that when multiple haproxy processes
      are started on the same socket, any process may pick up the request
      and thus hatop will output stats owned solely by that process.
      The current haproxy-internal process id is displayed top right.

Display mode reference:

ID  Mode    Description

1   STATUS  The default mode with health, session and queue statistics
2   TRAFFIC Display connection and request rates as well as traffic stats
3   HTTP    Display various statistical information related to HTTP
4   ERRORS  Display health info, various error counters and downtimes
5   CLI     Display embedded command line client for the unix socket

Keybind reference:

Key             Action

Hh?             Display this help screen
CTRL-C / Qq     Quit

TAB             Cycle mode forwards
SHIFT-TAB       Cycle mode backwards
ALT-n / ESC-n   Switch to mode n, where n is the numeric mode id
ESC-ESC         Jump to previous mode

ENTER           Display hotkey menu for selected service
SPACE           Copy and paste selected service identifier to the CLI

You can scroll the stat views using UP / DOWN / PGUP / PGDOWN / HOME / END.

The reverse colored cursor line is used to select a given service instance.

An unique identifier [#<iid>/<#sid>] of the selected service is displayed
bottom right.

You can hit SPACE to copy and paste the identifier in string format
"pxname/svname" to the CLI for easy re-use with some commands.

For example:

1) Open the CLI
2) Type "disable server "
3) Switch back to some stat view using TAB / SHIFT-TAB
4) Select the server instance using UP / DOWN
5) Hit SPACE

The result is this command line:

    > disable server <pxname>/<svname>

Some common administrative actions have hotkeys:

Hotkey      Action

F4          Restore initial server weight

F5          Decrease server weight:     - 10
F6          Decrease server weight:     -  1
F7          Increase server weight:     +  1
F8          Increase server weight:     + 10

F9          Enable server (return from maintenance mode)
F10         Disable server (put into maintenance mode)

Hotkey actions and server responses are logged on the CLI viewport.
You can scroll the output on the CLI view using PGUP / PGDOWN.
A brief keybind reference is logged there directly after startup...


Header reference:

Node        configured name of the haproxy node
Uptime      runtime since haproxy was initially started
Pipes       pipes are currently used for kernel-based tcp slicing
Procs       number of haproxy processes
Tasks       number of actice process tasks
Queue       number of queued process tasks (run queue)
Proxies     number of configured proxies
Services    number of configured services

In multiple modes:

NAME        name of the proxy and his services
W           configured weight of the service
STATUS      service status (UP/DOWN/NOLB/MAINT/MAINT(via)...)
CHECK       status of last health check (see status reference below)

In STATUS mode:

ACT         server is active (server), number of active servers (backend)
BCK         server is backup (server), number of backup servers (backend)
QCUR        current queued requests
QMAX        max queued requests
SCUR        current sessions
SMAX        max sessions
SLIM        sessions limit
STOT        total sessions

In TRAFFIC mode:

LBTOT       total number of times a server was selected
RATE        number of sessions per second over last elapsed second
RLIM        limit on new sessions per second
RMAX        max number of new sessions per second
BIN         bytes in (IEEE 1541-2002)
BOUT        bytes out (IEEE 1541-2002)

In HTTP mode:

RATE        HTTP requests per second over last elapsed second
RMAX        max number of HTTP requests per second observed
RTOT        total number of HTTP requests received
1xx         number of HTTP responses with 1xx code
2xx         number of HTTP responses with 2xx code
3xx         number of HTTP responses with 3xx code
4xx         number of HTTP responses with 4xx code
5xx         number of HTTP responses with 5xx code
?xx         number of HTTP responses with other codes (protocol error)

In ERRORS mode:

CF          number of failed checks
CD          number of UP->DOWN transitions
CL          last status change
ECONN       connection errors
EREQ        request errors
ERSP        response errors
DREQ        denied requests
DRSP        denied responses
DOWN        total downtime

Health check status reference:

UNK         unknown
INI         initializing
SOCKERR     socket error
L4OK        check passed on layer 4, no upper layers testing enabled
L4TMOUT     layer 1-4 timeout
L4CON       layer 1-4 connection problem, for example
            "Connection refused" (tcp rst) or "No route to host" (icmp)
L6OK        check passed on layer 6
L6TOUT      layer 6 (SSL) timeout
L6RSP       layer 6 invalid response - protocol error
L7OK        check passed on layer 7
L7OKC       check conditionally passed on layer 7, for example 404 with
            disable-on-404
L7TOUT      layer 7 (HTTP/SMTP) timeout
L7RSP       layer 7 invalid response - protocol error
L7STS       layer 7 response error, for example HTTP 5xx
'''
__author__    = 'John Feuerstein <john@feurix.com>'
__copyright__ = 'Copyright (C) 2010 %s' % __author__
__license__   = 'GNU GPLv3'
__version__   = '0.7.7'

import fcntl
import os
import re   
import signal
import socket
import struct
import sys
import time
import tty

import curses
import curses.ascii

from socket import error as SocketError
from _curses import error as CursesError

from collections import deque
from textwrap import TextWrapper

# ------------------------------------------------------------------------- #
#                               GLOBALS                                     #
# ------------------------------------------------------------------------- #

# Settings of interactive command session over the unix-socket
HAPROXY_CLI_BUFSIZE = 4096
HAPROXY_CLI_TIMEOUT = 60
HAPROXY_CLI_PROMPT = '> '
HAPROXY_CLI_CMD_SEP = ';'
HAPROXY_CLI_CMD_TIMEOUT = 1
HAPROXY_CLI_MAXLINES = 1000

# Settings of the embedded CLI
CLI_MAXLINES = 1000
CLI_MAXHIST = 100
CLI_INPUT_LIMIT = 200
CLI_INPUT_RE = re.compile('[a-zA-Z0-9_:\.\-\+; /#%]')
CLI_INPUT_DENY_CMD = ['prompt', 'set timeout cli', 'quit']

# Note: Only the last 3 lines are visible instantly on 80x25
CLI_HELP_TEXT = '''\
             Welcome on the embedded interactive HAProxy shell!

                  Type `help' to get a command reference
'''

# Screen setup
SCREEN_XMIN = 78
SCREEN_YMIN = 20
SCREEN_XMAX = 200
SCREEN_YMAX = 100
SCREEN_HPOS = 11

HAPROXY_INFO_RE = {
'software_name':    re.compile('^Name:\s*(?P<value>\S+)'),
'software_version': re.compile('^Version:\s*(?P<value>\S+)'),
'software_release': re.compile('^Release_date:\s*(?P<value>\S+)'),
'nproc':            re.compile('^Nbproc:\s*(?P<value>\d+)'),
'procn':            re.compile('^Process_num:\s*(?P<value>\d+)'),
'pid':              re.compile('^Pid:\s*(?P<value>\d+)'),
'uptime':           re.compile('^Uptime:\s*(?P<value>[\S ]+)$'),
'maxconn':          re.compile('^Maxconn:\s*(?P<value>\d+)'),
'curconn':          re.compile('^CurrConns:\s*(?P<value>\d+)'),
'maxpipes':         re.compile('^Maxpipes:\s*(?P<value>\d+)'),
'curpipes':         re.compile('^PipesUsed:\s*(?P<value>\d+)'),
'tasks':            re.compile('^Tasks:\s*(?P<value>\d+)'),
'runqueue':         re.compile('^Run_queue:\s*(?P<value>\d+)'),
'node':             re.compile('^node:\s*(?P<value>\S+)'),
}

HAPROXY_STAT_MAX_SERVICES = 100
HAPROXY_STAT_LIMIT_WARNING = '''\
Warning: You have reached the stat parser limit! (%d)
Use --filter to parse specific service stats only.
''' % HAPROXY_STAT_MAX_SERVICES
HAPROXY_STAT_FILTER_RE = re.compile(
        '^(?P<iid>-?\d+)\s+(?P<type>-?\d+)\s+(?P<sid>-?\d+)$')
HAPROXY_STAT_PROXY_FILTER_RE = re.compile(
        '^(?P<pxname>[a-zA-Z0-9_:\.\-]+)$')
HAPROXY_STAT_COMMENT = '#'
HAPROXY_STAT_SEP = ','
HAPROXY_STAT_CSV = [
# Note: Fields must be listed in correct order, as described in:
# http://haproxy.1wt.eu/download/1.4/doc/configuration.txt [9.1]

# TYPE  FIELD

(str,   'pxname'),          # proxy name
(str,   'svname'),          # service name (FRONTEND / BACKEND / name)
(int,   'qcur'),            # current queued requests
(int,   'qmax'),            # max queued requests
(int,   'scur'),            # current sessions
(int,   'smax'),            # max sessions
(int,   'slim'),            # sessions limit
(int,   'stot'),            # total sessions
(int,   'bin'),             # bytes in
(int,   'bout'),            # bytes out
(int,   'dreq'),            # denied requests
(int,   'dresp'),           # denied responses
(int,   'ereq'),            # request errors
(int,   'econ'),            # connection errors
(int,   'eresp'),           # response errors (among which srv_abrt)
(int,   'wretr'),           # retries (warning)
(int,   'wredis'),          # redispatches (warning)
(str,   'status'),          # status (UP/DOWN/NOLB/MAINT/MAINT(via)...)
(int,   'weight'),          # server weight (server), total weight (backend)
(int,   'act'),             # server is active (server),
                            # number of active servers (backend)
(int,   'bck'),             # server is backup (server),
                            # number of backup servers (backend)
(int,   'chkfail'),         # number of failed checks
(int,   'chkdown'),         # number of UP->DOWN transitions
(int,   'lastchg'),         # last status change (in seconds)
(int,   'downtime'),        # total downtime (in seconds)
(int,   'qlimit'),          # queue limit
(int,   'pid'),             # process id
(int,   'iid'),             # unique proxy id
(int,   'sid'),             # service id (unique inside a proxy)
(int,   'throttle'),        # warm up status
(int,   'lbtot'),           # total number of times a server was selected
(str,   'tracked'),         # id of proxy/server if tracking is enabled
(int,   'type'),            # (0=frontend, 1=backend, 2=server, 3=socket)
(int,   'rate'),            # number of sessions per second
                            # over the last elapsed second
(int,   'rate_lim'),        # limit on new sessions per second
(int,   'rate_max'),        # max number of new sessions per second
(str,   'check_status'),    # status of last health check
(int,   'check_code'),      # layer5-7 code, if available
(int,   'check_duration'),  # time in ms took to finish last health check
(int,   'hrsp_1xx'),        # http responses with 1xx code
(int,   'hrsp_2xx'),        # http responses with 2xx code
(int,   'hrsp_3xx'),        # http responses with 3xx code
(int,   'hrsp_4xx'),        # http responses with 4xx code
(int,   'hrsp_5xx'),        # http responses with 5xx code
(int,   'hrsp_other'),      # http responses with other codes (protocol error)
(str,   'hanafail'),        # failed health checks details
(int,   'req_rate'),        # HTTP requests per second
(int,   'req_rate_max'),    # max number of HTTP requests per second
(int,   'req_tot'),         # total number of HTTP requests received
(int,   'cli_abrt'),        # number of data transfers aborted by client
(int,   'srv_abrt'),        # number of data transfers aborted by server
]
HAPROXY_STAT_NUMFIELDS = len(HAPROXY_STAT_CSV)
HAPROXY_STAT_CSV = [(k, v) for k, v in enumerate(HAPROXY_STAT_CSV)]

# All big numeric values on the screen are prefixed using the metric prefix
# set, while everything byte related is prefixed using binary prefixes.
# Note: If a non-byte numeric value fits into the field, we skip prefixing.
PREFIX_BINARY = {
        1024:    'K',
        1024**2: 'M',
}
PREFIX_METRIC = {
        1000:    'k',
        1000**2: 'M',
        1000**3: 'G',
}
PREFIX_TIME = {
        60:      'm',
        60*60:   'h',
        60*60*24:'d',
}

# ------------------------------------------------------------------------- #
#                           CLASS DEFINITIONS                               #
# ------------------------------------------------------------------------- #

# Use bounded length deque if available (Python 2.6+)
try:
    deque(maxlen=0)

    class RingBuffer(deque):

        def __init__(self, maxlen):
            assert maxlen > 0
            deque.__init__(self, maxlen=maxlen)

except TypeError:

    class RingBuffer(deque):

        def __init__(self, maxlen):
            assert maxlen > 0
            deque.__init__(self)
            self.maxlen = maxlen

        def append(self, item):
            if len(self) == self.maxlen:
                self.popleft()
            deque.append(self, item)

        def appendleft(self, item):
            if len(self) == self.maxlen:
                self.popright()
            deque.appendleft(self, item)

        def extend(self, iterable):
            for item in iterable:
                self.append(item)

        def extendleft(self, iterable):
            for item in iterable:
                self.appendleft(item)


class Socket:

    def __init__(self, path, readonly=False):
        self.path = path
        self.ro = readonly
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def _recv(self):
        # socket.recv() wrapper raising SocketError if we receive
        # EOF before seeing the interactive socket prompt.
        data = self._socket.recv(HAPROXY_CLI_BUFSIZE)
        if not data:
            raise SocketError('error while waiting for prompt')
        return data

    def connect(self):
        # Initialize socket connection
        self._socket.connect(self.path)
        self._socket.settimeout(HAPROXY_CLI_CMD_TIMEOUT)

        # Enter the interactive socket mode. This requires HAProxy 1.4+ and
        # allows us to error out early if connected to an older version.
        try:
            self.send('prompt')
            self.wait()
            self.send('set timeout cli %d' % HAPROXY_CLI_TIMEOUT)
            self.wait()
        except SocketError:
            raise SocketError('error while initializing interactive mode')

    def close(self):
        try:
            self.send('quit')
        except:
            pass
        try:
            self._socket.close()
        except:
            pass

    def send(self, cmdline):
        self._socket.sendall('%s\n' % cmdline)

    def wait(self):
        # Wait for the prompt and discard data.
        rbuf = ''
        while not rbuf.endswith(HAPROXY_CLI_PROMPT):
            data = self._recv()
            rbuf = rbuf[-(len(HAPROXY_CLI_PROMPT)-1):] + data

    def recv(self):
        # Receive lines until HAPROXY_CLI_MAXLINES or the prompt is reached.
        # If the prompt was still not found, discard data and wait for it.
        linecount = 0
        rbuf = ''
        while not rbuf.endswith(HAPROXY_CLI_PROMPT):

            if linecount == HAPROXY_CLI_MAXLINES:
                data = self._recv()
                rbuf = rbuf[-(len(HAPROXY_CLI_PROMPT)-1):] + data
                continue

            data = self._recv()
            rbuf += data

            while linecount < HAPROXY_CLI_MAXLINES and '\n' in rbuf:
                line, rbuf = rbuf.split('\n', 1)
                linecount += 1
                yield line


class SocketData:

    def __init__(self, socket):
        self.socket = socket
        self.pxcount = 0
        self.svcount = 0
        self.info = {}
        self.stat = {}
        self._filters = set()

    def register_stat_filter(self, stat_filter):

        # Validate and register filters
        stat_filter_set = set(stat_filter)
        for filter in stat_filter_set:
            match = HAPROXY_STAT_FILTER_RE.match(filter)
            if not match:
                raise ValueError('invalid stat filter: %s' % filter)
            self._filters.add((
                    int(match.group('iid'), 10),
                    int(match.group('type'), 10),
                    int(match.group('sid'), 10),
            ))

    def register_proxy_filter(self, proxy_filter):

        # Validate filters
        proxy_filter_set = set(proxy_filter)
        for filter in proxy_filter_set:
            if not HAPROXY_STAT_PROXY_FILTER_RE.match(filter):
                raise ValueError('invalid proxy filter: %s' % filter)

        # Convert proxy filters into more efficient stat filters
        self.socket.send('show stat')
        pxstat, pxcount, svcount = parse_stat(self.socket.recv())

        proxy_iid_map = {} # {pxname: iid, ...}

        for pxname in proxy_filter_set:
            for iid in pxstat:
                for sid in pxstat[iid]:
                    if pxstat[iid][sid]['pxname'] == pxname:
                        proxy_iid_map[pxname] = iid
                    break
                if pxname in proxy_iid_map:
                    break

        for pxname in proxy_filter_set:
            if not pxname in proxy_iid_map:
                raise RuntimeError('proxy not found: %s' % pxname)

        # Register filters
        for iid in proxy_iid_map.itervalues():
            self._filters.add((iid, -1, -1))

    def update_info(self):
        self.socket.send('show info')
        iterable = self.socket.recv()
        self.info = parse_info(iterable)

    def update_stat(self):
        # Store current data
        pxcount_old = self.pxcount
        svcount_old = self.svcount
        stat_old = self.stat

        # Reset current data
        self.pxcount = 0
        self.svcount = 0
        self.stat = {}

        if self._filters:
            for filter in self._filters:
                self.socket.send('show stat %d %d %d' % filter)
                filter_stat, filter_pxcount, filter_svcount = \
                        parse_stat(self.socket.recv())

                if filter_pxcount == 0:
                    raise RuntimeError('stale stat filter: %d %d %d' % filter)

                self.pxcount += filter_pxcount
                self.svcount += filter_svcount
                self.stat.update(filter_stat)
        else:
            self.socket.send('show stat')
            self.stat, self.pxcount, self.svcount = \
                    parse_stat(self.socket.recv())

        if self.pxcount == 0:
            raise RuntimeWarning('no stat data available')

        # Warn if the HAProxy configuration has changed on-the-fly
        pxdiff = 0
        svdiff = 0

        if self.pxcount < pxcount_old:
            pxdiff -= pxcount_old - self.pxcount
        if pxcount_old > 0 and self.pxcount > pxcount_old:
            pxdiff += self.pxcount - pxcount_old
        if self.svcount < svcount_old:
            svdiff -= svcount_old - self.svcount
        if svcount_old > 0 and self.svcount > svcount_old:
            svdiff += self.svcount - svcount_old

        if pxdiff != 0 or svdiff != 0:
            raise RuntimeWarning(
                    'config changed: proxy %+d, service %+d '
                    '(reloading...)' % (pxdiff, svdiff))


class ScreenCLI:

    def __init__(self, screen):
        self.screen = screen

        # Output
        self.obuf = RingBuffer(CLI_MAXLINES)
        self.ypos = 0
        self.wrapper = TextWrapper()
        self.screenlines = []

        # Input
        self.ihist = RingBuffer(CLI_MAXHIST)
        self.ibuf = []
        self.ibpos = 0
        self.ibmin = 0


    # INPUT
    @property
    def imin(self):
        return self.screen.xmin + 2

    @property
    def imax(self):
        return self.screen.xmax - 4

    @property
    def ispan(self):
        return self.imax - self.imin

    @property
    def ipos(self):
        return self.ibpos - self.ibmin

    @property
    def ibmax(self):
        return self.ibmin + self.ispan

    @property
    def iblen(self):
        return len(self.ibuf)

    @property
    def cmdline(self):
        return ''.join(self.ibuf)

    # OUTPUT
    @property
    def ospan(self):
        return self.screen.span - 1


    def setup(self):
        self.ipad = curses.newpad(1, SCREEN_XMAX)               # input
        self.opad = curses.newpad(SCREEN_YMAX, SCREEN_XMAX)     # output

        # Display initial help text...
        self.obuf.extend(CLI_HELP_TEXT.split('\n'))
        self.update_screenlines()

    def start(self):
        try:
            curses.curs_set(1)
        except CursesError:
            pass
        self.draw_output()
        self.draw_input()

    def stop(self):
        try:
            curses.curs_set(0)
        except CursesError:
            pass

    def update_screenlines(self):
        self.wrapper.width = self.screen.xmax
        self.screenlines = []
        for line in self.obuf:
            if len(line) > self.wrapper.width:
                self.screenlines.extend(self.wrapper.wrap(line))
            else:
                self.screenlines.append(line)
        self.ypos = len(self.screenlines)

    def reset_input(self):
        self.ibuf = []
        self.ibpos = 0
        self.ibmin = 0

    def refresh_input(self, sync=False):
        if sync:
            refresh = self.ipad.refresh
        else:
            refresh = self.ipad.noutrefresh

        refresh(0, 0,
                self.screen.smax, self.screen.xmin,
                self.screen.smax, self.screen.xmax - 1)

    def refresh_output(self, sync=False):
        if sync:
            refresh = self.opad.refresh
        else:
            refresh = self.opad.noutrefresh

        refresh(0, 0,
                self.screen.smin, self.screen.xmin,
                self.screen.smax - 2, self.screen.xmax - 1)

    def draw_input(self):
        self.ipad.clear()
        self.ipad.addstr(0, 0, '> ', curses.A_BOLD)
        self.ipad.addstr(0, 2, ''.join(self.ibuf[self.ibmin:self.ibmax]))

        # Mark input lines longer than the visible input span
        if self.ibmin > 0:
            self.ipad.addstr(0, self.imin - 1, '<')
        if self.iblen > self.ibmax:
            self.ipad.addstr(0, self.imax, '>')

        self.ipad.move(0, self.imin + self.ipos)

    def draw_output(self):
        self.opad.clear()
        vmin = max(0, self.ypos - self.ospan)
        vmax = vmin + self.ospan
        lines = self.screenlines[vmin:vmax]
        self.opad.addstr(0, 0, '\n'.join(lines))

    # INPUT
    def prev(self):
        if len(self.ihist) == 0:
            return
        if len(self.ibuf) == 0:
            self.ibuf = list(self.ihist[-1])
            self.mvend()
            return
        if self.ibuf != self.ihist[-1]:
            self.ihist.append(self.ibuf)
        self.ihist.rotate(1)
        self.ibuf = list(self.ihist[-1])
        self.mvend()

    def next(self):
        if len(self.ihist) == 0:
            return
        self.ihist.rotate(-1)
        self.ibuf = list(self.ihist[-1])
        self.mvend()

    def puts(self, s):
        s = list(s)
        if len(self.ibuf) + len(s) >= CLI_INPUT_LIMIT:
            return
        for c in s:
            if not CLI_INPUT_RE.match(c):
                return

        if self.ibpos < self.iblen:
            self.ibuf = self.ibuf[:self.ibpos] + s + self.ibuf[self.ibpos:]
        else:
            self.ibuf.extend(s)

        self.mvc(len(s))
        return True

    def putc(self, c):
        if len(self.ibuf) == CLI_INPUT_LIMIT:
            return
        if not CLI_INPUT_RE.match(c):
            return

        if self.ibpos < self.iblen:
            self.ibuf.insert(self.ibpos, c)
        else:
            self.ibuf.append(c)

        self.mvc(1)

    def delc(self, n):
        if n == 0 or self.iblen == 0:
            return

        # Delete LEFT
        elif n < 0 and self.ibpos >= 1:
            self.ibuf.pop(self.ibpos - 1)
            self.mvc(-1)

        # Delete RIGHT
        elif n > 0 and self.ibpos < self.iblen:
            self.ibuf.pop(self.ibpos)
            self.draw_input()
            self.refresh_input(sync=True)

    def mvhome(self):
        self.ibmin = 0
        self.ibpos = 0
        self.draw_input()
        self.refresh_input(sync=True)

    def mvend(self):
        self.ibmin = max(0, self.iblen - self.ispan)
        self.ibpos = self.iblen
        self.draw_input()
        self.refresh_input(sync=True)

    def mvc(self, n):
        if n == 0:
            return

        # Move LEFT
        if n < 0:
            self.ibpos = max(0, self.ibpos + n)
            if self.ibpos < self.ibmin:
                self.ibmin = self.ibpos

        # Move RIGHT
        elif n > 0:
            self.ibpos = min(self.iblen, self.ibpos + n)
            if self.ibpos > self.ibmax:
                self.ibmin += n

        self.draw_input()
        self.refresh_input(sync=True)

    # OUTPUT
    def mvo(self, n):
        if n == 0:
            return

        # Move UP
        if n < 0 and self.ypos > self.ospan:
            self.ypos = max(self.ospan, self.ypos + n)

        # Move DOWN
        elif n > 0 and self.ypos < len(self.screenlines):
            self.ypos = min(len(self.screenlines), self.ypos + n)

        self.draw_output()
        self.refresh_output(sync=True)

    def execute(self):

        # Nothing to do... print marker line instead.
        if self.iblen == 0:
            self.obuf.append('- %s %s' % (time.ctime(), '-' * 50))
            self.obuf.append('')
            self.update_screenlines()
            self.draw_output()
            self.refresh_output(sync=True)
            self.refresh_input(sync=True)
            return

        # Validate each command on the command line
        cmds = [cmd.strip() for cmd in
                self.cmdline.split(HAPROXY_CLI_CMD_SEP)]

        for pattern in CLI_INPUT_DENY_CMD:
            for cmd in cmds:
                if re.match(r'^\s*%s(?:\s|$)' % pattern, cmd):
                    self.obuf.append('* command not allowed: %s' % cmd)
                    self.obuf.append('')
                    self.update_screenlines()
                    self.draw_output()
                    self.refresh_output(sync=True)
                    self.refresh_input(sync=True)
                    return

        self.execute_cmdline(self.cmdline)

        self.draw_output()
        self.refresh_output(sync=True)

        self.ihist.append(self.ibuf)
        self.reset_input()
        self.draw_input()
        self.refresh_input(sync=True)

    def execute_cmdline(self, cmdline):
        self.obuf.append('* %s' % time.ctime())
        self.obuf.append('> %s' % cmdline)
        self.screen.data.socket.send(cmdline)
        self.obuf.extend(self.screen.data.socket.recv())
        self.update_screenlines()


class Screen:

    def __init__(self, data, mid=1):
        self.data = data
        self.modes = SCREEN_MODES
        self.sb_conn = StatusBar()
        self.sb_pipe = StatusBar()
        self.lines = []
        self.screen = None
        self.xmin = 0
        self.xmax = SCREEN_XMIN
        self.ymin = 0
        self.ymax = SCREEN_YMIN
        self.vmin = 0
        self.cmin = 0
        self.cpos = 0
        self.hpos = SCREEN_HPOS
        self.help = ScreenHelp(self)
        self.cli = ScreenCLI(self)

        self._pmid = mid # previous mode id
        self._cmid = mid # current mode id
        self._mode = self.modes[mid]

        # Display state
        self.active = False

        # Assume a dumb TTY, setup() will detect smart features.
        self.dumbtty = True

        # Toggled by the SIGWINCH handler...
        # Note: Defaults to true to force the initial size sync.
        self._resized = True

        # Display given exceptions on screen
        self.exceptions = []

        # Show cursor line?
        self.cursor = True

        # Show hotkeys?
        self.hotkeys = False

    def _sigwinchhandler(self, signum, frame):
        self._resized = True

    @property
    def resized(self):
        if self.dumbtty:
            ymax, xmax = self.getmaxyx()
            return ymax != self.ymax or xmax != self.xmax
        else:
            return self._resized

    @property
    def mid(self):
        return self._cmid

    @property
    def mode(self):
        return self._mode

    @property
    def ncols(self):
        return self.xmax - self.xmin

    @property
    def smin(self):
        return self.hpos + 2

    @property
    def smax(self):
        return self.ymax - 3

    @property
    def span(self):
        return self.smax - self.smin

    @property
    def cmax(self):
        return min(self.span, len(self.lines) - 1)

    @property
    def cstat(self):
        return self.lines[self.vpos].stat

    @property
    def vpos(self):
        return self.vmin + self.cpos

    @property
    def vmax(self):
        return min(self.vmin + self.span, len(self.lines) - 1)

    @property
    def screenlines(self):
        return enumerate(self.lines[self.vmin:self.vmax + 1])

    # Proxies
    def getch(self, *args, **kwargs):
        return self.screen.getch(*args, **kwargs)
    def hline(self, *args, **kwargs):
        return self.screen.hline(*args, **kwargs)
    def addstr(self, *args, **kwargs):
        return self.screen.addstr(*args, **kwargs)

    def setup(self):
        self.screen = curses_init()
        self.screen.keypad(1)
        self.screen.nodelay(1)
        self.screen.idlok(1)
        self.screen.move(0, 0)
        curses.def_prog_mode()
        self.help.setup()
        self.cli.setup()

        # Register some terminal resizing magic if supported...
        if hasattr(curses, 'resize_term') and hasattr(signal, 'SIGWINCH'):
            self.dumbtty = False
            signal.signal(signal.SIGWINCH, self._sigwinchhandler)

        # If we came this far the display is active
        self.active = True

    def getmaxyx(self):
        ymax, xmax = self.screen.getmaxyx()
        xmax = min(xmax, SCREEN_XMAX)
        ymax = min(ymax, SCREEN_YMAX)
        return ymax, xmax

    def resize(self):
        if not self.dumbtty:
            self.clear()
            size = fcntl.ioctl(0, tty.TIOCGWINSZ, '12345678')
            size = struct.unpack('4H', size)
            curses.resize_term(size[0], size[1])

        ymax, xmax = self.getmaxyx()

        if xmax < SCREEN_XMIN or ymax < SCREEN_YMIN:
            raise RuntimeError(
                    'screen too small, need at least %dx%d'
                    % (SCREEN_XMIN, SCREEN_YMIN))
        if ymax == self.ymax and xmax == self.xmax:
            self._resized = False
            return
        if xmax != self.xmax:
            self.xmax = xmax
        if ymax != self.ymax:
            self.ymax = ymax

        self.mode.sync(self)

        # Force re-wrapping of the screenlines in CLI mode
        if self.mid == 5:
            self.cli.update_screenlines()
            self.cli.draw_output()

        self._resized = False

    def reset(self):
        if not self.active:
            return
        curses_reset(self.screen)

    def recover(self):
        curses.reset_prog_mode()

    def refresh(self):
        self.screen.noutrefresh()

        if self.mid == 0:
            self.help.refresh()
        elif self.mid == 5:
            self.cli.refresh_output()
            self.cli.refresh_input()

        curses.doupdate()

    def clear(self):
        # Note: Forces the whole screen to be repainted upon refresh()
        self.screen.clear()

    def erase(self):
        self.screen.erase()

    def switch_mode(self, mid):
        if mid == 5 and self.data.socket.ro:
            return # noop

        mode = self.modes[mid]
        mode.sync(self)

        if self.mid != 5 and mid == 5:
            self.cli.start()
        elif self.mid == 5 and mid != 5:
            self.cli.stop()

        self._pmid = self._cmid
        self._cmid, self._mode = mid, mode

    def toggle_mode(self):
        if self._pmid == self._cmid:
            return
        self.switch_mode(self._pmid)

    def cycle_mode(self, n):
        if n == 0:
            return

        if self.data.socket.ro:
            border = 4
        else:
            border = 5

        if self._cmid == 0:
            self.switch_mode(1)
        elif n < 0 and self._cmid == 1:
            self.switch_mode(border)
        elif n > 0 and self._cmid == border:
            self.switch_mode(1)
        else:
            self.switch_mode(self._cmid + n)

    def update_data(self):
        self.data.update_info()
        try:
            self.data.update_stat()
        except RuntimeWarning, x:
            self.exceptions.append(x)

    def update_bars(self):
        self.sb_conn.update_max(int(self.data.info['maxconn'], 10))
        self.sb_conn.update_cur(int(self.data.info['curconn'], 10))
        self.sb_pipe.update_max(int(self.data.info['maxpipes'], 10))
        self.sb_pipe.update_cur(int(self.data.info['curpipes'], 10))

    def update_lines(self):
        # Display non-fatal exceptions on screen
        if self.exceptions:
            self.mvhome()
            self.lines = []
            self.cursor = False
            for x in self.exceptions:
                for line in str(x).splitlines():
                    line = line.center(SCREEN_XMIN)
                    self.lines.append(ScreenLine(text=line))
            self.exceptions = []
            return

        # Reset cursor visibility
        if not self.cursor:
            self.cursor = True

        # Update screen lines
        self.lines = get_screenlines(self.data.stat)
        if self.data.svcount >= HAPROXY_STAT_MAX_SERVICES:
            self.lines.append(ScreenLine())
            for line in HAPROXY_STAT_LIMIT_WARNING.splitlines():
                self.lines.append(ScreenLine(text=line))

    def draw_line(self, ypos, xpos=0, text=None,
            attr=curses.A_REVERSE):
        self.hline(ypos, self.xmin, ' ', self.xmax, attr)
        if text:
            self.addstr(ypos, self.xmin + xpos, text, attr)

    def draw_head(self):
        self.draw_line(self.ymin)
        attr = curses.A_REVERSE | curses.A_BOLD
        self.addstr(self.ymin, self.xmin,
                time.ctime().rjust(self.xmax - 1), attr)
        self.addstr(self.ymin, self.xmin + 1,
                'HATop version ' + __version__, attr)

    def draw_info(self):
        self.addstr(self.ymin + 2, self.xmin + 2,
                '%s Version: %s  (released: %s)' % (
                    self.data.info['software_name'],
                    self.data.info['software_version'],
                    self.data.info['software_release'],
                ), curses.A_BOLD)
        self.addstr(self.ymin + 2, self.xmin + 56,
                'PID: %d (proc %d)' % (
                    int(self.data.info['pid'], 10),
                    int(self.data.info['procn'], 10),
                ), curses.A_BOLD)
        self.addstr(self.ymin + 4, self.xmin + 2,
                '       Node: %s (uptime %s)' % (
                    self.data.info['node'] or 'unknown',
                    self.data.info['uptime'],
                ))
        self.addstr(self.ymin + 6, self.xmin + 2,
                '      Pipes: %s'  % self.sb_pipe)
        self.addstr(self.ymin + 7, self.xmin + 2,
                'Connections: %s'  % self.sb_conn)
        self.addstr(self.ymin + 9, self.xmin + 2,
                'Procs: %3d   Tasks: %5d    Queue: %5d    '
                'Proxies: %3d   Services: %4d' % (
                    int(self.data.info['nproc'], 10),
                    int(self.data.info['tasks'], 10),
                    int(self.data.info['runqueue'], 10),
                    self.data.pxcount,
                    self.data.svcount,
                ))

    def draw_cols(self):
        self.draw_line(self.hpos, text=self.mode.head,
                attr=curses.A_REVERSE | curses.A_BOLD)

    def draw_foot(self):
        xpos = self.xmin
        ypos = self.ymax - 1
        self.draw_line(ypos)
        attr_active = curses.A_BOLD
        attr_inactive = curses.A_BOLD | curses.A_REVERSE

        # HOTKEYS
        if (self.hotkeys and
                0 < self.mid < 5 and
                self.cstat and
                self.cstat['iid'] > 0 and
                self.cstat['sid'] > 0):
                self.draw_line(ypos)
                self.addstr(ypos, 1, 'HOTKEYS:',
                        curses.A_BOLD | curses.A_REVERSE)
                self.addstr(ypos, 11,
                        'F4=W-RESET  '
                        'F5=W-10  F6=W-1  F7=W+1  F8=W+10  '
                        'F9=ENABLE  F10=DISABLE',
                        curses.A_NORMAL | curses.A_REVERSE)
                return

        # VIEWPORTS
        for mid, mode in enumerate(self.modes):
            if mid == 0:
                continue
            if mid == 5 and self.data.socket.ro:
                continue
            if mid == self.mid:
                attr = attr_active
            else:
                attr = attr_inactive

            s = ' %d-%s ' % (mid, mode.name)
            self.addstr(ypos, xpos, s, attr)
            xpos += len(s)

        if 0 < self.mid < 5 and self.cstat:
            if self.cstat['iid'] > 0 and self.cstat['sid'] > 0:
                if self.data.socket.ro:
                    s = 'READ-ONLY [#%d/#%d]' % (
                            self.cstat['iid'], self.cstat['sid'])
                else:
                    s = 'ENTER=MENU SPACE=SEL [#%d/#%d]' % (
                            self.cstat['iid'], self.cstat['sid'])
            else:
                if self.data.socket.ro:
                    s = 'READ-ONLY [#%d/#%d]' % (
                            self.cstat['iid'], self.cstat['sid'])
                else:
                    s = '[#%d/#%d]' % (
                            self.cstat['iid'], self.cstat['sid'])
        elif self.mid == 5:
            s = 'PGUP/PGDOWN=SCROLL'
        else:
            s = 'UP/DOWN=SCROLL H=HELP Q=QUIT'
        self.addstr(ypos, self.xmax - len(s) - 1, s, attr_inactive)

    def draw_stat(self):
        for idx, line in self.screenlines:
            if self.cursor and idx == self.cpos:
                attr = line.attr | curses.A_REVERSE
            else:
                attr = line.attr
            if not line.stat:
                screenline = get_cell(self.xmax, 'L', line.text)
            elif 'message' in line.stat:
                screenline = get_cell(self.xmax, 'L', line.stat['message'])
            else:
                screenline = get_screenline(self.mode, line.stat)
            self.addstr(self.smin + idx, self.xmin, screenline, attr)

    def draw_mode(self):
        if self.mid == 0:
            self.help.draw()
        elif self.mid == 5 and self._pmid == self._cmid:
            self.cli.start() # initial mid was 5
        elif 0 < self.mid < 5:
            self.draw_stat()

    def mvc(self, n):
        if n == 0:
            return

        # Move DOWN
        if n > 0:
            # move cursor
            if self.cpos < self.cmax:
                self.cpos = min(self.cmax, self.cpos + n)
                return
            # move screenlines
            maxvmin = max(0, len(self.lines) - self.span - 1)
            if self.cpos == self.cmax and self.vmin < maxvmin:
                self.vmin = min(maxvmin, self.vmin + n)

        # Move UP
        elif n < 0: # UP
            # move cursor
            if self.cpos > self.cmin:
                self.cpos = max(self.cmin, self.cpos + n)
                return
            # move screenlines
            if self.cpos == self.cmin and self.vmin > 0:
                self.vmin = max(0, self.vmin + n)

    def mvhome(self):
        # move cursor
        if self.cpos != self.cmin:
            self.cpos = self.cmin
        # move screenlines
        if self.vmin != 0:
            self.vmin = 0

    def mvend(self):
        # move cursor
        if self.cpos != self.cmax:
            self.cpos = self.cmax
        # move screenlines
        maxvmin = max(0, len(self.lines) - self.span - 1)
        if self.vmin != maxvmin:
            self.vmin = maxvmin


class ScreenHelp:

    def __init__(self, screen):
        self.screen = screen
        self.xmin = screen.xmin + 1
        self.xmax = screen.xmax
        self.ymin = 0
        self.ymax = __doc__.count('\n')
        self.xpos = 0
        self.ypos = 0

    def setup(self):
        self.pad = curses.newpad(self.ymax + 1, self.xmax + 1)

    def addstr(self, *args, **kwargs):
        return self.pad.addstr(*args, **kwargs)

    def refresh(self):
        self.pad.noutrefresh(
                self.ypos, self.xpos,
                self.screen.smin, self.xmin,
                self.screen.smax, self.xmax - 2)

    def draw(self):
        self.addstr(0, 0, __doc__)

    def mvc(self, n):
        if n == 0:
            return

        # Move DOWN
        if n > 0:
            self.ypos = min(self.ymax - self.screen.span, self.ypos + n)

        # Move UP
        elif n < 0:
            self.ypos = max(self.ymin, self.ypos + n)

    def mvhome(self):
        self.ypos = self.ymin

    def mvend(self):
        self.ypos = self.ymax - self.screen.span


class ScreenMode:

    def __init__(self, name):
        self.name = name
        self.columns = []

    @property
    def head(self):
        return get_head(self)

    def sync(self, screen):
        for idx, column in enumerate(self.columns):
            column.width = get_width(column.minwidth, screen.xmax,
                    len(self.columns), idx)


class ScreenColumn:

    def __init__(self, name, header, minwidth, maxwidth, align, filters={}):
        self.name = name
        self.header = header
        self.align = align
        self.minwidth = minwidth
        self.maxwidth = maxwidth
        self.width = minwidth
        self.filters = {'always': [], 'ondemand': []}
        self.filters.update(filters)

    def get_width(self):
        return self._width

    def set_width(self, n):
        if self.maxwidth:
            self._width = min(self.maxwidth, n)
        self._width = max(self.minwidth, n)

    width = property(get_width, set_width)


class ScreenLine:

    def __init__(self, stat=None, text='', attr=0):
        self.stat = stat
        self.text = text
        self.attr = attr


class StatusBar:

    def __init__(self, width=60, min=0, max=100, status=True):
        self.width = width
        self.curval = min
        self.minval = min
        self.maxval = max
        self.status = status
        self.prepend = '['
        self.append = ']'
        self.usedchar = '|'
        self.freechar = ' '

    def __str__(self):
        if self.status:
            status = '%d/%d' % (self.curval, self.maxval)

        space = self.width - len(self.prepend) - len(self.append)
        span = self.maxval - self.minval

        if span:
            used = min(float(self.curval) / float(span), 1.0)
        else:
            used = 0.0
        free = 1.0 - used

        # 100% equals full bar width, ignoring status text within the bar
        bar  = self.prepend
        bar += self.usedchar * int(space * used)
        bar += self.freechar * int(space * free)
        if self.status:
            bar  = bar[:(self.width - len(status) - len(self.append))]
            bar += status
        bar += self.append

        return bar

    def update_cur(self, value):
        value = min(self.maxval, value)
        value = max(self.minval, value)
        self.curval = value

    def update_max(self, value):
        if value >= self.minval:
            self.maxval = value
        else:
            self.maxval = self.minval

# ------------------------------------------------------------------------- #
#                             DISPLAY FILTERS                               #
# ------------------------------------------------------------------------- #

def human_seconds(numeric):
    for minval, prefix in sorted(PREFIX_TIME.items(), reverse=True):
        if (numeric/minval):
            return '%d%s' % (numeric/minval, prefix)
    return '%ds' % numeric

def human_metric(numeric):
    for minval, prefix in sorted(PREFIX_METRIC.items(), reverse=True):
        if (numeric/minval):
            return '%d%s' % (numeric/minval, prefix)
    return str(numeric)

def human_binary(numeric):
    for minval, prefix in sorted(PREFIX_BINARY.items(), reverse=True):
        if (numeric/minval):
            return '%.2f%s' % (float(numeric)/float(minval), prefix)
    return '%dB' % numeric

def trim(string, length):
    if len(string) <= length:
        return string
    if length == 1:
        return string[0]
    if length > 5:
        return '..%s' % string[-(length-2):]
    return '...'

# ------------------------------------------------------------------------- #
#                             SCREEN LAYOUT                                 #
# ------------------------------------------------------------------------- #

SCREEN_MODES = [
        ScreenMode('HELP'),
        ScreenMode('STATUS'),
        ScreenMode('TRAFFIC'),
        ScreenMode('HTTP'),
        ScreenMode('ERRORS'),
        ScreenMode('CLI'),
]

# Mode: HELP         name            header     xmin    xmax    align
SCREEN_MODES[0].columns = [
        ScreenColumn('help', ' HATop Online Help ',
                                         SCREEN_XMIN,      0,    'L'),
]

# Mode: STATUS       name            header     xmin    xmax    align
SCREEN_MODES[1].columns = [
        ScreenColumn('svname',       'NAME',      10,     50,    'L'),
        ScreenColumn('weight',       'W',          4,      6,    'R'),
        ScreenColumn('status',       'STATUS',     6,     10,    'L'),
        ScreenColumn('check_status', 'CHECK',      7,     20,    'L'),
        ScreenColumn('act',          'ACT',        3,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('bck',          'BCK',        3,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('qcur',         'QCUR',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('qmax',         'QMAX',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('scur',         'SCUR',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('smax',         'SMAX',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('slim',         'SLIM',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('stot',         'STOT',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
]

# Mode: TRAFFIC      name            header     xmin    xmax    align
SCREEN_MODES[2].columns = [
        ScreenColumn('svname',       'NAME',      10,     50,    'L'),
        ScreenColumn('weight',       'W',          4,      6,    'R'),
        ScreenColumn('status',       'STATUS',     6,     10,    'L'),
        ScreenColumn('lbtot',        'LBTOT',      8,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('rate',         'RATE',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('rate_lim',     'RLIM',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('rate_max',     'RMAX',       6,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('bin',          'BIN',       12,      0,    'R',
            filters={'always':   [human_binary]}),
        ScreenColumn('bout',         'BOUT',      12,      0,    'R',
            filters={'always':   [human_binary]}),
]

# Mode: HTTP         name            header     xmin    xmax    align
SCREEN_MODES[3].columns = [
        ScreenColumn('svname',       'NAME',      10,     50,    'L'),
        ScreenColumn('weight',       'W',          4,      6,    'R'),
        ScreenColumn('status',       'STATUS',     6,     10,    'L'),
        ScreenColumn('req_rate',     'RATE',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('req_rate_max', 'RMAX',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('req_tot',      'RTOT',       7,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_1xx',     '1xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_2xx',     '2xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_3xx',     '3xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_4xx',     '4xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_5xx',     '5xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('hrsp_other',   '?xx',        5,      0,    'R',
            filters={'ondemand': [human_metric]}),
]

# Mode: ERRORS       name            header     xmin    xmax    align
SCREEN_MODES[4].columns = [
        ScreenColumn('svname',       'NAME',      10,     50,    'L'),
        ScreenColumn('weight',       'W',          4,      6,    'R'),
        ScreenColumn('status',       'STATUS',     6,     10,    'L'),
        ScreenColumn('check_status', 'CHECK',      7,     20,    'L'),
        ScreenColumn('chkfail',      'CF',         3,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('chkdown',      'CD',         3,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('lastchg',      'CL',         3,      0,    'R',
            filters={'always':   [human_seconds]}),
        ScreenColumn('econ',         'ECONN',      5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('ereq',         'EREQ',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('eresp',        'ERSP',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('dreq',         'DREQ',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('dresp',        'DRSP',       5,      0,    'R',
            filters={'ondemand': [human_metric]}),
        ScreenColumn('downtime',     'DOWN',       5,      0,    'R',
            filters={'always':   [human_seconds]}),
]

# Mode: CLI          name            header     xmin    xmax    align
SCREEN_MODES[5].columns = [
        ScreenColumn('cli',
            ' haproxy command line                              '
            ' use ALT-n / ESC-n to escape',
                                         SCREEN_XMIN,      0,    'L'),
]

# ------------------------------------------------------------------------- #
#                                HELPERS                                    #
# ------------------------------------------------------------------------- #

def log(msg):
    sys.stderr.write('%s\n' % msg)

def parse_stat(iterable):
    pxcount = svcount = 0
    pxstat = {} # {iid: {sid: svstat, ...}, ...}

    idx_iid = get_idx('iid')
    idx_sid = get_idx('sid')

    for line in iterable:
        if not line:
            continue
        if line.startswith(HAPROXY_STAT_COMMENT):
            continue # comment
        if line.count(HAPROXY_STAT_SEP) < HAPROXY_STAT_NUMFIELDS:
            continue # unknown format

        csv = line.split(HAPROXY_STAT_SEP, HAPROXY_STAT_NUMFIELDS)

        # Skip further parsing?
        if svcount > HAPROXY_STAT_MAX_SERVICES:
            try:
                iid = csv[idx_iid]
                iid = int(iid, 10)
            except ValueError:
                raise RuntimeError(
                        'garbage proxy identifier: iid="%s" (need %s)' %
                        (iid, int))
            try:
                sid = csv[idx_sid]
                sid = int(sid, 10)
            except ValueError:
                raise RuntimeError(
                        'garbage service identifier: sid="%s" (need %s)' %
                        (sid, int))
            if iid not in pxstat:
                pxcount += 1
                svcount += 1
            elif sid not in pxstat[iid]:
                svcount += 1
            continue

        # Parse stat...
        svstat = {} # {field: value, ...}

        for idx, field in HAPROXY_STAT_CSV:
            field_type, field_name = field
            value = csv[idx]

            try:
                if field_type is int:
                    if len(value):
                        value = int(value, 10)
                    else:
                        value = 0
                elif field_type is not type(value):
                        value = field_type(value)
            except ValueError:
                raise RuntimeError('garbage field: %s="%s" (need %s)' % (
                        field_name, value, field_type))

            # Special case
            if field_name == 'status' and value == 'no check':
                value = '-'
            elif field_name == 'check_status' and svstat['status'] == '-':
                value = 'none'

            svstat[field_name] = value

        # Record result...
        iid = svstat['iid']
        stype = svstat['type']

        if stype == 0 or stype == 1:  # FRONTEND / BACKEND
            id = svstat['svname']
        else:
            id = svstat['sid']

        try:
            pxstat[iid][id] = svstat
        except KeyError:
            pxstat[iid] = { id: svstat }
            pxcount += 1
        svcount += 1

    return pxstat, pxcount, svcount

def parse_info(iterable):
    info = {}
    for line in iterable:
        line = line.strip()
        if not line:
            continue
        for key, regexp in HAPROXY_INFO_RE.iteritems():
            match = regexp.match(line)
            if match:
                info[key] = match.group('value')
                break

    for key in HAPROXY_INFO_RE.iterkeys():
        if not key in info:
            raise RuntimeError('missing "%s" in info data' % key)

    return info

def get_idx(field):
    return filter(lambda x: x[1][1] == field, HAPROXY_STAT_CSV)[0][0]

def get_width(width, xmax, ncols, idx):
    # distribute excess space evenly from left to right
    if xmax > SCREEN_XMIN:
        xdiff = xmax - SCREEN_XMIN
        if xdiff <= ncols:
            if idx < xdiff:
                width += 1
        else:
            if idx < (xdiff - (xdiff / ncols) * ncols):
                width += 1 # compensate rounding
            width = width + xdiff / ncols
    return width

def get_cell(width, align, value):
    s = str(value)
    if align == 'L':
        s = s.ljust(width)
    elif align == 'C':
        s = s.center(width)
    elif align == 'R':
        s = s.rjust(width)
    return s

def get_head(mode):
    columns = []
    for column in mode.columns:
        s = column.header
        s = get_cell(column.width, column.align, s)
        columns.append(s)
    return ' '.join(columns)

def get_screenlines(stat):
    screenlines = []

    for iid, svstats in stat.iteritems():
        lines = []

        try:
            frontend = svstats.pop('FRONTEND')
        except KeyError:
            frontend = None
        try:
            backend = svstats.pop('BACKEND')
        except KeyError:
            backend = None

        if frontend:
            lines.append(ScreenLine(stat=frontend))

        for sid, svstat in sorted(svstats.items()):
            lines.append(ScreenLine(stat=svstat))

        if backend:
            lines.append(ScreenLine(stat=backend))

        if not len(lines):
            continue

        pxname = lines[0].stat['pxname']
        screenlines.append(ScreenLine(attr=curses.A_BOLD,
            text='>>> %s' % pxname))
        screenlines += lines
        screenlines.append(ScreenLine())

    # remove trailing empty line
    if len(screenlines) > 1:
        screenlines.pop()

    return screenlines

def get_screenline(mode, stat):
    cells = []
    for column in mode.columns:
        value = stat[column.name]

        for filter in column.filters['always']:
            value = filter(value)

        if len(str(value)) > column.width:
            for filter in column.filters['ondemand']:
                value = filter(value)

        value = str(value)
        value = trim(value, column.width)
        cells.append(get_cell(column.width, column.align, value))

    return ' '.join(cells)

# ------------------------------------------------------------------------- #
#                            CURSES HELPERS                                 #
# ------------------------------------------------------------------------- #

def curses_init():
    screen = curses.initscr()
    curses.noecho()
    curses.nonl()
    curses.raw()

    # Some terminals don't support different cursor visibilities
    try:
        curses.curs_set(0)
    except CursesError:
        pass

    # Some terminals don't support the default color palette
    try:
        curses.start_color()
        curses.use_default_colors()
    except CursesError:
        pass

    return screen

def curses_reset(screen):
    if not screen:
        return
    screen.keypad(0)
    curses.noraw()
    curses.echo()
    curses.endwin()

# ------------------------------------------------------------------------- #
#                               MAIN LOOP                                   #
# ------------------------------------------------------------------------- #

def mainloop(screen, interval):
    # Sleep time of each iteration in seconds
    scan = 1.0 / 100.0
    # Query socket and redraw the screen in the given interval
    iterations = interval / scan

    i = 0
    update_stat = True      # Toggle stat update (query socket, parse csv)
    update_lines = True     # Toggle screen line update (sync with stat data)
    update_display = True   # Toggle screen update (resize, repaint, refresh)
    switch_mode = False     # Toggle mode / viewport switch

    while True:

        # Resize toggled by SIGWINCH?
        if screen.resized:
            screen.resize()
            update_display = True

        # Update interval reached...
        if i == iterations:
            update_stat = True
            if 0 < screen.mid < 5:
                update_lines = True
            update_display = True
            i = 0

        # Refresh screen?
        if update_display:

            if update_stat:
                screen.update_data()
                screen.update_bars()
                update_stat = False

            if update_lines:
                screen.update_lines()
                update_lines = False

            screen.erase()
            screen.draw_head()
            screen.draw_info()
            screen.draw_cols()
            screen.draw_mode()
            screen.draw_foot()
            screen.refresh()

            update_display = False

        c = screen.getch()

        if c < 0:
            time.sleep(scan)
            i += 1
            continue

        # Toggle hotkey footer
        if screen.hotkeys:
            if c not in (
                    curses.KEY_F4,          # reset weight
                    curses.KEY_F5,          # weight -10
                    curses.KEY_F6,          # weight -1
                    curses.KEY_F7,          # weight +1
                    curses.KEY_F8,          # weight +10
                    curses.KEY_F9,          # enable server
                    curses.KEY_F10,         # disable server
            ):
                screen.hotkeys = False
                update_display = True
            if c in (
                    curses.KEY_ENTER,
                    curses.ascii.CR
            ):
                continue

        if c == curses.ascii.ETX:
            raise KeyboardInterrupt()

        # Mode switch (ALT-n / ESC-n) or toggle (ESC / ESC-ESC)
        if c == curses.ascii.ESC:
            c = screen.getch()
            if c < 0 or c == curses.ascii.ESC:
                screen.toggle_mode()
                update_display = True
                continue
            if 0 < c < 256:
                c = chr(c)
                if c in 'qQHh?12345':
                    switch_mode = True

        # Mode cycle (TAB / BTAB)
        elif c == ord('\t'):
            screen.cycle_mode(1)
            update_display = True
            continue
        elif c == curses.KEY_BTAB:
            screen.cycle_mode(-1)
            update_display = True
            continue

        # Mode switch in non-CLI modes using the number only
        elif 0 <= screen.mid < 5 and 0 < c < 256:
            c = chr(c)
            if c in 'qQHh?12345':
                switch_mode = True

        if switch_mode:
            switch_mode = False
            if c in 'qQ':
                    raise StopIteration()
            if c != str(screen.mid) or (c in 'Hh?' and screen.mid != 0):
                if c in 'Hh?':
                    screen.switch_mode(0)
                elif c in '12345':
                    screen.switch_mode(int(c))

                # Force screen update with existing data
                update_display = True
                continue

        # -> HELP
        if screen.mid == 0:
            if c == curses.KEY_UP and screen.help.ypos > 0:
                screen.help.mvc(-1)
            elif c == curses.KEY_DOWN and \
                    screen.help.ypos < screen.help.ymax - screen.span:
                screen.help.mvc(1)
            elif c == curses.KEY_PPAGE and screen.help.ypos > 0:
                screen.help.mvc(-10)
            elif c == curses.KEY_NPAGE and \
                    screen.help.ypos < screen.help.ymax - screen.span:
                screen.help.mvc(10)
            elif c == curses.ascii.SOH or c == curses.KEY_HOME:
                screen.help.mvhome()
            elif c == curses.ascii.ENQ or c == curses.KEY_END:
                screen.help.mvend()

        # -> STATUS / TRAFFIC / HTTP / ERRORS
        elif 1 <= screen.mid <= 4:

            # movements
            if c == curses.KEY_UP:
                screen.mvc(-1)
            elif c == curses.KEY_DOWN:
                screen.mvc(1)
            elif c == curses.KEY_PPAGE:
                screen.mvc(-10)
            elif c == curses.KEY_NPAGE:
                screen.mvc(10)
            elif c == curses.ascii.SOH or c == curses.KEY_HOME:
                screen.mvhome()
            elif c == curses.ascii.ENQ or c == curses.KEY_END:
                screen.mvend()

            # actions
            elif c in (
                    curses.KEY_ENTER,       # show hotkeys
                    chr(curses.ascii.CR),   # show hotkeys
                    chr(curses.ascii.SP),   # copy & paste identifier
                    curses.KEY_F4,          # reset weight
                    curses.KEY_F5,          # weight -10
                    curses.KEY_F6,          # weight -1
                    curses.KEY_F7,          # weight +1
                    curses.KEY_F8,          # weight +10
                    curses.KEY_F9,          # enable server
                    curses.KEY_F10,         # disable server
            ):
                if screen.data.socket.ro:
                    continue
                if not screen.cstat:
                    continue

                if c == curses.KEY_ENTER or c == chr(curses.ascii.CR):
                    screen.hotkeys = True
                    update_display = True
                    continue

                iid = screen.cstat['iid']
                sid = screen.cstat['sid']

                if iid <= 0 or sid <= 0:
                    continue

                pxname = screen.cstat['pxname']
                svname = screen.cstat['svname']

                if not pxname or not svname:
                    continue

                notify = False

                if c == ' ':
                    if screen.cli.puts('%s/%s' % (pxname, svname)):
                        screen.switch_mode(5)
                        update_display = True
                        continue
                elif c == curses.KEY_F4:
                    screen.cli.execute_cmdline(
                            'set weight %s/%s 100%%' % (pxname, svname))
                    notify = True
                elif c == curses.KEY_F5:
                    curweight = screen.cstat['weight']
                    if curweight <= 0:
                        continue
                    weight = max(0, curweight - 10)             # - 10
                    screen.cli.execute_cmdline(
                            'set weight %s/%s %d' % (pxname, svname, weight))
                    notify = True
                elif c == curses.KEY_F6:
                    curweight = screen.cstat['weight']
                    if curweight <= 0:
                        continue
                    weight = max(0, curweight - 1)              # - 1
                    screen.cli.execute_cmdline(
                            'set weight %s/%s %d' % (pxname, svname, weight))
                    notify = True
                elif c == curses.KEY_F7:
                    curweight = screen.cstat['weight']
                    if curweight >= 256:
                        continue
                    weight = min(256, curweight + 1)            # + 1
                    screen.cli.execute_cmdline(
                            'set weight %s/%s %d' % (pxname, svname, weight))
                    notify = True
                elif c == curses.KEY_F8:
                    curweight = screen.cstat['weight']
                    if curweight >= 256:
                        continue
                    weight = min(256, curweight + 10)           # + 10
                    screen.cli.execute_cmdline(
                            'set weight %s/%s %d' % (pxname, svname, weight))
                    notify = True
                elif c == curses.KEY_F9:
                    screen.cli.execute_cmdline(
                            'enable server %s/%s' % (pxname, svname))
                    notify = True
                elif c == curses.KEY_F10:
                    screen.cli.execute_cmdline(
                            'disable server %s/%s' % (pxname, svname))
                    notify = True

                # Refresh the screen indicating pending changes...
                if notify:
                    screen.cstat['message'] = 'updating...'
                    update_display = True
                    continue

        # -> CLI
        elif screen.mid == 5:

            # enter
            if c == curses.KEY_ENTER or c == curses.ascii.CR:
                screen.cli.execute()

            # input movements
            elif c == curses.KEY_LEFT:
                screen.cli.mvc(-1)
            elif c == curses.KEY_RIGHT:
                screen.cli.mvc(1)
            elif c == curses.ascii.SOH or c == curses.KEY_HOME:
                screen.cli.mvhome()
            elif c == curses.ascii.ENQ or c == curses.KEY_END:
                screen.cli.mvend()

            # input editing
            elif c == curses.ascii.ETB:
                pass # TODO (CTRL-W)
            elif c == curses.KEY_DC:
                screen.cli.delc(1)
            elif c == curses.KEY_BACKSPACE or c == curses.ascii.DEL:
                screen.cli.delc(-1)

            # input history
            elif c == curses.KEY_UP:
                screen.cli.prev()
            elif c == curses.KEY_DOWN:
                screen.cli.next()

            # output history
            elif c == curses.KEY_PPAGE:
                screen.cli.mvo(-1)
            elif c == curses.KEY_NPAGE:
                screen.cli.mvo(1)

            elif 0 < c < 256:
                screen.cli.putc(chr(c))

        # Force screen update with existing data if key was a movement key
        if c in (
            curses.KEY_UP,
            curses.KEY_DOWN,
            curses.KEY_PPAGE,
            curses.KEY_NPAGE,
        ) or screen.mid != 5 and c in (
            curses.ascii.SOH, curses.KEY_HOME,
            curses.ascii.ENQ, curses.KEY_END,
        ):
            update_display = True

        time.sleep(scan)
        i += 1


if __name__ == '__main__':

    from optparse import OptionParser, OptionGroup

    version  = 'hatop version %s' % __version__
    usage    = 'Usage: hatop -s SOCKET [OPTIONS]...'

    parser = OptionParser(usage=usage, version=version)

    opts = OptionGroup(parser, 'Mandatory')
    opts.add_option('-s', '--unix-socket', dest='socket',
            help='path to the haproxy unix socket')
    parser.add_option_group(opts)

    opts = OptionGroup(parser, 'Optional')
    opts.add_option('-i', '--update-interval', type='int', dest='interval',
            help='update interval in seconds (1-30, default: 3)', default=3)
    opts.add_option('-m', '--mode', type='int', dest='mode',
            help='start in specific mode (1-5, default: 1)', default=1)
    opts.add_option('-n', '--read-only', action='store_true', dest='ro',
            help='disable the cli and query for stats only')
    parser.add_option_group(opts)

    opts = OptionGroup(parser, 'Filters',
            'Note: All filter options may be given multiple times.')
    opts.add_option('-f', '--filter', action='append', dest='stat_filter',
            default=[], metavar='FILTER',
            help='stat filter in format "<iid> <type> <sid>"')
    opts.add_option('-p', '--proxy', action='append', dest='proxy_filter',
            default=[], metavar='PROXY',
            help='proxy filter in format "<pxname>"')
    parser.add_option_group(opts)

    opts, args = parser.parse_args()

    if not 1 <= opts.interval <= 30:
        log('invalid update interval: %d' % opts.interval)
        sys.exit(1)
    if not 1 <= opts.mode <= 5:
        log('invalid mode: %d' % opts.mode)
        sys.exit(1)
    if len(opts.stat_filter) + len(opts.proxy_filter) > 50:
        log('filter limit exceeded (50)')
        sys.exit(1)
    if opts.ro and opts.mode == 5:
        log('cli not available in read-only mode')
        sys.exit(1)
    if not opts.socket:
        parser.print_help()
        sys.exit(0)
    if not os.access(opts.socket, os.R_OK | os.W_OK):
        log('insufficient permissions for socket path %s' % opts.socket)
        sys.exit(2)

    socket = Socket(opts.socket, opts.ro)
    data = SocketData(socket)
    screen = Screen(data, opts.mode)

    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))

    try:
        try:
            socket.connect()
            screen.setup()

            # Register filters
            data.register_stat_filter(opts.stat_filter)
            data.register_proxy_filter(opts.proxy_filter)

            while True:
                try:
                    mainloop(screen, opts.interval)
                except StopIteration:
                    break
                except KeyboardInterrupt:
                    break
                except CursesError, e:
                    screen.reset()
                    log('curses error: %s, restarting...' % e)
                    time.sleep(1)
                    screen.recover()

        except ValueError, e:
            screen.reset()
            log('value error: %s' % e)
            sys.exit(1)
        except RuntimeError, e:
            screen.reset()
            log('runtime error: %s' % e)
            sys.exit(1)
        except SocketError, e:
            screen.reset()
            log('socket error: %s' % e)
            sys.exit(2)

    finally:
        screen.reset()
        socket.close()

    sys.exit(0)

# vim: et sw=4 sts=4 ts=4 tw=78 fdn=1 fdm=indent