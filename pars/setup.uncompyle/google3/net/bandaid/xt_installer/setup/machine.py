# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/machine.py
# Compiled at: 2019-06-18 16:41:38
"""Hardware detection and configuration part od XT installer.

This file covers hardware specific aspects of XT Installer.  It does the
following:

  - retrieves system information
  - configures RAID controller
  - configures BIOS

"""
__author__ = 'devink@google.com (Devin Kennedy)'
import glob
import logging
import operator
import os
import re
import sys
from google3.net.bandaid.xt_installer.setup import ifconfig
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils

class Machine(object):
    """Generic class for machine configuration.
    
    This class holds the information about machine state and methods to prepere
    it for installation.
    """

    def __init__(self, platform=None):
        self._svctag = None
        self._sysid = None
        self._interfaces = []
        self._one_ge_interfaces = []
        self._ten_ge_interfaces = []
        self._forty_ge_interfaces = []
        self._mlx_interfaces = []
        self._interfaces_with_link = []
        self._root_disk = '/dev/sda'
        self._platform = platform
        self._bios_settings_changed = False
        self._live_device = None
        self._quiet = False
        self._dry_run = True
        self._skip_reboot = False
        self._root_disk = '/dev/sda'
        self._live_mountpoint = '/lib/live/mount/medium'
        return

    def PassEnv(self, env):
        self._quiet = env.quiet
        self._dry_run = env.dry_run
        self._skip_reboot = env.skip_reboot
        self._root_disk = env.prospective_root_disk
        self._live_mountpoint = env.live_mountpoint
        if self._platform:
            self._platform.PassEnv(env)

    @property
    def svctag(self):
        if not self._svctag:
            self._svctag = platformutils.GetPlatformSerialNumber()
        return self._svctag

    @property
    def sysid(self):
        if not self._sysid and self._platform:
            self._sysid = self._platform.sysid
        if not self._sysid:
            self._sysid = platformutils.GetPlatformModel()
        return self._sysid

    @property
    def interfaces(self):
        return self._interfaces

    @property
    def one_ge_interfaces(self):
        return self._one_ge_interfaces

    @property
    def ten_ge_interfaces(self):
        return self._ten_ge_interfaces

    @property
    def forty_ge_interfaces(self):
        return self._forty_ge_interfaces

    @property
    def mlx_interfaces(self):
        return self._mlx_interfaces

    @property
    def interfaces_with_link(self):
        return self._interfaces_with_link

    @property
    def root_disk(self):
        if self._platform:
            return self._platform.root_disk
        return self._root_disk

    @property
    def serial_unit(self):
        if self._platform:
            return self._platform.serial_unit
        return 1

    @property
    def platform(self):
        return self._platform

    @classmethod
    def Detect(cls, force_platform=platformutils.AUTODETECT, root='/'):
        """Detect the platform setup is running on.
        
        Args:
          force_platform: which embedded platform to use.
          root: where to look for sysfs.
        
        Returns:
          A machine instance with embedded platform, possibly None.
        """
        platform = None
        if force_platform == platformutils.AUTODETECT:
            detection_method = 'detected'
            platform = platformutils.GetHardwarePlatform(root)
        else:
            detection_method = 'forced'
            platform_cls = platformutils.GetHardwarePlatformClassByName(force_platform)
            if platform_cls:
                platform = platform_cls()
        if platform:
            logging.info('Platform: %s (%s)', platform.GetName(), detection_method)
        else:
            logging.warning('Unrecognized platform: %s (s/n: %s)', platformutils.GetPlatformModel(), platformutils.GetPlatformSerialNumber())
        utils.RunCommand('lspci -nn')
        return Machine(platform)

    def Reboot(self):
        sys.exit(3)

    def GetEthernetInterfaces(self, root='/'):
        """Fetches the list of PCI Ethernet interfaces in physical order.
        
        Arguments:
          root: where to look for sysfs.
        
        Returns:
          An array of interface names.
        """
        descriptors = glob.glob(os.path.join(root, 'sys/bus/pci/devices/*/net/eth*'))
        interfaces = [ ifconfig.NetworkInterface(os.path.basename(descriptor), root) for descriptor in descriptors
                     ]
        return sorted(interfaces, key=operator.attrgetter('iface_index', 'mac'))

    def GatherNicLinkStatus(self, root='/'):
        self._interfaces_with_link = [ iface for iface in self._interfaces if iface.is_link_up(root) ]
        logging.info('Detected interfaces with carrier: %s', [ iface.name for iface in self._interfaces_with_link ])

    def GatherNicInformation(self, root='/'):
        """Gather information about the machine's network cards."""
        if self._platform:
            if self._dry_run:
                logging.info('Dry run, network controller check skipped.')
            else:
                self._platform.PrepareNetworkDevice()
        self._interfaces = self.GetEthernetInterfaces(root)
        logging.info('Detected interfaces: %s', [ iface.name for iface in self._interfaces ])
        if not self._interfaces:
            utils.Print('No Network Interfaces found.')
            return False
        for iface in self._interfaces:
            logging.info('Bringing up %s', iface.name)
            iface.up()

        self.GatherNicLinkStatus(root)
        self._one_ge_interfaces = [ iface for iface in self._interfaces if not iface.supports_10_ge ]
        logging.info('Detected 1Ge interfaces: %s', [ iface.name for iface in self._one_ge_interfaces ])
        self._ten_ge_interfaces = [ iface for iface in self._interfaces if iface.supports_10_ge and not iface.supports_40_ge
                                  ]
        logging.info('Detected 10Ge interfaces: %s', [ iface.name for iface in self._ten_ge_interfaces ])
        self._forty_ge_interfaces = [ iface for iface in self._interfaces if iface.supports_40_ge ]
        logging.info('Detected 40Ge interfaces: %s', [ iface.name for iface in self._forty_ge_interfaces ])
        self._mlx_interfaces = [ iface for iface in self._ten_ge_interfaces + self._forty_ge_interfaces if iface.vendor_id == platformutils.PCI_VENDOR_MELLANOX
                               ]
        logging.info('Detected Mellanox interfaces: %s', [ iface.name for iface in self._mlx_interfaces ])
        return True

    def _GetLiveDevice(self, mounts_path='/proc/mounts'):
        """Check if we booted from a block device (as opposed to a CD).
        
        self._live_mountpoint is the path of the file system on the actual boot
        device.  This method uses this path to determine the type of the boot device
        (CD or USB stick).
        
        Args:
          mounts_path: path to the mounts file in proc (usually '/proc/mounts').
        
        Returns:
          True if self._live_mountpoint is mounted from /dev/sd*.
          False if self._live_mountpoint is mounted from /dev/sr*.
          None otherwise.
        """
        try:
            with open(mounts_path, 'r') as mounts_file:
                mounts_dump = mounts_file.read()
        except IOError:
            logging.error('Cannot read mounts file %s.', mounts_path)
            return

        live_device = re.search('^(?P<Dev>[^ ]*) ' + self._live_mountpoint + ' ', mounts_dump, re.MULTILINE)
        if live_device:
            if live_device.group('Dev').startswith('/dev/sd'):
                return platformutils.LiveDevice.USB
            if live_device.group('Dev').startswith('/dev/sr'):
                return platformutils.LiveDevice.CDROM
        return

    def GatherSystemInformation(self):
        """Reads system information and stores it.
        
        This function reads system information from various sources and stores it in
        the object.  In addition to reading this information, it validates it
        against a set of supported platforms.
        
        Returns:
          True if information was retrieved successfully and the system matches a
          supported platform; False otherwise.
        """
        utils.Print('Gathering system information...\n', self._quiet)
        utils.Print('System Id: %s' % (self.sysid or 'UNKNOWN'), self._quiet)
        utils.Print('Service tag: %s\n' % (self.svctag or 'UNKNOWN'), self._quiet)
        if not self._platform:
            utils.Print('Unrecognized platform!')
            platformutils.PrintSystemInfo()
            return False
        self._live_device = self._GetLiveDevice()
        logging.info('Live media device: %s', self._live_device)
        if self._dry_run:
            logging.info('Dry run, RAID controller check skipped.')
            return True
        return self._platform.PrepareBootDevice(self._live_device)

    def ConfigureRaid(self):
        utils.Print('Configuring RAID...', self._quiet)
        if self._dry_run:
            logging.info('Dry run, not configuring RAID controller.')
            return True
        if self._platform:
            return self._platform.ConfigureRaid()
        return False

    def ConfigureBIOS(self):
        """Set some basic BIOS settings to proper values.
        
        Set some basic BIOS settings to proper values.
        The new values will become effective after the next reboot.
        
        Returns:
          True if the settings were accepted.
        """
        utils.Print('Configuring BIOS general settings...', self._quiet)
        if self._dry_run:
            logging.info('Dry run, not configuring BIOS.')
            return True
        if self._platform:
            return self._platform.ConfigureBIOS()
        return False

    def ConfigureBootOrder(self):
        """Bring hard drives to the front of the boot order.
        
        The new boot order will become effective after the next reboot.
        
        Returns:
          True if the settings were accepted.
        
        """
        utils.Print('Configuring BIOS boot settings...', self._quiet)
        if self._dry_run:
            logging.info('Dry run, not configuring BIOS boot setting.')
            return True
        if self._platform:
            return self._platform.ConfigureBootOrder()
        return False

    def CreateBIOSJobQueue(self):
        """If there are pending BIOS changes creates a jobqueue entry.
        
        Returns:
          True
        """
        utils.Print('Writing BIOS settings...', self._quiet)
        if self._dry_run:
            logging.info('Dry run, not writing new setting to BIOS.')
            return True
        if self._platform:
            return self._platform.CreateBIOSJobQueue()
        return False
# okay decompiling ./google3/net/bandaid/xt_installer/setup/machine.pyc
