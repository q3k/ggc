# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/platformutils.py
# Compiled at: 2019-06-18 16:41:38
"""Generic methods to gather system info and to identify a platform."""
__author__ = 'lducazu@google.com (Luc Ducazu)'
import abc
import collections
import logging
import os
import re
from google3.net.bandaid.xt_installer.setup import utils
AUTODETECT = 'auto'

class RebootNeeded(Exception):
    pass


class LiveDevice(object):
    CDROM = 'CDROM'
    USB = 'USB'


class PlatformBase(object):
    """Abstract base for platform classes."""
    __metaclass__ = abc.ABCMeta

    @property
    def root_disk(self):
        return None

    @property
    def serial_unit(self):
        return 1

    @property
    def sysid(self):
        return None

    @classmethod
    def GetName(cls):
        """Returns a friendly name for the platform, eg 'Dell-R720-10G'."""
        return 'platform base'

    @classmethod
    def Match(cls, sysinfo):
        """Indicates whether the given system info matches the platform.
        
        Args:
          sysinfo: a dictionary like this:
          {
            'vendor': 'Dell Inc.',
            'model': 'PowerEdge R430',
            'board': '0HFG24',
            'serialnumber': '9D9Z182',
            'network': [ PciDevice(PCI_CLASS_NETWORK_ETHERNET,
                                   PCI_VENDOR_BROADCOM, 0x1639) ],
            'storage': [ PciDevice(PCI_CLASS_STORAGE_RAID,
                                   PCI_VENDOR_LSI, 0x0060) ],
          }
          See also platformutils.GetSystemInfo().
        
        Returns:
          True if sysinfo matches the particular platform.
        """
        return True

    def PassEnv(self, env):
        """Pass the runtime environment (flags)."""
        pass

    def PrepareBootDevice(self, live_device):
        """Preliminary boot device configuration.
        
        Args:
          live_device: device booted from (LiveDevice)
        
        Returns:
          False if the configuration failed.
        
        Raises:
          RebootNeeded if the machine needs to be rebooted for the changes
              to take effect.
        """
        return True

    def PrepareNetworkDevice(self):
        """Preliminary network device configuration.
        
        Returns:
          False if the configuration failed.
        
        Raises:
          RebootNeeded if the machine needs to be rebooted for the changes
              to take effect.
        """
        return True

    def ConfigureRaid(self):
        """Configures RAID controllers.
        
        This function configures the RAID controller and updates the object.
        
        Returns:
          True if the RAID controller has been configured correctly;
          False if there was an error.
        """
        return True

    def ConfigureBIOS(self):
        """Set some basic BIOS settings to proper values.
        
        The new values will become effective after the next reboot.
        
        Returns:
          True if the settings were accepted.
        """
        return True

    def ConfigureBootOrder(self):
        """Bring hard drives to the front of the boot order.
        
        The new boot order will become effective after the next reboot.
        
        Returns:
          True if the settings were accepted.
        """
        return True

    def CreateBIOSJobQueue(self):
        """Prepares a BIOS job queue.
        
        The job queue contains the changes that will take effect
        at the next reboot.
        
        Returns:
          True (always)
        """
        return True

    def GetRootDiskPhysicalDriveIds(self):
        """One or more physical disk ids to configure as root disk."""
        return []


class PciDevice(collections.namedtuple('PciDevice', ['class_id', 'vendor_id', 'device_id'])):
    """Class to hold PCI device IDs.
    
    Holds the device class, the vendor and the device id.
    Documentation of PCI classes and ids: https://pci-ids.ucw.cz/.
    """

    def __repr__(self):
        return '[%04X] %04X:%04X' % self

    @classmethod
    def FromString(cls, id_as_string):
        """Creates a PciDevice object from a string.
        
        Args:
          id_as_string: a string in the form of '[0200] 14E4:1639'.
                        Where [0200] is the class id,
                        14E4 is the vendor id and
                        1639 is the device id.
        
        Returns:
          a PciDevice object.
        """
        re_pciid = re.compile('\\[(?P<class>[0-9a-fA-F]{4})\\]\\s(?P<vendor>[0-9a-fA-F]{4}):(?P<device>[0-9a-fA-F]{4})')
        match = re_pciid.match(id_as_string)
        if match:
            return cls(int(match.group('class'), 16), int(match.group('vendor'), 16), int(match.group('device'), 16))
        else:
            return None


