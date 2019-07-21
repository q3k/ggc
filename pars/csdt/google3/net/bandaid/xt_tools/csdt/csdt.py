"""Console Status Display - show current hardware status of GGC machines."""

__author__ = 'morda@google.com (Marcin Kaminski)'

import argparse
import curses
import logging
import logging.handlers
import signal
import sys
import time

from google3.net.bandaid.xt_tools.csdt import lib_colors
from google3.net.bandaid.xt_tools.csdt import lib_common
from google3.net.bandaid.xt_tools.csdt import tile_connectivity
from google3.net.bandaid.xt_tools.csdt import tile_disks
from google3.net.bandaid.xt_tools.csdt import tile_fans
from google3.net.bandaid.xt_tools.csdt import tile_identification
from google3.net.bandaid.xt_tools.csdt import tile_interfaces
from google3.net.bandaid.xt_tools.csdt import tile_memory
from google3.net.bandaid.xt_tools.csdt import tile_psus

# TODO(morda): Move all color handling code to lib_colors.py.
# Define curses color pairs.
_COLOR_RED_ON_BLACK = 1
_COLOR_GREEN_ON_BLACK = 2
_COLOR_YELLOW_ON_BLACK = 3
_COLOR_BLUE_ON_BLACK = 4
_COLOR_MAGENTA_ON_BLACK = 5
_COLOR_CYAN_ON_BLACK = 6
_COLOR_WHITE_ON_BLACK = 7
_COLOR_BLACK_ON_GREEN = 8

# Define status bar message types.
_STATUS_BAR_HELP = 0
_STATUS_BAR_IDLE = 1
_STATUS_BAR_REFRESH = 2
_STATUS_BAR_REFUSE_REFRESH = 3

_HELP_CONTENTS = """
The goal of this tool is to provide you with instant feedback on
the status of the most crucial hardware components while on-site.

This should allow you to perform part replacements or other diagnostics,
verify the result and leave the site instead of having to contact
the EdgeOps team and wait for the response.


  Top of the screen shows information which should help you identify this
  machine.

  In the middle of the screen, you'll find information about the state of
  various hardware components and other information we consider to be useful
  to you as a technician.

  Bottom line shows the current status of the tool itself.


If you notice this tool misbehaving, please contact ggc@google.com.
""".strip()


TILES_TO_REGISTER = {

    # Machine identification.
    'Top status bar': {
        'tile': tile_identification.IdentificationTile,
        'row': 0,
        'column': 0,
        'height': 3,
        'width': 80,
        'color_theme': _COLOR_BLACK_ON_GREEN,
    },

    # Left side of the screen.
    'Disk status': {
        'tile': tile_disks.DiskStatusTile,
        'row': 4,
        'column': 1,
        'height': 3,
        'width': 33,
    },
    'Power supply status': {
        'tile': tile_psus.PsuStatusTile,
        'row': 8,
        'column': 1,
        'height': 3,
        'width': 33,
    },
    'Fan status': {
        'tile': tile_fans.FanStatusTile,
        'row': 12,
        'column': 1,
        'height': 3,
        'width': 33,
    },
    'Memory status': {
        'tile': tile_memory.MemoryStatusTile,
        'row': 16,
        'column': 1,
        'height': 3,
        'width': 33,
    },

    # Right side of the screen.
    'Network interface status': {
        'tile': tile_interfaces.InterfaceStatusTile,
        'row': 4,
        'column': 36,
        'height': 12,
        'width': 44,
    },
    'Network connectivity': {
        'tile': tile_connectivity.ConnectivityStatusTile,
        'row': 16,
        'column': 36,
        'height': 4,
        'width': 44,
    },
}


class Error(Exception):
  pass


