# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/ifconfig.py
# Compiled at: 2019-06-18 16:41:38
"""Network interface identification and manipulation."""
__author__ = 'lducazu@google.com (Luc Ducazu)'
import array
import errno
import fcntl
import logging
import os
import re
import socket
import struct
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils
SIOCGIFFLAGS = 35091
SIOCSIFFLAGS = 35092
SIOCGIFHWADDR = 35111
SIOCETHTOOL = 35142
IFF_UP = 1
AF_UNIX = 1
AF_INET = 2
ETHTOOL_GSET = 1
ADVERTISED_FIBRE = 1024
ADVERTISED_10000baseT_Full = 4096
ADVERTISED_10000baseKX4_Full = 262144
ADVERTISED_10000baseKR_Full = 524288
ADVERTISED_10000baseR_FEC = 1048576
ADVERTISED_40000baseKR4_Full = 8388608
ADVERTISED_40000baseCR4_Full = 16777216
ADVERTISED_40000baseSR4_Full = 33554432
ADVERTISED_40000baseLR4_Full = 67108864
MLX_LINK_TYPE_INFINIBAND = 1
MLX_LINK_TYPE_ETHERNET = 2
MLX_LINK_TYPE_AUTO = 3

class NetworkInterface(object):
    """Extends Interface - provides additional link info.
    
       class Interface provides link detection info in
         * get_link_info()
       class NetworkInterface provides
         * supports_10_ge - True if the interface is able to run @ 10 Gbps
         * fibre_port - True if the port type is actually fibre
    
       See also: ethtool source code
         https://www.kernel.org/pub/software/network/ethtool/
    """
    PORT_TYPE_FIBRE = 3
    INDEX_ONBOARD_MIN = 0
    INDEX_ONBOARD_MAX = 16776192
    INDEX_UNKNOWN = 16777215
    INDEX_ADDON_MIN = 16777216
    _sock = None

    def __new__(cls, *args, **kwargs):
        if not cls._sock:
            try:
                cls._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            except socket.error as e:
                if e.errno != errno.EAFNOSUPPORT:
                    raise
                cls._sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)

        return super(NetworkInterface, cls).__new__(cls, *args, **kwargs)

    def __init__(self, name, root='/'):
        """Initialize NetworkInterface object.
        
        Args:
          name: interface name (str).
          root: where to look for sysfs.
        """
        self.name = name
        self.vendor_id = self._get_vendor_id(root)
        self.supports_40_ge, self.supports_10_ge, self.fibre_port = self._get_extra_link_info()
        self.iface_index = self._get_iface_index(root)
        self.mac = self.get_mac()
        logging.info('Interface %s: %s %s port at %d (mac: %s)', self.name, '40G' if self.supports_40_ge else ('10G' if self.supports_10_ge else '1G'), 'fiber' if self.fibre_port else 'utp', self.iface_index, self.mac)

    def __repr__(self):
        return '<NetworkInterface %s:%s:%s:%d>' % (
         self.name,
         self.supports_40_ge and '40G' if 1 else ('10G' if self.supports_10_ge else '1G'),
         'fiber' if self.fibre_port else 'utp', self.iface_index)

    def __str__(self):
        return self.name

    @property
    def sockfd(self):
        return self._sock.fileno()

    def _get_iface_index(self, root='/'):
        """Gets physical interface location.
        
        Args:
          root: where to look for sysfs.
        
        Returns:
          Interface index nummber:
            <INDEX_ONBOARD_MIN..INDEX_ONBOARD_MAX> for onboard NICs
            INDEX_UNKNOWN for NICs with no location data
            <INDEX_ADDON_MIN..) for addon NICs
        """
        dev_index = self.INDEX_ONBOARD_MIN
        key = 'sys/class/net/%s/device/acpi_index' % self.name
        index = platformutils.GetSysFsInfo(key, root)
        if not index:
            key = 'sys/class/net/%s/device/index' % self.name
            index = platformutils.GetSysFsInfo(key, root)
        try:
            dev_index = int(index) * 1024
            if dev_index > self.INDEX_ONBOARD_MAX:
                raise ValueError
        except ValueError:
            dev_index = self.INDEX_UNKNOWN
            logging.warn('No ACPI _DSM or SMBIOS NIC index information found for interface %s', self.name)
            logging.warn('Assuming interface %s is an addon card', self.name)

        key = 'sys/class/net/%s/dev_port' % self.name
        index = platformutils.GetSysFsInfo(key, root)
        try:
            port_index = int(index) + 1
            return dev_index + port_index
        except ValueError:
            if dev_index == self.INDEX_UNKNOWN:
                logging.warn('No physical port location information found for interface %s', self.name)

        return dev_index

    def _get_extra_link_info(self):
        """Gets supported port features and physical port type.
        
          SIOCETHTOOL ioctl is called with struct ifreq pointer (40b)
          * ifreq.ifr_name (0 - 15) = name of the interface (eg "eth0")
          * ifreq.ifr_data (16 - 23) -> struct ethtool_cmd (43b)
          ** ethtool_cmd.cmd (0 - 3) = ethtool command (eg. ETHTOOL_GSET)
        
          After calling ioctl()
          ** ethtool_cmd.supported (4 - 7) = bitfield of supported features
             bit ADVERTISED_10000baseT_Full is set when 10 Ge is supported
          ** ethtool_cmd.port (15) = physical port type
             0x03: fibre port
        
        Returns:
          Tuple of supported port features and type
        """
        ecmd = array.array('B', struct.pack('I39s', ETHTOOL_GSET, '\x00' * 39))
        ifreq = struct.pack('16sP', self.name, ecmd.buffer_info()[0])
        try:
            fcntl.ioctl(self.sockfd, SIOCETHTOOL, ifreq)
            res = ecmd.tostring()
            supported_features, port_type = struct.unpack('4xI7xB27x', res)
            supports_40_ge = bool(supported_features & ADVERTISED_40000baseKR4_Full or supported_features & ADVERTISED_40000baseCR4_Full or supported_features & ADVERTISED_40000baseSR4_Full or supported_features & ADVERTISED_40000baseLR4_Full)
            supports_10_ge = bool(supported_features & ADVERTISED_10000baseT_Full or supported_features & ADVERTISED_10000baseKX4_Full or supported_features & ADVERTISED_10000baseKR_Full or supported_features & ADVERTISED_10000baseR_FEC)
            fibre_port = port_type == self.PORT_TYPE_FIBRE
            return (
             supports_40_ge, supports_10_ge, fibre_port)
        except IOError:
            logging.warn('Failed fetching physical port type for interface %s', self.name)

        return (False, False, False)

    def _get_vendor_id(self, root='/'):
        """Returns the PCI vendor id for a network interface.
        
        Args:
          root: where to look for sysfs.
        
        Returns:
          PCI vendor id of the nic as an integer.
          See also http://pci-ids.ucw.cz/
            15B3: Mellanox
            14E4: Broadcom
            FFFF: illegal vendor id
        """
        key = 'sys/class/net/%s/device/vendor' % self.name
        hex_vendor_id = platformutils.GetSysFsInfo(key, root)
        try:
            return int(hex_vendor_id, 0)
        except ValueError:
            return platformutils.PCI_VENDOR_ILLEGAL

    def is_link_up(self, root='/'):
        """Tests whether or not a particular interface has a carrier.
        
        Args:
          root: where to look for sysfs.
        
        Returns:
          True if a carrier is detected
          False if either the interface is down or there is no link
        """
        key = 'sys/class/net/%s/carrier' % self.name
        return platformutils.GetSysFsInfo(key, root) == '1'

    def up(self):
        """Bring up the interface. Equivalent to ifconfig [iface] up."""
        ifreq = struct.pack('16sh', self.name, 0)
        res = fcntl.ioctl(self.sockfd, SIOCGIFFLAGS, ifreq)
        flags = struct.unpack('16sh', res)[1]
        flags |= IFF_UP
        ifreq = struct.pack('16sh', self.name, flags)
        fcntl.ioctl(self.sockfd, SIOCSIFFLAGS, ifreq)

    def get_mac(self):
        """Obtain the device's mac address."""
        ifreq = struct.pack('16sH14s', self.name, AF_UNIX, '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        res = fcntl.ioctl(self.sockfd, SIOCGIFHWADDR, ifreq)
        address = struct.unpack('16sH14s', res)[2]
        mac_address = struct.unpack('6B8x', address)
        return ':'.join(('%02X' % i for i in mac_address))


def ConfigureMellanoxNic(pci_address, mstconfig_path, link_types, root='/'):
    """Set sane ports types on ConnectX3 40G NIC.
    
    Mellanox ConnectX3 40G NIC has both ports configured by default to
    Infiniband. This is problematic, since the card will not bring up any eth*
    interfaces if no QSFP or DAC cable is plugged in and connected to the
    switch. Enforce link types on the NIC to always bring up an eth interface,
    even if nothing is plugged in.
    
    Args:
      pci_address: PCI address of the NIC (string).
      mstconfig_path: path to mstconfig tool.
      link_types: dict mapping port numbers to intended link types on the NIC
                  (ex. {1: MLX_LINK_TYPE_INFINIBAND, 2: MLX_LINK_TYPE_ETHERNET}).
      root: where to look for sysfs.
    
    Returns:
      True if no changes were needed and/or all commands finished successfully,
      False if there were problems running mstconfig tool.
    
    Raises:
      RebootNeeded if the machine needs to be rebooted for the changes
          to take effect.
    """
    if not link_types or not isinstance(link_types, dict):
        logging.warning('No links specified for configuration on ConnectX3 NIC')
        return True
    mlx_sysfs_config = os.path.join(root, 'sys/bus/pci/devices/%s/config' % pci_address)
    out, unused_err, ret_code = utils.RunCommand('%s -d %s query' % (mstconfig_path, mlx_sysfs_config))
    if ret_code != 0:
        logging.error('Unable to read ConnectX3 NIC settings.')
        return False
    port_settings = re.findall('^\\s*LINK_TYPE_P(\\d)\\s+\\w+(\\((\\d+)\\))?', out, re.M)
    if not port_settings:
        logging.error('Unable to parse mstconfig output.')
        return False
    reboot_needed = False
    for port_number, _, port_type in port_settings:
        try:
            port_type_int = int(port_type)
        except ValueError:
            port_type_int = -1

        if int(port_number) not in link_types.keys():
            continue
        if link_types[int(port_number)] != port_type_int:
            unused_out, unused_err, ret_code = utils.RunCommand('%s -y -d %s set LINK_TYPE_P%s=%d' % (
             mstconfig_path, mlx_sysfs_config, port_number,
             link_types[int(port_number)]))
            if ret_code != 0:
                logging.error('Unable to configure ConnectX3 NIC port %s to %s.', port_number, link_types[int(port_number)])
                return False
            reboot_needed = True

    if reboot_needed:
        raise platformutils.RebootNeeded
    return True
# okay decompiling ./google3/net/bandaid/xt_installer/setup/ifconfig.pyc