PCI_CLASS_STORAGE_RAID = 260
PCI_CLASS_STORAGE_SAS = 263
PCI_CLASS_NETWORK_ETHERNET = 512
PCI_CLASS_NETWORK_CONTROLLER = 640
PCI_VENDOR_LSI = 4096
PCI_VENDOR_HP = 4156
PCI_VENDOR_BROADCOM = 5348
PCI_VENDOR_MELLANOX = 5555
PCI_VENDOR_INTEL = 32902
PCI_VENDOR_ILLEGAL = 65535
PCI_SUBSYSTEM_DEVICE_HP_MELLANOX10G = 32800
PCI_SUBSYSTEM_DEVICE_HP_MELLANOX40G = 8948
PCI_SUBSYSTEM_DEVICE_MLX_CONNECTX3PRO40G = 121
SUPPORTED_RAID_CONTROLLERS = {'PERC_H710_MINI': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 91),
   'PERC_H730_MINI': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 93),
   'PERC_H330_MINI': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 95),
   'PERC_6I': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 96),
   'PERC_H310_MINI': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 115),
   'PERC_H700': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_LSI, 121),
   'HPSA': PciDevice(PCI_CLASS_STORAGE_RAID, PCI_VENDOR_HP, 12857)
   }
SUPPORTED_SAS_CONTROLLERS = {'HPSA': PciDevice(PCI_CLASS_STORAGE_SAS, PCI_VENDOR_HP, 12857),
   'HBA330': PciDevice(PCI_CLASS_STORAGE_SAS, PCI_VENDOR_LSI, 151),
   'LSISAS3224': PciDevice(PCI_CLASS_STORAGE_SAS, PCI_VENDOR_LSI, 196)
   }
SUPPORTED_NETWORK_CARDS = {'BCM5709': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_BROADCOM, 5689),
   'BCM5720': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_BROADCOM, 5727),
   'BCM57800': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_BROADCOM, 5770),
   'BCM57810': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_BROADCOM, 5774),
   'MT27500': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_MELLANOX, 4099),
   'MT27520': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_MELLANOX, 4103),
   'MLX_ConnectX3': PciDevice(PCI_CLASS_NETWORK_CONTROLLER, PCI_VENDOR_MELLANOX, 4103),
   'MLX_ConnectX4': PciDevice(PCI_CLASS_NETWORK_ETHERNET, PCI_VENDOR_MELLANOX, 4117)
   }

def GetBlockDevicesByHost(host, channel=None, removable=True, root='/'):
    """Find the block devices associated with a SCSI host.
    
    H310 and H710 controllers create their logical disks in channel 2.
    H310 controllers make their physical drives accessible in channel 0.
    
    Args:
      host: host entry.
      channel: limit the list to entries in a specified channel.
          None means every channel.
      removable: include devices marked as 'removable' by the system.
      root: where to look for sysfs.
    
    Returns:
      An array of block device names.
    """
    result = []
    for target in sorted(os.listdir(os.path.join(root, 'sys/class/scsi_host', host, 'device'))):
        if target.startswith('target'):
            for coordinates in os.listdir(os.path.join(root, 'sys/class/scsi_host', host, 'device', target)):
                scsi_coordinates = coordinates.split(':')
                if len(scsi_coordinates) == 4 and (channel is None or scsi_coordinates[1] == str(channel)):
                    block_dir = os.path.join(root, 'sys/class/scsi_host', host, 'device', target, coordinates, 'block')
                    if os.path.isdir(block_dir):
                        for block in os.listdir(block_dir):
                            valid = True
                            if not removable:
                                try:
                                    with open(os.path.join(block_dir, block, 'removable'), 'r') as f:
                                        valid = not bool(int(f.read().strip()))
                                except (IOError, ValueError):
                                    pass

                            if valid:
                                result.append('/dev/' + block)

    return sorted(result)


def RescanScsiHost(host, root='/'):
    """Scan the devices for a specific host.
    
    Arguments:
      host: hostname of the entry in '/sys/class/scsi_host/'.
      root: where to look for sysfs.
    
    Returns:
      True if it succeeds, False otherwise.
    """
    filename = os.path.join(root, 'sys/class/scsi_host', host, 'scan')
    try:
        with open(filename, 'w') as f:
            f.write('- - -\n')
    except IOError:
        return False

    return True


def GetHostSysEntry(proc_name=None, root='/'):
    """Find the sys entries associated with hosts handled by a specific driver.
    
    Arguments:
      proc_name: driver name.
      root: where to look for sysfs.
    
    Returns:
      An array of host numbers matching the requirement.
    """
    scsi_hosts = sorted(os.listdir(os.path.join(root, 'sys/class/scsi_host')))
    if not proc_name:
        return scsi_hosts
    result = []
    for host in scsi_hosts:
        key = 'sys/class/scsi_host/%s/proc_name' % host
        if GetSysFsInfo(key, root) == proc_name:
            result.append(host)

    return result