class ConsoleDisplayTool(object):
  """Console Status Display Tool."""

  def __init__(self, stdscr, tty=None, allow_exit=False,
               logfile='/var/log/csdt.log', loglevel='info',
               forced_refresh_min_interval=30, skip_initial_delay=False,
               handle_keys=False, color_mode=None):
    """Initialise Console Status Display Tool.

    Args:
      stdscr: Instance of curses.WindowObject passed by curses.wrapper.
      tty: TTY device name for CSDT to run on, such as ttyN (str).
      allow_exit: Whether to allow closing the application that's usually
          running on the machine's console (bool).
      logfile: Log file path (str).
      loglevel: Logging verbosity (str).
      forced_refresh_min_interval: Interval between forced refreshes (int).
      skip_initial_delay: Skip the initial delay when testing (bool).
      handle_keys: Allow keys to be used to control CSDT (bool).
      color_mode: Color mode (one of lib_colors.COLOR_MODE_*).
    """
    self.stdscr = stdscr
    self.tty = tty
    self.allow_exit = allow_exit
    self.skip_initial_delay = skip_initial_delay
    self.forced_refresh_min_interval = forced_refresh_min_interval
    self.handle_keys = handle_keys

    if color_mode:
      self.color_mode = color_mode
    else:
      self.color_mode = lib_colors.COLOR_MODE_ANSI

    self.color_codes = lib_colors.GetColorCodes(color_mode=self.color_mode)

    self.status_bar = None
    self.tiles = []

    self._ConfigureLogging(
        logfile=logfile, loglevel=getattr(logging, loglevel.upper()))

    self._InitialiseScreen()

    # Ensure screen gets restored to its previous state upon exiting CSDT.
    signal.signal(signal.SIGINT, self._HandleSignal)
    signal.signal(signal.SIGTERM, self._HandleSignal)
    signal.signal(signal.SIGTSTP, self._HandleSignal)

    self.forced_refresh_timestamp = int(time.time())

  def _ConfigureLogging(self, logfile, loglevel=logging.INFO):
    """Configure the root logger for CSDT.

    Args:
      logfile: Log file path (string).
      loglevel: Logging verbosity (logging.LOGLEVEL).
    """
    formatter = logging.Formatter(
        fmt='%(asctime)s %(levelname)-10s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    # This handler is necessary since the default handler doesn't attempt to
    # re-open a log file if it disappears due to, i.e. being rotated.
    handler = logging.handlers.WatchedFileHandler(logfile)
    handler.setFormatter(formatter)
    handler.setLevel(loglevel)

    logger = logging.getLogger()
    for existing_handler in logger.handlers:
      logger.removeHandler(existing_handler)
    logger.addHandler(handler)
    logger.setLevel(loglevel)

    logging.info('*' * 80)
    if self.tty:
      logging.info('Launching Console Status Display on %s.', self.tty)
    else:
      logging.info('Launching Console Status Display interactively.')
    logging.info('*' * 80)

  def _InitialiseScreen(self):
    """Initialise curses screen objects and set their properties."""

    # Explicitly set the desired curses features.

    # Disable echoing of input characters.
    curses.noecho()
    # Make cursor invisible.
    curses.curs_set(0)
    # Disable translation of return into newline on input.
    curses.nonl()
    # Interpret escape sequences generated by keypad and function keys.
    self.stdscr.keypad(1)
    # Make getch() wait for input without blocking indefinitely.
    self.stdscr.timeout(1)

    if self.handle_keys:
      # Allow processing signals, flow-control and character input.
      curses.cbreak()
    else:
      # Set terminal to raw mode; disable flow-control and signals.
      curses.raw()

    # TODO(morda): Move all color handling code to lib_colors.py.
    # Initialise colour pairs.
    curses.init_pair(
        _COLOR_RED_ON_BLACK, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_GREEN_ON_BLACK, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_YELLOW_ON_BLACK, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_BLUE_ON_BLACK, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_MAGENTA_ON_BLACK, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_CYAN_ON_BLACK, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_WHITE_ON_BLACK, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(
        _COLOR_BLACK_ON_GREEN, curses.COLOR_BLACK, curses.COLOR_GREEN)

  def RegisterTile(self, tile, row, column, height, width,
                   color_theme=_COLOR_WHITE_ON_BLACK):
    """Add a tile to the list of currently registered tiles.

    Args:
      tile: Tile class to instantiate (InformationTile).
      row: Vertical position relative to the console screen (int).
      column: Horizontal position relative to the console screen (int).
      height: Height of the tile's window (int).
      width: Width of the tile's window (int).
      color_theme: color_pair to use as the window's background (int).

    Returns:
      None
    """
    logging.info(
        'Registering tile \'%s\' at row: %d, column: %d, width: %d, height: %d',
        tile.GetTileName(),
        row, column, width, height)
    tile_data = {
        'tile': tile(),
        'window': curses.newwin(height, width, row, column),
    }
    tile_data['window'].bkgd(' ', curses.color_pair(color_theme))
    self.tiles.append(tile_data)

  def _UpdateTile(self, tile, force_refresh=False):
    """Update the contents of a tile if required.

    Args:
      tile: Dictionary with the following keys:
      - tile: Tile instance (tile.InformationTile).
      - window: Curses window instance (curses.window).
      force_refresh: Whether to request an immediate refresh (boolean).

    Returns:
      True if content of a tile was refreshed.
      False otherwise.
    """
    if tile['tile'].IsRefreshRequired() or force_refresh:
      logging.debug(
          'Updating content of \'%s\' tile.', tile['tile'].GetTileName())

      self._UpdateStatusBar(
          message_type=_STATUS_BAR_REFRESH, message=tile['tile'].GetTileName())
      tile['window'].erase()

      if tile['tile'].DisplayTileName():
        tile_name = '{c.bold}%s{c.reset}\n' % tile['tile'].GetTileName()
        self._AddStringWithAttributes(
            window=tile['window'],
            string=tile_name.format(c=self.color_codes))
        self._AddStringWithAttributes(
            window=tile['window'],
            row=1, column=0,
            string=tile['tile'].GetContent())
      else:
        self._AddStringWithAttributes(
            window=tile['window'],
            string=tile['tile'].GetContent())
      tile['tile'].UpdateRefreshTimestamp()
      return True
    return False

  def _UpdateStatusBar(self, message_type=_STATUS_BAR_REFRESH, message='',
                       timeout=None):
    """Show status updates in the notification area.

    Args:
      message_type: Type of message to present, one of _STATUS_BAR_* (int).
      message: Additional message content to display on the status bar (str).
      timeout: Time, in seconds, to keep the message visible for (int).
    """
    if not self.status_bar:
      self.status_bar = curses.newwin(1, 80, 24, 0)
      self.status_bar.bkgd(' ', curses.color_pair(_COLOR_BLACK_ON_GREEN))
      self.status_bar.erase()

      # The initial delay is introduced to prevent running ipmitool and megacli
      # commands continuously too often, if CSDT crashes for some reason and is
      # restarted by init, since it's running on the machine's TTY console.
      if self.skip_initial_delay:
        timeout = 1
      else:
        timeout = self.forced_refresh_min_interval

      self._AddStringWithAttributes(
          window=self.status_bar, row=0, column=1,
          string='Initialising GGC Console...')
    else:
      self.status_bar.erase()

      # When idle, show time until the next screen refresh.
      if message_type == _STATUS_BAR_IDLE:
        seconds_until_refresh = self._GetSecondsUntilRefresh()
        minutes = int(seconds_until_refresh / 60)
        seconds = int(seconds_until_refresh % 60)
        if self._AllowForcedRefresh() and self.handle_keys:
          message = (
              'Press {c.bold}SPACE{c.reset} to refresh or wait '
              '{c.bold}%02d:%02d{c.reset}' % (minutes, seconds))
          self._AddStringWithAttributes(
              window=self.status_bar, row=0, column=1,
              string=message.format(c=self.color_codes))
        else:
          message = (
              'Wait {c.bold}%02d:%02d{c.reset} for an automatic refresh' %
              (minutes, seconds))
          self._AddStringWithAttributes(
              window=self.status_bar, row=0, column=1,
              string=message.format(c=self.color_codes))
        if self.handle_keys:
          message = 'Press {c.bold}h{c.reset} for help'
          self._AddStringWithAttributes(
              window=self.status_bar, row=0, column=63,
              string=message.format(c=self.color_codes))

      # Tell user to wait longer before forcing a screen refresh.
      elif message_type == _STATUS_BAR_REFUSE_REFRESH:
        time_until_refresh_allowed = self.forced_refresh_min_interval - (
            int(time.time() - self.forced_refresh_timestamp))
        message = (
            'Please wait {c.bold}%d{c.reset} more seconds ' %
            time_until_refresh_allowed)
        self._AddStringWithAttributes(
            window=self.status_bar, row=0, column=1,
            string=message.format(c=self.color_codes))

      # Show message to exit help and go back to main screen.
      elif message_type == _STATUS_BAR_HELP:
        message = 'Press {c.bold}almost{c.reset} any key to go back'
        self._AddStringWithAttributes(
            window=self.status_bar, row=0, column=1,
            string=message.format(c=self.color_codes))

      # Show screen refresh progress.
      elif message_type == _STATUS_BAR_REFRESH:
        message = 'Refreshing: {c.bold}%s{c.reset}' % message
        self._AddStringWithAttributes(
            window=self.status_bar, row=0, column=1,
            string=message.format(c=self.color_codes))

      else:
        logging.debug('Unsupported status bar message_type passed.')
        return

    self.status_bar.refresh()

    # If timeout is specified, make sure the message is visible for n seconds.
    if timeout:
      time.sleep(timeout)

  def _RedrawScreen(self, force_refresh=False):
    """Redraw all curses screens and windows."""

    execute_forced_refresh = force_refresh and self._AllowForcedRefresh()

    if force_refresh:
      if execute_forced_refresh:
        logging.info('Requesting immediate screen refresh.')
        self.forced_refresh_timestamp = time.time()
      else:
        logging.warning('Refusing immediate screen refresh request.')
        self._UpdateStatusBar(
            message_type=_STATUS_BAR_REFUSE_REFRESH, timeout=3)

    for tile in self.tiles:
      if self._UpdateTile(tile, force_refresh=execute_forced_refresh):
        tile['window'].touchwin()
        tile['window'].refresh()

    self._UpdateStatusBar(message_type=_STATUS_BAR_IDLE)

  def _ShowHelp(self):
    """Show help and usage information."""
    logging.info('Showing help window.')
    self.stdscr.erase()
    message = '{c.bold}Console Status Display{c.reset}'
    self._AddStringWithAttributes(
        window=self.stdscr, row=0, column=1,
        string=message.format(c=self.color_codes))
    self._AddStringWithAttributes(
        window=self.stdscr, row=3, column=1,
        string=_HELP_CONTENTS.format(c=self.color_codes))
    self.stdscr.refresh()
    self._UpdateStatusBar(message_type=_STATUS_BAR_HELP)
    while 1:
      key = self.stdscr.getch()
      # TODO(morda): Figure out why getch() always returns key code 10 (RETURN)
      # even if no key is pressed. I chose to ignore those keys for now.
      if key not in [-1, 10]:
        logging.info('Hiding help window.')
        self.stdscr.erase()
        self.stdscr.refresh()
        for tile in self.tiles:
          tile['window'].touchwin()
          tile['window'].refresh()
        break

  def _HandleKey(self, key):
    """Handle key presses and invoke functions mapped to them."""
    try:
      logging.debug('Key pressed: %s (%s)', chr(key), key)

      if chr(key) in [' ', 'r', 'R']:
        self._RedrawScreen(force_refresh=True)

      if chr(key) in ['h', 'H', '?']:
        self._ShowHelp()

      if chr(key) in ['q', 'Q']:
        if self.allow_exit:
          self.RestoreScreenAndExit()
        else:
          logging.debug('Ignored a request to exit.')

    except ValueError:
      logging.debug('Invalid keypress event received: %s', key)
      return

  def _AddStringWithAttributes(self, window, string, row=0, column=0):
    """Add string, converting formatting tokens into curses attributes.

    Args:
      window: instance of curses.window.
      string: string to add to window (str).
      row: vertical position (int).
      column: horizontal position (int).
    """
    window.move(row, column)

    lines = string.splitlines()
    attributes = curses.A_NORMAL

    for line in lines:
      for string_token in lib_colors.GetStringTokens(line, self.color_mode):
        if string_token == self.color_codes.bold:
          attributes |= curses.A_BOLD
        elif string_token == self.color_codes.red:
          attributes |= curses.color_pair(_COLOR_RED_ON_BLACK)
        elif string_token == self.color_codes.green:
          attributes |= curses.color_pair(_COLOR_GREEN_ON_BLACK)
        elif string_token == self.color_codes.yellow:
          attributes |= curses.color_pair(_COLOR_YELLOW_ON_BLACK)
        elif string_token == self.color_codes.blue:
          attributes |= curses.color_pair(_COLOR_BLUE_ON_BLACK)
        elif string_token == self.color_codes.magenta:
          attributes |= curses.color_pair(_COLOR_MAGENTA_ON_BLACK)
        elif string_token == self.color_codes.cyan:
          attributes |= curses.color_pair(_COLOR_CYAN_ON_BLACK)
        elif string_token == self.color_codes.white:
          attributes |= curses.color_pair(_COLOR_WHITE_ON_BLACK)
        elif string_token == self.color_codes.reset:
          attributes = curses.A_NORMAL
        else:
          try:
            window.addstr(string_token, attributes)
          except curses.error:
            logging.debug('Unable to add string: \'%s\'', string_token)
      row += 1
      try:
        window.move(row, column)
      except curses.error:
        logging.debug('Last line, not moving cursor position.')

  def _GetSecondsUntilRefresh(self):
    """Get the number of seconds until the next data screen refresh."""
    return max([tile['tile'].GetSecondsUntilRefresh() for tile in self.tiles])

  def _AllowForcedRefresh(self):
    """Check if we should honour a forced refresh request."""
    seconds_since_last_forced_update = int(
        time.time() - self.forced_refresh_timestamp)
    if seconds_since_last_forced_update > self.forced_refresh_min_interval:
      return True
    return False

  def _HandleSignal(self, signal_number, unused_interrupted_stack_frame=None):
    if self.allow_exit and self.handle_keys:
      logging.debug('Received signal %d and honoured it.', signal_number)
      self.RestoreScreenAndExit()
    else:
      logging.debug('Received signal %d and ignored it.', signal_number)

  @staticmethod
  def RestoreScreenAndExit(exception=None):
    """Restore console screen to its usable state before exiting.

    Args:
      exception: Exception object to allow writing exception details to the
        logfile, if not exiting due to normal termination (Exception).
    """
    logging.info('Restoring terminal state and exiting.')
    curses.echo()
    curses.nocbreak()
    curses.endwin()

    if exception:
      logging.exception('An exception caused CSDT to exit:\n')
      exit_code = lib_common.CSDT_EXIT_EXCEPTION
    else:
      logging.info('Exiting gracefully.')
      exit_code = lib_common.CSDT_EXIT_NORMAL

    lib_common.ExitCsdt(exit_code)

  def Run(self):
    """Run the Console Display Tool."""
    self._UpdateStatusBar()
    while 1:
      if self.handle_keys:
        key = self.stdscr.getch()
        # TODO(morda): Figure out why getch() always returns key code 10
        # (RETURN) even if no key is pressed. I chose to ignore those keys for
        # now.
        if key not in [-1, 10]:
          self._HandleKey(key)
      else:
        # If user input is disabled, introduce the same delay as set by
        # self.stdscr.timeout().
        time.sleep(0.1)
      self._RedrawScreen()


def main(args):
  # Ensure CSDT is configured to be started by the init process and its current
  # version is running.
  if args.install:
    lib_common.InstallCsdt(args)
    lib_common.ExitCsdt(lib_common.CSDT_EXIT_NORMAL)

  # Set input and output to a physical or serial console, if requested.
  if args.tty:
    lib_common.SetInputOutputDevice(tty_device=args.tty)

  pidfile = lib_common.WritePid()

  try:
    app = curses.wrapper(
        ConsoleDisplayTool,
        tty=args.tty,
        allow_exit=args.allow_exit,
        logfile=args.logfile,
        loglevel=args.loglevel,
        forced_refresh_min_interval=int(args.forced_refresh_min_interval),
        skip_initial_delay=args.skip_initial_delay,
        handle_keys=args.handle_keys)

    for tile_spec in TILES_TO_REGISTER.itervalues():
      app.RegisterTile(**tile_spec)

    app.Run()

  # Exception type being caught here is intentionally broad to hide stack traces
  # and error messages from the application's user interface and write them to
  # a log file instead.
  except Exception as e:  # pylint: disable=broad-except
    pidfile.close()
    ConsoleDisplayTool.RestoreScreenAndExit(exception=e)

  pidfile.close()
  lib_common.ExitCsdt(lib_common.CSDT_EXIT_NORMAL)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--tty', default=None,
      choices=['tty1', 'tty2', 'tty3', 'tty4', 'ttyS0', 'ttyS1'],
      help='TTY to run on.')
  parser.add_argument(
      '--allow_exit', action='store_true',
      help='allow the application to be exited (for testing purposes)')
  parser.add_argument(
      '--logfile', default='/var/log/csdt.log',
      help='location of the log file')
  parser.add_argument(
      '--loglevel', default='info',
      choices=['debug', 'error', 'warning', 'info'],
      help='log level')
  parser.add_argument(
      '--forced_refresh_min_interval', default=30,
      help='minimum interval between forced refresh requests')
  parser.add_argument(
      '--skip_initial_delay', action='store_true',
      help='skip delay before displaying the initial screen')
  parser.add_argument(
      '--handle_keys', action='store_true',
      help='do not handle keypresses')
  parser.add_argument(
      '--install', action='store_true',
      help='add CSDT to /etc/inittab and make init process re-read it')
  parser.add_argument(
      '--inittab_path', default='/etc/inittab',
      help='location of the inittab file')
  parser.add_argument(
      '--csdt_path', default=sys.argv[0],
      help='location of the CSDT application')

  main(parser.parse_args())
