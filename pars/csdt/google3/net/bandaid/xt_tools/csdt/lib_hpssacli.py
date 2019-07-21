"""Console Status Display Tool hpssacli library."""
# TODO(http://b/36903097): achieve functionality parity with lib_megacli.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

from google3.net.bandaid.xt_tools.csdt import lib_commands
from google3.net.bandaid.xt_tools.csdt import lib_disk_parser


HPSSACLI_PATH = '/export/hda3/bandaid/tools/hpssacli'


class Error(lib_disk_parser.Error):
  """Module level exception."""
  pass


class HpssacliExecutionError(Error):
  """Error occurred while executing hpssacli command."""
  pass


class Hpssacli(object):
  """Interface for accessing the HPE hpssacli interface."""

  def __init__(self, command_runner):
    """Constructs a Hpssacli object."""
    self.runner = command_runner
    self.hpssacli_path = HPSSACLI_PATH

  def GetControllerInformation(self):
    try:
      command = ('%s controller all show detail' % self.hpssacli_path)
      result = self.runner.Run(command)
    except lib_commands.Error as e:
      logging.exception(e)
      raise HpssacliExecutionError(e)
    controllers = lib_disk_parser.HpParseControllerList(result.output)
    return controllers

  def GetDiskInformation(self):
    """Gets list of dictionaries containing disk information.

    Each dictionary will contain the following keys:
      - slot: the number of the disk slot in which this disk is in (int).
      - firmware_state: the state of this disk (str).
      - inquiry: Currently hard-coded to 0.
      - size: the size of this disk in GB|TB (str).
      - temperature: the drive temperature in degrees celcius
          (int if available, otherwise None).
      - serial_number: Disk serial number as reported by hpssacli.
      - predictive_failure: Currently hard-coded to 0.

    Raises:
      HpssacliExecutionError: If an error occurs while executing hpssacli.

    Returns:
      A list of dictionaries containing disk information (list).
    """

    all_disks = []
    for controller in self.GetControllerInformation():
      try:
        command = (
            '%s controller slot=%d pd all show detail' % (
                self.hpssacli_path, controller))
        result = self.runner.Run(command)
      except lib_commands.Error as e:
        logging.exception('Error getting disk information')
        raise HpssacliExecutionError(e)
      disk_list = lib_disk_parser.HpParseDiskList(result.output)
      all_disks += disk_list
    return all_disks
