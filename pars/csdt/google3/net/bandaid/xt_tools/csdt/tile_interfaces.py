"""Console Status Display Tool interface status tile."""

import logging
import re

from google3.net.bandaid.xt_tools.csdt import lib_ethtool
from google3.net.bandaid.xt_tools.csdt import lib_interfaces
from google3.net.bandaid.xt_tools.csdt import tile


RE_NETWORK_INTERFACE_PATTERN = re.compile(
    r'^(?P<prefix>bond|eth)(?P<index>[0-9]+)$')


class InterfaceStatusTile(tile.InformationTile):
  """Network interfaces information tile."""

  @staticmethod
  def FormatNetworkBandwidth(bandwidth_mbps):
    """Return network interface speed in Mbps or Gbps or '-' if down."""
    if bandwidth_mbps == 0:
      return '-'
    elif bandwidth_mbps < 1000:
      return '%dMbps' % bandwidth_mbps
    else:
      return '%dGbps' % (bandwidth_mbps / 1000)

  @staticmethod
  def GetTileName():
    return 'Network interface status'

  def GetTileData(self):
    tile_data = {}

    interface_statistics = {}
    try:
      interface_statistics = lib_interfaces.GetInterfaceStatisticsFromMachine(
          command_runner=self.runner)
    except lib_interfaces.Error:
      logging.exception('Unable to get interface statistics on this machine.')

    bonding_state = {}
    try:
      bonding_state = lib_interfaces.GetBondingStateFromMachine(
          command_runner=self.runner)
    except lib_interfaces.Error:
      logging.exception('Unable to get bonding state on this machine.')

    ethtool_details = {}
    for interface in interface_statistics.iterkeys():
      ethtool_details[interface] = {}
      ethtool_details[interface] = lib_ethtool.GetNicDetails(
          command_runner=self.runner, device=interface)

    tile_data['interface_statistics'] = interface_statistics
    tile_data['bonding_state'] = bonding_state
    tile_data['ethtool_details'] = ethtool_details
    return tile_data

  def GetTileContent(self, tile_data):
    ethtool_details = tile_data.get('ethtool_details')
    bonding_state = tile_data.get('bonding_state')
    bonding_master = bonding_state.get('master')
    bonding_slaves = bonding_state.get('slaves')

    output = []
    general_info_format = '%-20s: %-21s'

    # General configuration details when LACP is enabled.
    if bonding_master:
      bonding_partner_mac = bonding_state.get('partner_mac', 'Unconfigured')
      bonding_partner_key = bonding_state.get('partner_key', 0)
      bonding_capacity = bonding_state.get('active_capacity_mbps', 0)

      # Header fields of the interface table.
      fields = {
          'interface_name': 'Port',
          'interface_speed': 'Speed',
          'bonding_key': 'Key',
          'interface_status': 'Status',
      }
      # Format of the interface table.
      row_format = (
          '%(interface_name)-4s '
          '%(interface_speed)-8s '
          '%(bonding_key)-6s '
          '%(interface_status)-22s'
      )
      output.append(general_info_format % (
          'LACP partner MAC', bonding_partner_mac))
      output.append(general_info_format % (
          'LACP capacity', self.FormatNetworkBandwidth(bonding_capacity)))
      output.append('')

    # General configuration details when LACP is disabled.
    else:
      # Header fields of the interface table.
      fields = {
          'interface_name': 'Port',
          'interface_speed': 'Speed',
          'interface_status': 'Status',
      }
      # Format of the interface table.
      row_format = (
          '%(interface_name)-4s '
          '%(interface_speed)-8s '
          '%(interface_status)-28s '
      )
      output.append(general_info_format % ('LACP state', 'disabled'))
      output.append('')

    # Add header to the interface table.
    output.append(row_format % fields)

    for interface in sorted(tile_data['interface_statistics'].iterkeys()):
      fields = {}
      match = RE_NETWORK_INTERFACE_PATTERN.match(interface)
      if not match:
        raise ValueError('Unrecognised interface name: %s' % interface)
      # In standalone mode, first network interface is called 'eth0' and needs
      # to be translated to 'Gb1' which is how the actual port is labeled.
      interface_index = int(match.group('index'))
      if not bonding_master:
        interface_index += 1

      fields['interface_name'] = str(interface_index)
      fields['interface_speed'] = self.FormatNetworkBandwidth(
          ethtool_details[interface].get('speed', 0))
      if fields['interface_speed'] in ['1Gbps', '10Gbps', '40Gbps']:
        fields['interface_status'] = '{c.green}UP{c.reset}'.format(
            c=self.color_codes)
      elif fields['interface_speed'] == '-':
        fields['interface_status'] = '{c.red}DOWN{c.reset}'.format(
            c=self.color_codes)
      else:
        fields['interface_status'] = '{c.red}Incorrect speed{c.reset}'.format(
            c=self.color_codes)

      if bonding_master:
        if interface == bonding_master:
          continue  # We don't want to display non-physical interfaces.
        elif interface not in bonding_slaves:
          fields['bonding_key'] = '-'
        else:
          fields['bonding_key'] = bonding_slaves[interface].get('oper_key', '-')

        if fields['bonding_key'] != bonding_partner_key:
          # Only warn about the incorrect LACP key if the link is up.
          if fields['interface_speed'] in ['1Gbps', '10Gbps']:
            fields['interface_status'] = (
                '{c.red}Incorrect LACP key{c.reset}'.format(c=self.color_codes))
          else:
            # Don't show possibly bogus LACP key if the link is down.
            fields['bonding_key'] = '-'
      else:
        fields['bonding_key'] = '-'

      output.append(row_format % fields)

    return '\n'.join([line.rstrip() for line in output])
