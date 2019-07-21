"""Console Status Display Tool common library."""

from __future__ import print_function

import fcntl
import logging
import os
import re
import shutil
import sys

from google3.net.bandaid.xt_tools.csdt import lib_commands

CSDT_EXIT_NORMAL = 0
CSDT_EXIT_EXCEPTION = 1
CSDT_EXIT_ALREADY_RUNNING = 2
CSDT_EXIT_PIDFILE_OPEN_ERROR = 3
CSDT_EXIT_INITTAB_NOT_FIXED = 4
CSDT_PIDFILE_PATH = '/var/run/csdt.pid'

RE_IPV4_ADDRESS = r'([0-9]{1,3}\.){3}[0-9]{1,3}'
RE_IPV6_ADDRESS = r'[0-9a-fA-F:]{3,}'


class Error(Exception):
  pass


def ExitCsdt(exit_code, message=None):
  """Exit CSDT and optionally display a message."""
  if message:
    if exit_code:
      fd = sys.stderr
    else:
      fd = sys.stdout
    fd.write(message)
    fd.flush()
  sys.exit(exit_code)


def GetPid():
  """Get PID of the currently running CSDT instance.

  Returns:
    Process ID number (int) if CSDT is running or None otherwise.
  """
  try:
    with open(CSDT_PIDFILE_PATH, 'r') as fd:
      try:
        # Attempt to obtain an exclusive, non-blocking lock.
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except IOError:
        try:
          return int(fd.read())
        except ValueError:
          pass
  except IOError:
    pass
  return None


def WritePid(pidfile_path=None):
  """Write current PID of CSDT.

  Attempt to open a pidfile and obtain an exclusive, non-blocking lock on it or
  exit upon failure.

  Args:
    pidfile_path: Path to the PID file (str).

  Returns:
    File descriptor of a PID file upon successfully writing the PID.
  """
  pidfile_path = pidfile_path if pidfile_path else CSDT_PIDFILE_PATH

  try:
    fd = open(pidfile_path, 'w')
  except IOError:
    ExitCsdt(
        CSDT_EXIT_PIDFILE_OPEN_ERROR,
        'Unable to open PID file %s\n' % pidfile_path)

  try:
    # Attempt to obtain an exclusive, non-blocking lock.
    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except IOError:
    ExitCsdt(
        CSDT_EXIT_PIDFILE_OPEN_ERROR,
        'Unable to obtain an exclusive lock on a PID file %s.\n'
        'Another CSDT instance is still running.\n' % pidfile_path)
  fd.write(str(os.getpid()))
  fd.flush()
  return fd


def SetInputOutputDevice(tty_device):
  """Set input and output to a physical or serial console, if requested.

  Additionally, prevent console from being blanked after a timeout.

  Args:
    tty_device: TTY device name, such as ttyN (str).
  """
  if not tty_device:
    return

  tty_device_path = '/dev/%s' % tty_device
  with open(tty_device_path, 'rb') as input_device:
    with open(tty_device_path, 'wb') as output_device:
      os.dup2(input_device.fileno(), 0)
      os.dup2(output_device.fileno(), 1)
      os.dup2(output_device.fileno(), 2)

      command_runner = lib_commands.CommandRunner()
      command = 'setterm -term linux -blank 0'
      try:
        result = command_runner.Run(
            command, stdin=input_device, stdout=output_device)
        if result.exit_code:
          logging.warning('Unable to disable console blanking with `setterm`.')
      except lib_commands.Error:
        logging.warning('Failed to run `setterm` to disable console blanking.')


