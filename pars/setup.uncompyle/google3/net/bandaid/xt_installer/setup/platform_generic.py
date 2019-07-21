# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/platform_generic.py
# Compiled at: 2019-06-18 16:41:38
"""Generic machine definition used for installing unknown platforms."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
import logging
from google3.net.bandaid.xt_installer.setup import platformutils

class PlatformGeneric(platformutils.PlatformBase):
    """Generic machine."""

    def __init__(self):
        super(PlatformGeneric, self).__init__()
        self._root_disk = None
        self._quiet = False
        self._dry_run = True
        return

    def PassEnv(self, env):
        self._skip_reboot = env.skip_reboot
        self._dry_run = env.dry_run
        self._quiet = env.quiet
        self._root_disk = env.prospective_root_disk

    @classmethod
    def GetName(cls):
        return 'generic-unknown'

    @classmethod
    def Match(cls, sysinfo):
        return False

    @property
    def root_disk(self):
        return self._root_disk

    def PrepareBootDevice(self, live_device):
        block_devices = []
        scsi_hosts = platformutils.GetHostSysEntry()
        for host in scsi_hosts:
            block_devices.extend(platformutils.GetBlockDevicesByHost(host, removable=False))

        block_devices = sorted(block_devices)
        logging.info('Detected block devices: %r.', block_devices)
        if block_devices:
            logging.info('Setting %s as root disk.', block_devices[0])
            self._root_disk = block_devices[0]
        return True

    def PrepareNetworkDevice(self):
        return True

    def ConfigureRaid(self):
        return True

    def ConfigureBIOS(self):
        return True

    def ConfigureBootOrder(self):
        return True

    def CreateBIOSJobQueue(self):
        return True


platformutils.RegisterHardwarePlatform(PlatformGeneric)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/platform_generic.pyc
