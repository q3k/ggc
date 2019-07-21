"""Console Status Display Tool tile base class."""

import logging
import time

from google3.net.bandaid.xt_tools.csdt import lib_colors
from google3.net.bandaid.xt_tools.csdt import lib_commands
from google3.net.bandaid.xt_tools.csdt import lib_common


class Error(Exception):
  pass


class InformationTile(object):
  """Base class for information tiles displayed by CSDT."""

  def __init__(self, color_mode=None):
    """Initialise CSDT tile and populate shared details.

    Args:
      color_mode: Color mode (one of lib_colors.COLOR_MODE_*).
    """
    if color_mode:
      self.color_mode = color_mode
    else:
      self.color_mode = lib_colors.COLOR_MODE_ANSI
    self.color_codes = lib_colors.GetColorCodes(self.color_mode)

    self.tile_name = self.GetTileName()
    self.refresh_timestamp = 0
    self.refresh_interval = 300

    # Set up variables useful to multiple tiles.
    self.runner = lib_commands.CommandRunner()

    self.hostname = None
    self.service_tag = None
    self.hardware_model = None

    self.ipv4_interface = None
    self.ipv4_address = None
    self.ipv4_gateway = None

    self.ipv6_interface = None
    self.ipv6_address = None
    self.ipv6_gateway = None

  def RefreshCommonTileData(self):
    """Refresh common tile data used by several tiles."""
    self.hostname = lib_common.GetHostname(command_runner=self.runner)
    self.service_tag = lib_common.GetServiceTag()
    self.hardware_model = lib_common.GetHardwareModel()

    ipv4_configuration = lib_common.GetNetworkConfiguration(
        command_runner=self.runner, ip_version=4)
    ipv6_configuration = lib_common.GetNetworkConfiguration(
        command_runner=self.runner, ip_version=6)

    if ipv4_configuration:
      self.ipv4_interface = ipv4_configuration[0]
      self.ipv4_address = ipv4_configuration[1]
      self.ipv4_gateway = ipv4_configuration[2]
    else:
      self.ipv4_interface = None
      self.ipv4_address = None
      self.ipv4_gateway = None

    if ipv6_configuration:
      self.ipv6_interface = ipv6_configuration[0]
      self.ipv6_address = ipv6_configuration[1]
      self.ipv6_gateway = ipv6_configuration[2]
    else:
      self.ipv6_interface = None
      self.ipv6_address = None
      self.ipv6_gateway = None

  @staticmethod
  def DisplayTileName():
    """Return True if tile name should be displayed on the tile's first line."""
    return True

  def GetSecondsUntilRefresh(self):
    """Get the number of seconds until next data refresh."""
    seconds_to_refresh = int(
        self.refresh_interval - (time.time() - self.refresh_timestamp))
    if seconds_to_refresh > 0:
      return seconds_to_refresh
    return 0

  def GetRefreshInterval(self):
    """Get the minimum number of seconds between data refreshes."""
    return self.refresh_interval

  def UpdateRefreshTimestamp(self):
    self.refresh_timestamp = time.time()
    logging.debug('Updated refresh_timestamp with \'%s\'', self.GetTileName())

  def IsRefreshRequired(self):
    """Check if tile's content refresh is required."""
    return self.GetSecondsUntilRefresh() == 0

  def GetContent(self):
    """Refresh common tile data and return tile content to be displayed."""
    self.RefreshCommonTileData()
    try:
      return self.GetTileContent(tile_data=self.GetTileData())
    # This is to allow tiles to show custom errors when it is beneficial for
    # the CSDT user to see them.
    except Error as exception:
      return exception.message
    # Exception type being caught here is intentionally broad to hide stack
    # traces and unforeseen error messages from individual tiles and write them
    # to a log file instead.
    except Exception:  # pylint: disable=broad-except
      logging.exception('Failed to refresh tile: \'%s\':', self.GetTileName())
    return 'No data to display'

  @staticmethod
  def GetTileName():
    """Get tile name to be displayed in the list of tiles."""
    raise NotImplementedError

  def GetTileData(self):
    """Return the tile's data dictionary."""
    raise NotImplementedError

  def GetTileContent(self, tile_data):
    """Return the tile's content to be displayed."""
    raise NotImplementedError