def InstallCsdt(csdt_args):
  """Install CSDT in /etc/inittab and ensure the current version is running.

  Args:
    csdt_args: Instance of argparse.ArgumentParser.
  """
  csdt_command_args = []
  inittab_entry_fields = []

  csdt_command_args.append(csdt_args.csdt_path)

  if csdt_args.tty:
    csdt_command_args.append('--tty %s' % csdt_args.tty)

  if csdt_args.allow_exit:
    csdt_command_args.append('--allow_exit')

  csdt_command_args.append('--logfile %s' % csdt_args.logfile)
  csdt_command_args.append('--loglevel %s' % csdt_args.loglevel)
  csdt_command_args.append(
      '--forced_refresh_min_interval %s' %
      csdt_args.forced_refresh_min_interval)

  if csdt_args.skip_initial_delay:
    csdt_command_args.append('--skip_initial_delay')

  if csdt_args.handle_keys:
    csdt_command_args.append('--handle_keys')

  csdt_command_line = ' '.join(csdt_command_args)

  # Inittab entry identifier. Has to be unique within the inittab file.
  inittab_entry_fields.append('csdt')
  # Runlevels during which to keep CSDT running.
  inittab_entry_fields.append('2345')
  # CSDT should be respawned when it terminates for any reason.
  inittab_entry_fields.append('respawn')
  # CSDT command line.
  inittab_entry_fields.append(csdt_command_line)

  inittab_entry = ':'.join(inittab_entry_fields)

  print('Ensuring CSDT is present in /etc/inittab.')
  with open(csdt_args.inittab_path, 'r+') as file_handle:
    _EnsureLineExistsInFile(
        file_handle=file_handle,
        expected_line=inittab_entry,
        search_pattern=r'^csdt:.*$')

  # Only restart CSDT if we're modifying the real inittab.
  if csdt_args.inittab_path == '/etc/inittab':
    print('Re-reading /etc/inittab.')
    command_runner = lib_commands.CommandRunner()
    _EnsureCurrentCsdtVersionIsRunning(command_runner)


def _EnsureLineExistsInFile(file_handle, expected_line, search_pattern):
  """Ensure file contains the expected line exactly once and fix it otherwise.

  Args:
    file_handle: Instance of opened file.
    expected_line: Expected line. Will be added if missing or corrected if
        only partially matching (str).
    search_pattern: Regular expression pattern of line to replace with the
        expected line. This is to ensure only one matching line is present
        (str).
  """
  file_handle.seek(0)
  input_file_lines = [line.strip() for line in file_handle.readlines()]
  output_file_lines = []

  expected_line_present = False
  pattern = re.compile(search_pattern)

  for line in input_file_lines:
    if line == expected_line:
      return
    else:
      if re.search(pattern, line):
        if not expected_line_present:
          output_file_lines.append(expected_line)
          expected_line_present = True
      else:
        output_file_lines.append(line)

  if not expected_line_present:
    output_file_lines.append(expected_line)

  # Abort if the difference in number of lines of the original and modified
  # file is greater than one as a safety precaution.
  if abs(len(input_file_lines) - len(output_file_lines)) > 1:
    ExitCsdt(
        CSDT_EXIT_INITTAB_NOT_FIXED,
        'More than one line in %s is being modified. Aborting.\n' %
        file_handle.name)
  try:
    with open(file_handle.name + '.new', 'w') as modified_file:
      modified_file.write('\n'.join(output_file_lines))
  except IOError:
    ExitCsdt(
        CSDT_EXIT_INITTAB_NOT_FIXED,
        'Unable to write to %s. Aborting.\n' %
        file_handle.name + '.new')

  try:
    shutil.copy(file_handle.name, file_handle.name + '.orig')
  except IOError:
    ExitCsdt(
        CSDT_EXIT_INITTAB_NOT_FIXED,
        'Unable to write backup content to %s. Aborting.\n' %
        file_handle.name + '.orig')
  try:
    shutil.move(file_handle.name + '.new', file_handle.name)
  except IOError:
    ExitCsdt(
        CSDT_EXIT_INITTAB_NOT_FIXED,
        'Unable to rename %s to %s. Aborting.\n' % (
            file_handle.name + '.new', file_handle.name))


def _EnsureCurrentCsdtVersionIsRunning(command_runner):
  """Re-read /etc/inittab and kill any CSDT processes spawned by init."""

  try:
    # Re-reading inittab isn't going to spawn another instance of CSDT, since
    # only one may be running at any given time, thus we still have an instance
    # that's running at this point and we have a chance to clean up its STDOUT
    # and kill it thereafter.
    command_runner.Run('telinit q')
  except lib_commands.Error:
    pass
  pid = GetPid()
  if pid:
    # Clear STDOUT currently in use by CSDT to avoid confusing users with
    # stale output after the application has terminated.
    try:
      with open('/proc/%d/fd/0' % pid, 'w') as stdout_device:
        stdout_device.write('\033c')
    except IOError:
      pass
    # Ask currently running CSDT to die and allow init to respawn it.
    try:
      os.kill(pid, 1)
    except OSError:
      pass


