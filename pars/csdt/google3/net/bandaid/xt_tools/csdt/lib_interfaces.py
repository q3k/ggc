"""Console Status Display Tool network interface library."""

import collections
import glob
import logging
import os
import re

from google3.net.bandaid.xt_tools.csdt import lib_commands


class Error(Exception):
  pass


class BondingModuleNotLoadedError(Error):
  pass


class BondingModuleNotConfiguredError(Error):
  pass


class BondingModuleHasMultipleMastersError(Error):
  pass


def CheckIfInProdimage():
  """Check if we're running in the prodimage, vs the install environment."""
  return os.path.isfile('/.bandaid-image')


def GetBondingMasterFromMachine(command_runner):
  """Get the active bonding master interface on a given machine.

  Args:
    command_runner: lib_commands.CommandRunner instance.

  Returns:
    Active bonding master interface (str). Examples:
      - "eth0" (GLAG in the prodimage)
      - "bond0" (GLAG init in the prodimage or LACP in the installer)

  Raises:
    BondingModuleNotLoadedError: Bonding module not loaded.
    BondingModuleNotConfiguredError: Bonding module not configured.
    BondingModuleHasMultipleMastersError: Bonding module has multiple
        active masters.
  """
  try:
    command = 'ls -1 /proc/net/bonding'
    result = command_runner.Run(command)
    bonding_masters = result.output.strip().split()
    if result.exit_code:
      raise BondingModuleNotLoadedError(
          'Unsupported machine state: bonding module not loaded')
  except lib_commands.Error as e:
    logging.exception(e)

  if not bonding_masters:
    raise BondingModuleNotConfiguredError(
        'Unsupported machine state: bonding module not configured')

  if len(bonding_masters) != 1:
    raise BondingModuleHasMultipleMastersError(
        'Unsupported machine state: bonding module has multiple masters')

  # b/33128065  prodimage has a bond0 device present even when bonding is not
  # enabled; when it is enabled it is actually eth0.
  if CheckIfInProdimage() and bonding_masters[0] == 'bond0':
    raise BondingModuleNotConfiguredError(
        'Unsupported machine state: bonding not enabled')

  return bonding_masters[0]


