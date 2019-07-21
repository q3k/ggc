"""Console Status Display Tool disk parser library."""

import logging
import re


class Error(Exception):
  """Module level exception."""
  pass


class MegaCLIOutputParseError(Error):
  """Error occurred while parsing MegaCLI output."""
  pass


class HpssacliParseError(Error):
  """Error occurred while parsing HpssaCLI output."""
  pass


class _InvalidDiskCountOutput(MegaCLIOutputParseError):
  """Error occurred while parsing disk count."""
  pass


def MegaCliParseDiskList(output):
  """Parses the output from MegaCLI listing all the disk data.

  Args:
    output: a string containing the output from "MegaCLI -PDList -aALL".

  Raises:
    MegaCLIOutputParseError: if the output string could not be parsed.

  Returns:
    A list of dictionaries containing the extracted data.
  """
  # Lets quickly get rid of those pesky padding lines with just spaces
  output = '\n'.join(s.strip() for s in output.splitlines() if s)

  if 'Adapter #' not in output:
    raise MegaCLIOutputParseError('Invalid MegaCLI Output')
  adapters = output.split('Adapter #')[1:]

  disks = []
  size_pattern = re.compile(
      r'^(?P<size>[0-9]+(\.[0-9]+)?)\s+'
      r'(?P<unit>kb|mb|gb|tb)\s+'
      r'\[(?P<sectors>0x[0-9a-f]+) sectors\]',
      re.IGNORECASE)
  temperature_pattern = re.compile(
      r'(?P<temp_celsius>[0-9]+)C \([0-9]+.[0-9]+ F\)')

  if 'Enclosure Device ID' not in adapters[0]:
    raise MegaCLIOutputParseError('Invalid MegaCLI Output')

  devices = adapters[0].split('Enclosure Device ID')[1:]
  for device in devices:
    # Populate the current disk's details.
    current_disk = {
        'slot': None,
        'media_error': 0,
        'other_error': 0,
        'predictive_failure': 0,
        'firmware_state': '',
        'firmware_secondary_state': '',
        'inquiry': '',
        'size': '',
        'sectors': 0,
        'temperature': None,
    }
    device_lines = device.splitlines()
    for line in device_lines:
      key, _, value = line.partition(':')
      key = key.strip()
      value = value.strip()

      try:
        if key == 'Slot Number':
          current_disk['slot'] = int(value)
        elif key == 'Media Error Count':
          current_disk['media_error'] = int(value)
        elif key == 'Other Error Count':
          current_disk['other_error'] = int(value)
        elif key == 'Predictive Failure Count':
          current_disk['predictive_failure'] = int(value)
        elif key == 'Firmware state':
          primary_state, _, secondary_state = value.partition(',')
          current_disk['firmware_state'] = primary_state.strip()
          current_disk['firmware_secondary_state'] = secondary_state.strip()
        elif key == 'Inquiry Data':
          current_disk['inquiry'] = ' '.join(value.split())
        elif key == 'Raw Size':
          # Extract disk's sector size.
          # The format is <X> GB|TB [<Y> Sectors], where Y is an hex number.
          match = size_pattern.match(value)
          if match:
            current_disk['sectors'] = int(match.group('sectors'), 0)
            disk_size_gb = int(current_disk['sectors'] * 512 / 1000 ** 3)
            if 0 < disk_size_gb < 1000:
              current_disk['size'] = '%d GB' % disk_size_gb
            elif disk_size_gb >= 1000:
              current_disk['size'] = '%d TB' % int(disk_size_gb / 1000)
        elif key == 'Drive Temperature':
          match = temperature_pattern.match(value)
          if match:
            current_disk['temperature'] = int(match.group('temp_celsius'))
      except ValueError:
        logging.exception(
            'Ignoring key %r with unsupported value %r', key, value)
    disks.append(current_disk)
  return disks


def HpParseControllerList(output):
  """Parses output of hpssacli and returns information about controllers.

  Args:
    output: A string containing the output of hpssacli.

  Raises:
    HpssacliParseError: if the output string could not be parsed.

  Returns:
    A list with controller numbers.

  """
  controller_info = []
  output = '\n'.join(s.strip() for s in output.splitlines() if s)
  if 'in Slot' not in output:
    raise HpssacliParseError('Invalid hpssacli Output')
  for line in output.splitlines():
    if 'Slot: ' in line:
      controller_info.append(int(line.split(' ')[1]))
  return controller_info


def HpParseDiskList(output):
  """Parses output of hpssacli to return a list of disks.

  Args:
    output: A string containing the output of hpssacli.

  Raises:
    HpssacliParseError: if the output string could not be parsed.

  Returns:
    A list of dictionaries containing the extracted data.
  """
  output = '\n'.join(s.strip() for s in output.splitlines() if s)
  if 'physicaldrive' not in output:
    raise HpssacliParseError('Invalid hpssacli Output')

  disks = []
  if 'HBA Drives' in output:
    arrays = output.split('HBA Drives')[1:]
  else:
    arrays = output.split('array ')[1:]
  for array in arrays:
    devices = array.split('physicaldrive')[1:]
    for device in devices:
      current_disk = {
          'slot': None,
          'firmware_state': '',
          'inquiry': '',
          'size': '',
          'temperature': None,
          'serial_number': None,
          'predictive_failure': None,
      }
      device_lines = device.splitlines()
      for line in device_lines:
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        try:
          if key == 'Bay':
            current_disk['slot'] = int(value)
          elif key == 'Status':
            current_disk['firmware_state'] = value
          elif key == 'Current Temperature (C)':
            current_disk['temperature'] = value
          elif key == 'Size':
            disk_size_gb = float(value.split(' ')[0])
            if disk_size_gb >= 1000:
              current_disk['size'] = '%d TB' % (disk_size_gb / 1000)
            else:
              current_disk['size'] = '%d GB' % disk_size_gb
          elif key == 'Serial Number':
            current_disk['serial_number'] = value
        except ValueError:
          logging.exception(
              'Ignoring key %r with unsupported value %r', key, value)
      disks.append(current_disk)
  return disks