def GetHostFromPCI(pci_address, root='/'):
    """Find SCSI host located at PCI address.
    
    Args:
      pci_address: PCI Address (Domain:Bus:Device.Function) (str).
      root: where to look for sysfs.
    
    Returns:
      A host identifier (str) if found at specified addres or None.
    """
    try:
        sys_files = sorted(os.listdir(os.path.join(root, 'sys/bus/pci/devices', pci_address)))
    except OSError:
        logging.error('Connot find PCI device %s.', pci_address)
        return None

    for filename in sys_files:
        if filename.startswith('host'):
            return filename

    logging.error('Connot find SCSI host at PCI address %s.', pci_address)
    return None


def GetSysFsInfo(key, root='/'):
    """Get info from files in sysfs.
    
    Args:
      key: the name of the file to be opened.
      root: where to look for sysfs.
    
    Returns:
      On success, the first line of the 'key'.
      Otherwise, an empty string.
    """
    filename = os.path.join(root, key)
    try:
        with open(filename, 'r') as fd:
            return fd.readline().strip()
    except IOError:
        return ''


def GetPlatformVendor(root='/'):
    key = 'sys/class/dmi/id/sys_vendor'
    return GetSysFsInfo(key, root=root)


def GetPlatformModel(root='/'):
    key = 'sys/class/dmi/id/product_name'
    return GetSysFsInfo(key, root=root)


def GetPlatformBoard(root='/'):
    key = 'sys/class/dmi/id/board_name'
    return GetSysFsInfo(key, root=root)


def GetPlatformSerialNumber(root='/'):
    key = 'sys/class/dmi/id/product_serial'
    return GetSysFsInfo(key, root=root)


def _GetPciDeviceFromSysFsEntry(path):
    class_id = int(GetSysFsInfo(os.path.join(path, 'class')), 16) >> 8
    vendor_id = int(GetSysFsInfo(os.path.join(path, 'vendor')), 16)
    device_id = int(GetSysFsInfo(os.path.join(path, 'device')), 16)
    return PciDevice(class_id, vendor_id, device_id)


def _GetPciIds(root='/'):
    """Gather PCI device IDs from sysfs."""
    devicesdir = os.path.join(root, 'sys/bus/pci/devices')
    pci_ids = set()
    for direntry in sorted(os.listdir(devicesdir)):
        device_path = os.path.join(devicesdir, direntry)
        pci_device = _GetPciDeviceFromSysFsEntry(device_path)
        pci_ids.add(pci_device)

    return pci_ids


def _GetPciIdsForClass(class_id, root='/'):
    return sorted([ pci_id for pci_id in _GetPciIds(root) if pci_id.class_id == class_id ])


def GetRaidControllerPciIds(root='/'):
    return _GetPciIdsForClass(PCI_CLASS_STORAGE_RAID, root)


def GetSasControllerPciIds(root='/'):
    return _GetPciIdsForClass(PCI_CLASS_STORAGE_SAS, root)


def GetEthernetControllerPciIds(root='/'):
    return _GetPciIdsForClass(PCI_CLASS_NETWORK_ETHERNET, root)


def GetNetworkControllerPciIds(root='/'):
    return _GetPciIdsForClass(PCI_CLASS_NETWORK_CONTROLLER, root)


def GetDevicePciAddress(pci_device, any_class=False, root='/'):
    """Get PCI device Domain, Bus, Device Number and Function address from sysfs.
    
    Args:
      pci_device: A PciDevice object to search for.
      any_class: Match device even if PCI class id is different (bool).
      root: where to look for sysfs.
    
    Returns:
      A string in 'Domain:Bus:Device.Function' format or empty if no device found.
    """
    devicesdir = os.path.join(root, 'sys/bus/pci/devices')
    for direntry in sorted(os.listdir(devicesdir)):
        device_path = os.path.join(devicesdir, direntry)
        device = _GetPciDeviceFromSysFsEntry(device_path)
        match_class = bool(pci_device.class_id == device.class_id) or any_class
        match_vendor = bool(pci_device.vendor_id == device.vendor_id)
        match_device = bool(pci_device.device_id == device.device_id)
        if match_class and match_vendor and match_device:
            return direntry

    return ''