def GetBondingStateFromMachine(
    command_runner, line_separator='\n', block_separator='\n\n',
    key_value_separator=': '):
  """Get the current bonding state on a machine.

  Args:
    command_runner: lib_commands.CommandRunner instance.
    line_separator: Line separator used in /proc/net/bonding (str).
    block_separator: Block separator used in /proc/net/bonding (str).
    key_value_separator: Key value separator used in /proc/net/bonding (str).

  Returns:
    Dictionary containing the current bonding state. Example:
      {
          'mode': 'IEEE 802.3ad Dynamic link aggregation',
          'master': 'eth0',
          'slaves': {
              'eth1': {
                  'link_speed_mbps': 1000,
                  ...
              },
              'eth2': {
                  'link_speed_mbps': 1000,
                  ...
              },
              ...
          },
          'active_members': ['eth1', 'eth2'],
          'active_capacity_mbps': 2000,
          ...
      }

  Raises:
    ValueError: Unsupported value in /proc/net/bonding.
      This should not happen and would indicate an unsupported format, typically
      caused by a new kernel version. Please file a bug.
  """
  bonding_master = GetBondingMasterFromMachine(command_runner=command_runner)

  bonding_state = {}
  bonding_state['master'] = bonding_master
  bonding_state['slaves'] = {}

  try:
    with open(os.path.join('/proc/net/bonding', bonding_master)) as fh:
      bonding_data = fh.read().strip()
  except IOError:
    logging.error('Unable to read bonding configuration.')
    return bonding_state

  for block in bonding_data.split(block_separator):
    block_header, unused_sep, block_data = block.partition(line_separator)
    block_header = block_header.strip()

    # Bonding mode and master state.
    if block_header.startswith('Bonding Mode'):
      unused_key, unused_sep, bonding_mode = (
          block_header.partition(key_value_separator))
      if not bonding_mode:
        raise ValueError('Missing bonding mode: %r' % block_header)
      bonding_state['mode'] = bonding_mode

      for line in block_data.splitlines():
        line = line.strip()
        key, unused_sep, value = line.partition(key_value_separator)
        if key == 'MII Status':
          bonding_state['mii_status'] = value.lower()
        elif key == 'Active Members':
          bonding_state['active_members'] = value.split()
        elif key == 'Active Capacity (Mb/s)':
          bonding_state['active_capacity_mbps'] = int(value)

    # LACP state.
    elif block_header.startswith('802.3ad info'):
      for line in block_data.splitlines():
        line = line.strip()
        key, unused_sep, value = line.partition(key_value_separator)
        if key == 'Partner Mac Address':
          bonding_state['partner_mac'] = value.upper()
        elif key == 'Partner Key':
          bonding_state['partner_key'] = int(value)
        elif key == 'Aggregator ID':
          bonding_state['aggregator_id'] = int(value)

    # Slave interface state.
    elif block_header.startswith('Slave Interface'):
      unused_key, unused_sep, slave = (
          block_header.partition(key_value_separator))
      if not slave:
        raise ValueError('Missing slave: %r' % block_header)
      if slave in bonding_state['slaves']:
        raise ValueError('Duplicate slave: %r' % slave)

      slave_state = {}
      for line in block_data.splitlines():
        line = line.strip()
        key, unused_sep, value = line.partition(key_value_separator)
        if key == 'MII Status':
          slave_state['mii_status'] = value.lower()
        elif key == 'Speed':
          # Handle known bogus speeds for down interfaces depending on driver:
          # 65535 Mbps (16 bit: 2**16-1) or 4294967295 Mbps (32 bit: 2**32-1).
          if value in ['Unknown', '65535 Mbps', '4294967295 Mbps']:
            slave_state['link_speed_mbps'] = 0
            continue
          value, unused_sep, unit = value.partition(' ')
          if unit == 'Mbps':
            slave_state['link_speed_mbps'] = int(value)
          else:
            raise ValueError('Unsupported slave speed unit: %r' % line)
        elif key == 'Duplex':
          slave_state['duplex'] = value.lower()
        elif key == 'Link Failure Count':
          slave_state['link_flaps'] = int(value)
        elif key == 'oper key':
          slave_state['oper_key'] = int(value)
        elif key == 'Aggregator ID':
          slave_state['aggregator_id'] = int(value)
      bonding_state['slaves'][slave] = slave_state

  # Upstream /proc/net/bonding/* (non-GLAG as found on the installer)
  # does not report active members. Derive using slave aggregator id.
  if bonding_state.get('active_members') is None:
    active_members = []
    bond_aggregator_id = bonding_state.get('aggregator_id')
    for slave, slave_state in bonding_state['slaves'].iteritems():
      slave_aggregator_id = slave_state.get('aggregator_id')
      if slave_aggregator_id == bond_aggregator_id:
        active_members.append(slave)
    active_members.sort()
    bonding_state['active_members'] = active_members

  # Upstream /proc/net/bonding/* (non-GLAG as found on the installer)
  # does not report active capacity. Sum up all active slave link speeds.
  if bonding_state.get('active_capacity_mbps') is None:
    bonding_state['active_capacity_mbps'] = 0
    for active_member in bonding_state.get('active_members'):
      slave_state = bonding_state['slaves'].get(active_member)
      if slave_state is not None:
        slave_link_speed_mbps = slave_state.get('link_speed_mbps')
        if slave_link_speed_mbps is not None:
          bonding_state['active_capacity_mbps'] += slave_link_speed_mbps

  return bonding_state


def GetInterfaceStatisticsFromMachine(command_runner):
  """Parse /sys/class/net/*/statistics and return interface statistics.

  Args:
    command_runner: lib_commands.CommandRunner instance.

  Returns:
    Dictionary containing statistics for all interfaces:
      {
          'eth0': {'rx_bytes': 123, 'tx_bytes': 123, ...},
          'eth1': {'rx_bytes': 123, 'tx_bytes': 123, ...},
          'eth2': {'rx_bytes': 123, 'tx_bytes': 123, ...},
          ...
      }

  Raises:
    ValueError: Unsupported value in /sys/class/net/*/statistics.
      This should not happen and would indicate an unsupported format,
      typically caused by a new kernel version. Please file a bug.
  """
  statistics_files = glob.glob('/sys/class/net/*/statistics')
  command = r'grep -Hrx "[0-9]\+" %s' % ' '.join(statistics_files)
  result = command_runner.Run(command)
  interface_data = result.output.strip()
  interface_stats = collections.defaultdict(dict)
  for match in re.finditer(
      r'^/sys/class/net/(?P<interface>(?:bond|eth)\d+)/statistics/'
      r'(?P<key>.+):(?P<value>\d+)$', interface_data, re.MULTILINE):
    interface = match.group('interface')

    # b/33128065  prodimage has a bond0 device present even when bonding is not
    # enabled; when it is enabled it is actually eth0.
    if CheckIfInProdimage() and interface == 'bond0':
      continue
    key = match.group('key')
    value = match.group('value')
    interface_stats[interface][key] = int(value)
  return interface_stats