def GetHostname(command_runner):
  """Get short hostname of a machine."""
  command = 'hostname --short'
  result = command_runner.Run(command)
  return result.output.strip()


def GetUptime():
  """Get uptime of a machine.

  Returns:
    Uptime as a human-friendly string (eg: 35 days, 2:11 hours).
  """
  with open('/proc/uptime', 'r') as f:
    uptime_seconds = int(float(f.read().split()[0]))

    days = uptime_seconds / 86400
    uptime_seconds -= days * 86400

    hours = uptime_seconds / 3600
    uptime_seconds -= hours * 3600

    minutes = uptime_seconds / 60

  return '%d days, %d:%02d hours' % (days, hours, minutes)


def GetServiceTag():
  """Get service tag of a machine."""
  service_tag = ''
  try:
    with open('/sys/class/dmi/id/product_serial', 'r') as file_handle:
      service_tag = file_handle.read().strip()
  except IOError:
    logging.error('Unable to read the service tag.')
  return service_tag or 'Unknown'


def GetHardwareModel():
  """Get hardware model of a machine."""
  hardware_models = {
      'Dell R440': [
          'PowerEdge R440',
      ],
      'Dell R430': [
          'PowerEdge R430',
      ],
      'Dell R630': [
          'PowerEdge R630',
      ],
      'Dell R640': [
          'PowerEdge R640',
      ],
      'Dell R710': [
          'PowerEdge R710',
      ],
      'Dell R720': [
          'OEM-R 720xd',
          'PowerEdge R720',
          'PowerEdge R720xd',
      ],
      'Dell R730': [
          'PowerEdge R730xd',
      ],
      'Dell R740': [
          'PowerEdge R740xd',
      ],
      'HP Apollo 4200': [
          'ProLiant XL420 Gen9',
      ]
  }
  product_name = ''
  try:
    with open('/sys/class/dmi/id/product_name', 'r') as file_handle:
      product_name = file_handle.read().strip()
  except IOError:
    logging.error('Unable to read the product name.')
  logging.debug('Product name: %s', product_name)

  for hardware_model, product_names in hardware_models.iteritems():
    if product_name in product_names:
      return hardware_model
  return 'Unknown'


def GetNetworkConfiguration(command_runner, ip_version=4):
  """Get the network interface configuration for a machine.

  Args:
    command_runner: Instance of lib_commands.CommandRunner().
    ip_version: IP protocol version (int).

  Raises:
    Error: If details for an invalid IP version are requested.

  Returns:
    If network configuration for a given IP version is present, a tuple with the
    following indices:

      Network interface name (str).
      IP address of the machine (str)
      IP address of the gateway (str)

    Otherwise None.
  """
  if ip_version == 4:
    command = 'ip -4 route get 8.8.8.8'
    pattern_default_route = re.compile(
        r'^\s*8\.8\.8\.8\s+'
        r'.*'
        r'via\s+(?P<ip_gateway>%s)\s+'
        r'.*'
        r'dev\s+(?P<interface>[a-zA-Z]+\d+)\s+'
        r'.*'
        r'src\s+(?P<ip_machine>%s)\s*' % (RE_IPV4_ADDRESS, RE_IPV4_ADDRESS))
  elif ip_version == 6:
    command = 'ip -6 route get 2001:4860:4860::8888'
    pattern_default_route = re.compile(
        r'^2001:4860:4860::8888\s+'
        r'.*'
        r'via\s+(?P<ip_gateway>%s)\s+'
        r'.*'
        r'dev\s+(?P<interface>[a-zA-Z]+\d+)\s+'
        r'.*'
        r'(proto ra)?\s+'
        r'.*'
        r'src\s+(?P<ip_machine>%s)\s*' % (RE_IPV6_ADDRESS, RE_IPV6_ADDRESS))
  else:
    raise Error('Incorrect IP protocol version supplied.')

  result = command_runner.Run(command)
  for line in result.output.splitlines():
    match = pattern_default_route.search(line)
    if match:
      return (
          match.group('interface'),
          match.group('ip_machine'),
          match.group('ip_gateway'),
      )
  logging.warning('Unable to parse iproute output:\n%s', result.output)
  return None