def GetDeviceSubsystemId(pci_address, root='/'):
    sysfs_path = os.path.join(root, 'sys/bus/pci/devices/%s' % pci_address)
    try:
        device_id = int(GetSysFsInfo(os.path.join(sysfs_path, 'subsystem_device')), 16)
        vendor_id = int(GetSysFsInfo(os.path.join(sysfs_path, 'subsystem_vendor')), 16)
    except ValueError:
        return (0, 0)

    return (vendor_id, device_id)


def GetSystemInfo(root='/'):
    """Gather system info from files in sysfs.
    
    Args:
      root: where to look for sysfs.
    
    Returns:
      A dictionary containing the vendor and model name, serial number,
      storage and network controller PCI ids.
    """
    sysinfo = {'vendor': GetPlatformVendor(root),
       'model': GetPlatformModel(root),
       'board': GetPlatformBoard(root),
       'serialnumber': GetPlatformSerialNumber(root),
       'network': GetEthernetControllerPciIds(root) + GetNetworkControllerPciIds(root),
       'storage': GetRaidControllerPciIds(root) + GetSasControllerPciIds(root)
       }
    logging.info('System Info: %r', sysinfo)
    return sysinfo


def PrintSystemInfo(root='/'):
    """Print PCI device information.
    
    Args:
      root: where to look for sysfs.
    
    """
    utils.Print('\nVendor: %s' % (GetPlatformVendor(root) or 'UNKNOWN'))
    net_reverse = {v:k for k, v in SUPPORTED_NETWORK_CARDS.items()}
    network_pciids = GetEthernetControllerPciIds(root) + GetNetworkControllerPciIds(root)
    netdev = [ (net_reverse.get(n) or 'unknown (PCI ID: %s)' % str(n)).replace('_', ' ') for n in network_pciids
             ]
    netdev = [ n.replace('_', ' ') for n in netdev ]
    utils.Print('Network device(s): %s' % (', '.join(netdev) if netdev else 'Not found'))
    storage_reverse = {v:k for k, v in SUPPORTED_SAS_CONTROLLERS.items()}
    storage_reverse.update({v:k for k, v in SUPPORTED_RAID_CONTROLLERS.items()})
    storage_pciids = GetRaidControllerPciIds(root) + GetSasControllerPciIds(root)
    stordev = [ (storage_reverse.get(n) or 'unknown (PCI ID: %s)' % str(n)).replace('_', ' ') for n in storage_pciids
              ]
    utils.Print('Storage: %s\n' % (', '.join(stordev) if stordev else 'Not found'))


_hardware_platforms = set()

def RegisterHardwarePlatform(cls):
    _hardware_platforms.add(cls)


def GetHardwarePlatformNames():
    return sorted((platform_cls.GetName() for platform_cls in _hardware_platforms))


def GetHardwarePlatformClasses():
    return sorted(_hardware_platforms, key=lambda platform_cls: platform_cls.GetName())


def GetHardwarePlatformClassByName(platform_name):
    """Returns a platform class associated with a name.
    
    Args:
      platform_name: string represenation of a hardware platform
                     eg 'Dell-R720-10G'
    
    Returns:
      A python class representing a hardware platform,
      None on error.
    """
    for platform_cls in _hardware_platforms:
        if platform_cls.GetName() == platform_name:
            return platform_cls

    return None


def GetHardwarePlatformFromSystemInfo(sysinfo):
    """Returns a platform object matching passed system information.
    
    Args:
      sysinfo: a dictionary like this:
      {
        'vendor': 'Dell Inc.',
        'model': 'PowerEdge R430',
        'board': '0HFG24',
        'serialnumber': '9D9Z182',
        'network': [ PciDevice(PCI_CLASS_NETWORK_ETHERNET,
                               PCI_VENDOR_BROADCOM, 0x1639) ],
        'storage': [ PciDevice(PCI_CLASS_STORAGE_RAID,
                               PCI_VENDOR_LSI, 0x0060) ],
      }
      See also GetSystemInfo().
    
    Returns:
      A platform class instance representing the local hardware,
      None on error, or if no match can be found.
    """
    for platform_cls in _hardware_platforms:
        if platform_cls.Match(sysinfo):
            return platform_cls()

    return None


def GetHardwarePlatform(root='/'):
    """Returns a platform object representing the detected hardware.
    
    This function gathers system information from the local machine
    and returns an object that matches this information.
    
    Args:
      root: where to look for the 'sys' directory.
    
    Returns:
      A platform class instance representing the local hardware,
      None on error, or if no match can be found.
    """
    sysinfo = GetSystemInfo(root)
    return GetHardwarePlatformFromSystemInfo(sysinfo)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/platformutils.pyc
