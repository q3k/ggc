"""Console Status Display Tool megacli library."""

import logging

from google3.net.bandaid.xt_tools.csdt import lib_commands
from google3.net.bandaid.xt_tools.csdt import lib_disk_parser


MEGACLI_LEGACY_PATHS = [
    '/export/hda3/bandaid/third_party/MegaCli',
    '/usr/local/sbin/MegaCli',
    '/tmp/MegaCli',
]
MEGACLI64_PATHS = [
    '/export/hda3/bandaid/tools/MegaCli64',
]
SMARTCTL_PATHS = [
    '/export/hda3/bandaid/third_party/smartctl',
    '/usr/sbin/smartctl',
]


class Error(lib_disk_parser.Error):
  """Module level exception."""
  pass


class FindPercModelError(Error):
  """Error occurred while getting PERC model."""
  pass


class FindMegaCLIError(Error):
  """Error occurred while finding MegaCLI binary."""
  pass


class FindSmartctlError(Error):
  """Error occurred while finding smartctl binary."""
  pass


class MegaCLIExecutionError(Error):
  """Error occurred while executing MegaCLI command."""
  pass


class MegaCLI(object):
  """MegaCLI interface for accessing the Dell MegaCLI binary.

  Attributes:
    standard_legacy_megacli_locations: list of standard locations legacy MegaCLI
      executables could be at.
    standard_megacli64_locations: list of standard location MegaCLI64
      executables could be at.
  """

  def __init__(self, command_runner):
    """Constructs a MegaCLI object."""
    self.runner = command_runner
    self.megacli_path = None
    self.megacli_version = None
    self.smartctl_path = None
    self._known_megacli_64_path = None
    self._known_legacy_megacli_path = None
    self._known_smartctl_path = None
    self.megacli_legacy_path = MEGACLI_LEGACY_PATHS
    self.megacli_64_path = MEGACLI64_PATHS
    self.smartctl_paths = SMARTCTL_PATHS

  def GetDiskInformation(self):
    """Gets list of dictionaries containing disk information.

    Each dictionary will contain the following keys:
      - slot: the number of the disk slot in which this disk is in (int).
      - scsi_lun: SCSI LUN of a physical disk. If multiple disks are part of a
        RAID group, they will all have the same SCSI LUN (int if MegaCLI64 is
        used, otherwise None).
      - media_error: the number of media errors reported on this disk since
          boot (int).
      - other_error: the number of other errors reported on this disk since
          boot (int).
      - predictive_failure: the number of predictive failures reported for this
          disk since boot (int).
      - last_predictive: the total number of predictive failures on this disk
          before the last boot (int).
      - firmware_state: the state of this disk (str).
      - inquiry: the inquiry string reported by the disk, this is usually the
          disk serial number (str).
      - raw_size: the size of this disk in GB (str).
      - sectors: the number of sectors on this disk (int).
      - temperature: the drive temperature in degrees celcius (int if available,
        otherwise None).


    The order of the dictionaries is based on the output of MegaCLI. The output
    is ordered by slot number.

    Raises:
      MegaCLIExecutionError: If an error occurs while executing MegaCLI.

    Returns:
      A list of dictionaries containing disk information (list).
    """

    try:
      if not self.megacli_path:
        self.megacli_path = self.GetMegaCLIPath()
      command = '%s -PDList -aALL' % self.megacli_path
      result = self.runner.Run(command)
      disk_list = lib_disk_parser.MegaCliParseDiskList(result.output)
      if not disk_list:
        raise lib_disk_parser.MegaCLIOutputParseError(
            'No disk information found.')
      self._DeleteMegasasLog()
      for disk in disk_list:
        disk['serial_number'] = self.GetDiskSerialNumberFromSmartctl(
            disk['slot'])
      return disk_list
    except lib_commands.Error as e:
      logging.exception(e)
      raise MegaCLIExecutionError(e)

  def GetDiskSerialNumberFromSmartctl(self, slot):
    """Get disk serial number from S.M.A.R.T.

    This is necessary since megacli only returns an 'inquiry' field which
    contains a random combination of serial number, disk model, manufacturer and
    firmware version.

    Args:
      slot: physical disk slot number (int).

    Returns:
      Disk serial number (str) or None if not available.
    """
    if not self.smartctl_path:
      try:
        self.smartctl_path = self.GetSmartctlPath()
      except FindSmartctlError:
        return None
    command = '%s /dev/bus/0 -d megaraid,%s -i' % (
        self.smartctl_path, str(slot))
    try:
      logging.debug(command)
      result = self.runner.Run(command)
    except lib_commands.Error:
      logging.warning('Error getting serial number of a disk in slot %d.', slot)
      return None

    for line in result.output.splitlines():
      fields = line.split(':')
      if fields[0].strip().lower() == 'serial number':
        return fields[1].strip()
    logging.warning('Unable to get serial number of a disk in slot %d.', slot)
    return None

  def GetPercModels(self):
    """Gets the Perc Model(s) on the machine by running lspci.

    Raises:
        lib_commands.Error: Error while executing LSPCI.
        lib_disk_parser.ParsingError: Error while parsing MegaCLI output.

    Returns:
        List of strings describing the Perc Models of the current machine.
    """

    try:
      command = 'lspci -vmm'
      result = self.runner.Run(command)
    except lib_commands.Error:
      logging.exception('Error executing lspci to get Hardware Information.')
      raise

    device_array = result.output.strip().split('\n\n')
    raid_controllers = [device for device in device_array
                        if 'RAID bus controller' in device]

    if not raid_controllers:
      raise lib_disk_parser.ParsingError(
          'Could not find RAID bus controller from lspci output.')

    perc_models = []
    for controller in raid_controllers:
      raid_controller_info = controller.split('\n')
      for line in raid_controller_info:
        try:
          key, val = line.split(':\t', 1)
        except ValueError:
          continue
        if key == 'SDevice':
          perc_models.append(val.strip())
          logging.debug('Perc Model found: %s', val.strip())
          break
    return perc_models

  def GetMegaCLIPath(self):
    """Get the Path of MegaCLI to use.

    Newer versions of MegaCLI do not work with the old 6/i Perc Models. It
    causes an increment in harmless "Other" errors on the disks.
    Therefore we should use the Legacy MegaCLI version on machines that use 6/i
    Percs.
    The new MegaCLI version works fine on all newer hardware.

    See: http://b/14999235 for more information.

    Raises:
      FindMegaCLIError: If the user specified MegaCLI executable cannot be found
                        or if MegaCLI executables cannot be found in default
                        locations.
      FindPercModelError: If no Perc MOdel is found from lspci output.

    Returns:
      String of path to MegaCLI path.
        MegaCLI path maybe overridden if the user manually specifies
        a path via flags.
    """
    perc_models = self.GetPercModels()
    if not perc_models:
      logging.warning('Got a None for Perc Model')
      raise FindPercModelError('No PERC Raid Controllers '
                               'found from lspci output.')
    elif 'PERC 6/i Integrated RAID Controller' in perc_models:
      logging.debug('Matched with 6/i Perc, using Legacy MegaCLI Path')
      return self.GetLegacyMegaCLIPath()
    else:
      logging.debug('Matched newer Perc Model')
      try:
        return self.GetMegaCLI64Path()
      except FindMegaCLIError:
        return self.GetLegacyMegaCLIPath()

  def GetLegacyMegaCLIPath(self):
    """Gets the path of the Legacy MegaCLI binary.

    Checks all known standard locations of Legacy MegaCLI.
    If we cannot find MegaCLI at any of them, we raise an error.

    Raises:
      FindMegaCLIError: If we cannot find a MegaCLI in any of the known
        locations.

    Returns:
      String: path to Legacy MegaCLI binary.

    """
    if self._known_legacy_megacli_path:
      logging.debug('We have a known good legacy MegaCLI path: %s',
                    self._known_legacy_megacli_path)
      return self._known_legacy_megacli_path

    for path in self.megacli_legacy_path:
      if self._CheckFileExists(path):
        logging.debug('Using Legacy MegaCLI found at %s', path)
        self._known_legacy_megacli_path = path
        return path
      logging.warning('Legacy MegaCLI not found at %s', path)

    error_message = 'Could not find any legacy MegaCLI executable: %s' % (
        self.megacli_legacy_path)
    logging.error(error_message)
    raise FindMegaCLIError(error_message)

  def GetMegaCLI64Path(self):
    """Gets the path of the MegaCLI64 binary.

    Go through the list of known MegaCLI64 locations. See if we can find the
    executable there.

    Raises:
      FindMegaCLIError: If we cannot find a MegaCLI at this location.

    Returns:
      String: path to MegaCLI64 binary.

    """
    if self._known_megacli_64_path:
      logging.debug('We have a known good MegaCLI 64 path: %s',
                    self._known_megacli_64_path)
      return self._known_megacli_64_path

    for path in self.megacli_64_path:
      if self._CheckFileExists(path):
        logging.debug('Using MegaCLI64 found at %s', path)
        self._known_megacli_64_path = path
        return path
      logging.warning('MegaCLI 64 not found at %s', path)

    error_message = 'Could not find any MegaCLI64 executables at: %s' % (
        self.megacli_64_path)
    logging.error(error_message)
    raise FindMegaCLIError(error_message)

  def GetSmartctlPath(self):
    """Gets the path of the smartctl binary.

    Raises:
      FindSmartctlError: If the smartctl binary isn't found at any location.

    Returns:
      Path to the smartctl binary (str).
    """
    if self._known_smartctl_path:
      logging.debug('We have a known good smartctl path: %s',
                    self._known_smartctl_path)
      return self._known_smartctl_path

    for path in self.smartctl_paths:
      if self._CheckFileExists(path):
        logging.debug('Using smartctl found at %s', path)
        self._known_smartctl_path = path
        return path
      logging.debug('smartctl not found at %s', path)
    raise FindSmartctlError(
        'Could not find any smartctl executables at: %s' % self.smartctl_paths)

  def _CheckFileExists(self, path):
    try:
      command = 'test -e %s' % path
      result = self.runner.Run(command)
      if result.exit_code == 0:
        return True
    except lib_commands.Error:
      pass
    return False

  def _DeleteMegasasLog(self):
    if self._CheckFileExists('MegaSAS.log'):
      command = 'rm MegaSAS.log'
      try:
        self.runner.Run(command)
      except lib_commands.Error:
        pass
