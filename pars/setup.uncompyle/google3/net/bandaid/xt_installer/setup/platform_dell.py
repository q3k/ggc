# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/platform_dell.py
# Compiled at: 2019-06-18 16:41:38
"""Dell platform specific identification implementation."""
__author__ = 'lducazu@google.com (Luc Ducazu)'
import logging
import re
import time
from google3.net.bandaid.xt_installer.setup import ifconfig
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils

class PlatformDell(platformutils.PlatformBase):
    """Generic Dell machine."""
    DEFAULT_IDRACADM_PATH = '/usr/local/sbin/idracadm7'
    DEFAULT_MEGACLI_PATH = '/export/hda3/bandaid/tools/MegaCli64'
    DEFAULT_SYSCFG_PATH = '/usr/local/sbin/syscfg'
    DEFAULT_MSTCONFIG_PATH = '/usr/bin/mstconfig'

    def __init__(self):
        super(PlatformDell, self).__init__()
        self._bios_boot_sequence = None
        self._bios_hdd_sequence = None
        self._bios_settings_changed = False
        self._root_disk = None
        self._skip_reboot = False
        self._quiet = False
        self._dry_run = True
        self._idracadm_path = self.DEFAULT_IDRACADM_PATH
        self._megacli_path = self.DEFAULT_MEGACLI_PATH
        self._syscfg_path = self.DEFAULT_SYSCFG_PATH
        self._mstconfig_path = self.DEFAULT_MSTCONFIG_PATH
        return

    def PassEnv(self, env):
        self._skip_reboot = env.skip_reboot
        self._dry_run = env.dry_run
        self._quiet = env.quiet
        self._idracadm_path = env.idracadm_path or self.DEFAULT_IDRACADM_PATH
        self._megacli_path = env.megacli_path or self.DEFAULT_MEGACLI_PATH
        self._syscfg_path = env.syscfg_path or self.DEFAULT_SYSCFG_PATH
        self._mstconfig_path = env.mstconfig_path or self.DEFAULT_MSTCONFIG_PATH

    @classmethod
    def GetName(cls):
        return 'Generic Dell'

    @classmethod
    def Match(cls, sysinfo):
        return cls._CheckVendor(sysinfo['vendor']) and cls._CheckModel(sysinfo['model']) and cls._CheckNetwork(sysinfo['network']) and cls._CheckStorage(sysinfo['storage'])

    @classmethod
    def _CheckVendor(cls, vendor):
        return 'dell' in vendor.lower()

    @classmethod
    def _CheckModel(cls, model):
        return True

    @classmethod
    def _CheckNetwork(cls, network):
        return True

    @classmethod
    def _CheckStorage(cls, storage):
        return True

    @property
    def root_disk(self):
        return self._root_disk

    def PrepareBootDevice(self, live_device):
        if not self._ReadBootSequence():
            print 'Unable to communicate with BIOS.'
            return False
        logging.info('Boot sequence: %s', self._bios_boot_sequence)
        logging.info('HDD sequence: %s', self._bios_hdd_sequence)
        if self._NeedToReboot(live_device):
            if not self.ConfigureRaid():
                return False
            utils.Print('A reboot is required to reconfigure RAID controller.', self._quiet)
            if not self._skip_reboot:
                raise platformutils.RebootNeeded
        return True

    def PrepareNetworkDevice(self):
        return True

    def _ParseDeviceLine(self, devices):
        """Parse device lists as formatted by idracadm.
        
        Arguments:
          devices: The single device list output from idracadm.
        
        Returns:
          A list of BIOS device names. It may be an empty list.
        """
        if not devices:
            return []
        return devices.split(',')

    def _ReadBootSequence(self):
        """Read the current BootSeq and HddSeq from the BIOS.
        
        Note an empty list does not mean there are no entries. Only that we don't
        have multiple options to choose from.
        
        Returns:
          Boolean indicating if we were able to read BIOS settings.
        """
        stdout, unused_err, ret_code = utils.RunCommand('%s get BIOS.BiosBootSettings' % self._idracadm_path)
        if ret_code not in (0, 255):
            logging.error('Cannot read BIOS boot settings!')
            return False
        else:
            for entry in stdout.splitlines():
                key, sep, value = entry.partition('=')
                if not sep:
                    continue
                if key == 'BootSeq':
                    self._bios_boot_sequence = self._ParseDeviceLine(value)
                if key == 'HddSeq':
                    self._bios_hdd_sequence = self._ParseDeviceLine(value)

            if self._bios_boot_sequence is None or self._bios_hdd_sequence is None:
                return False
            return True

    def _NeedToReboot(self, live_device):
        """Check if we need to configure the RAID controller and reboot.
        
        Args:
          live_device: Device booted from (platformutils.LiveDevice)
        
        Returns:
          True if we need to create a logical disk and reboot before we can
            configure the boot sequence.
          False if we can complete the install procedure without a reboot.
        """
        if live_device == platformutils.LiveDevice.USB:
            return not [ device for device in self._bios_hdd_sequence if device.startswith('RAID.Integrated.') or device.startswith('RAID.Slot.') or device.startswith('sasraid.emb.')
                       ]
        else:
            if not [ device for device in self._bios_boot_sequence if device.startswith('HardDisk.') or device.startswith('hdd.emb.')
                   ]:
                return True
            if [ device for device in self._bios_hdd_sequence if device.startswith('RAID.Integrated.') or device.startswith('RAID.Slot.') or device.startswith('sasraid.emb.')
               ]:
                return False
            if not self._bios_hdd_sequence:
                return not self._GetLDList()
            return True

    def _GetLDList(self):
        """Get information about the logical drives from the RAID controller.
        
        Returns:
          An associative array of logical drives associated with their targets ids
          or None if there are any errors.
        """
        logging.info('Getting all logical disk information from MegaCLI.')
        stdout, unused_err, ret_code = utils.RunCommand('%s -LDInfo -lALL -a0' % self._megacli_path)
        if ret_code != 0:
            logging.error('Error retrieving logical disk information.')
            return None
        else:
            ldlist = {}
            vd = re.compile('^Virtual (Disk|Drive): (?P<Id>\\d+) \\(Target Id: (?P<Target>\\d+)\\)$')
            for line in stdout.splitlines():
                entry = vd.match(line)
                if entry:
                    ldlist[int(entry.group('Id'))] = int(entry.group('Target'))

            return ldlist

    def _GetPDState(self):
        """Get slot numbers and firmware state of physical drives.
        
        Returns:
          A dict with slot numbers as keys and firmware state as value.
        """
        logging.info('Getting all physical disk information from MegaCLI.')
        stdout, unused_err, ret_code = utils.RunCommand('%s -PDList -a0' % self._megacli_path)
        if ret_code != 0:
            logging.error('Error retrieving physical disk information.')
            return {}
        pdlist = {}
        pd = re.compile('^Slot Number: (?P<Id>\\d+)$')
        state = re.compile('^Firmware state: (?P<state>.+)$')
        current_slot = -1
        for line in stdout.splitlines():
            entry = pd.match(line)
            if entry:
                current_slot = int(entry.group('Id'))
            entry = state.match(line)
            if entry:
                pdlist[current_slot] = entry.group('state')

        return pdlist

    def _GetPDList(self):
        """Get slot numbers of the physical drives from the RAID controller.
        
        Returns:
          An set of physical drive ids.
          The slot numbers are used as keys.
        """
        return set(self._GetPDState().keys())

    def ConfigureRaid(self):
        """Configures RAID controllers.
        
        This function configures the RAID controller and updates the object.
        
        Returns:
          True if the RAID controller has been configured correctly; False if there
          was an error.
        """
        hosts = platformutils.GetHostSysEntry(proc_name='megaraid_sas')
        if not hosts:
            utils.Print('\nGGC install: RAID controller not detected.', self._quiet)
            logging.error('RAID controller not detected!')
            return False
        if len(hosts) > 1:
            utils.Print('\nGGC install: RAID controller detection error.', self._quiet)
            logging.error('Unexpected number of controllers (%d)!', len(hosts))
            return False
        host = hosts[0]
        logging.info('Attempting to configure the RAID controller with correct settings. Non-zero exit codes are expected.')
        utils.RunCommand('%s -CfgForeign -Clear -a0' % self._megacli_path, dry_run=self._dry_run)
        utils.RunCommand('%s -DiscardPreservedCache -Lall -a0' % self._megacli_path, dry_run=self._dry_run)
        utils.RunCommand('%s -CfgClr -a0' % self._megacli_path, dry_run=self._dry_run)
        utils.RunCommand('%s -AdpSetProp BootWithPinnedCache -1 -aALL' % self._megacli_path, dry_run=self._dry_run)
        utils.RunCommand('%s -AdpSetProp AutoEnhancedImportEnbl -aALL' % self._megacli_path, dry_run=self._dry_run)
        utils.RunCommand('%s -AdpBios -BE -aALL' % self._megacli_path, dry_run=self._dry_run)
        if self._GetLDList():
            logging.error('Logical drives left after a CfgClr!')
            utils.Print('\nGGC install: RAID configuration error (code: 001).', self._quiet)
            return False
        platformutils.RescanScsiHost(host)
        physical_drives = self._GetPDList()
        if not physical_drives:
            logging.error("Can't retrieve the list of physical drives!")
            utils.Print('\nGGC install: RAID configuration error (code: 002).', self._quiet)
            return False
        logging.info('Attempting to disable JBOD on the RAID controller.')
        utils.RunCommand('%s -AdpSetProp -EnableJBOD -0 -a0' % self._megacli_path, dry_run=self._dry_run)
        drive_ids = self.GetRootDiskPhysicalDriveIds()
        if len(drive_ids) == 1:
            if not self._ConfigureSingleRootDisk(drive_ids[0], physical_drives):
                return False
        else:
            if len(drive_ids) > 1:
                if not self._ConfigureMirrorRootDisk(drive_ids, physical_drives):
                    return False
            if self._GetLDList() != {0: 0}:
                logging.info('Unexpected logical drive configuration after initialization!')
                utils.Print('\nGGC install: RAID configuration error (code: 005).', self._quiet)
                return False
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s -AdpBootDrive -Set -L0 -a0' % self._megacli_path, dry_run=self._dry_run)
            if ret_code:
                logging.info('Cannot set the controller boot device!')
                utils.Print('\nGGC install: RAID configuration error (code: 006).', self._quiet)
                return False
            logging.info('Attempting to configure the root logical disk settings.')
            utils.RunCommand('%s -LDSetProp Direct -L0 -a0' % self._megacli_path, dry_run=self._dry_run)
            utils.RunCommand('%s -LDSetProp ADRA -L0 -a0' % self._megacli_path, dry_run=self._dry_run)
            utils.RunCommand('%s -LDSetProp WB -L0 -a0' % self._megacli_path, dry_run=self._dry_run)
            utils.RunCommand('%s -LDSetProp -Name BootDisk -L0 -a0' % self._megacli_path, dry_run=self._dry_run)
            platformutils.RescanScsiHost(host)
            time.sleep(1.5)
            block_devices = platformutils.GetBlockDevicesByHost(host, 2)
            if len(block_devices) != 1:
                logging.error('Unexpected number of devices (%d)!', len(block_devices))
                utils.Print('\nGGC install: RAID configuration error (code: 007).', self._quiet)
                return False
        self._root_disk = block_devices[0]
        logging.info('Root logical device: %s', self._root_disk)
        return True

    def _ConfigureSingleRootDisk(self, drive_id, physical_drives):
        """Configures a single disk as root device.
        
        Arguments:
          drive_id: a physical disk id that should be the root disk.
          physical_drives: list of physical drives
        
        Returns:
          True if the boot disk was created.
        """
        if drive_id not in physical_drives:
            logging.error('No physical drive in slot #0 to build the root logical drive!')
            utils.Print('\nGGC install: RAID configuration error (code: 004).', self._quiet)
            return False
        logging.info('Creating a RAID0 logical disk with the disk at slot 0.')
        utils.RunCommand('%s -CfgLDAdd -r0 [?:0] -a0' % self._megacli_path, dry_run=self._dry_run)
        return True

    def _ConfigureMirrorRootDisk(self, root_disks_ids, all_disks_ids):
        """Configures a RAID 1 array.
        
        Arguments:
          root_disks_ids: Set of physical disk ids that should be part of the array.
          all_disks_ids: list of disk ids of all physical disks on the machine.
        
        Returns:
          True if the RAID array was created.
        """
        raid_members = []
        for candidate in root_disks_ids:
            if candidate in all_disks_ids:
                raid_members.append('?:%d' % candidate)

        if not raid_members:
            logging.error('Not enough physical drives to build the root logical drive! Needed at least one of the disks at slot: %s. Found none.', ','.join(map(str, root_disks_ids)))
            utils.Print('\nGGC install: RAID configuration error (code: 003).', self._quiet)
            return False
        logging.info('Configuring the boot logical drive with these members: [%s]', ','.join(map(str, raid_members)))
        raid_level = 1 if len(raid_members) > 1 else 0
        logging.info('Creating RAID %s logical disk with disks at slots: %s.', raid_level, ','.join(map(str, raid_members)))
        utils.RunCommand('%s -CfgLDAdd -r%d [%s] -a0' % (
         self._megacli_path,
         raid_level,
         ','.join(map(str, raid_members))), dry_run=self._dry_run)
        if self._GetLDList() == {0: 0}:
            logging.info('Successfully created RAID %s logial disk with disks at slots: %s.', raid_level, ','.join(map(str, raid_members)))
            return True
        logging.error('Failed to create RAID %s logial disk with disks at slots: %s.', raid_level, ','.join(map(str, raid_members)))
        logging.info('Attempting to create RAID0 logical disk with any one of the disks at slots: %s', ','.join(map(str, raid_members)))
        pdstate = self._GetPDState()
        for disk in root_disks_ids:
            if 'Unconfigured(good)' in pdstate.get(disk, ''):
                utils.RunCommand('%s -CfgLDAdd -r0 [?:%s] -a0' % (
                 self._megacli_path, disk), dry_run=self._dry_run)
                logging.info('Created RAID0 logical disk using the physical disk at slot %s', disk)
                return True

        logging.error('Failed to create RAID0 logical disk with any one of these disks at slots: %s', ','.join(map(str, raid_members)))
        return False

    def _GetBiosSetting(self, group, setting):
        """Get a value of a single BIOS setting.
        
        Args:
          group: BIOS config group where the setting is located.
          setting: The name of config entry.
        
        Returns:
          Value of the BIOS setting or None if it's not found in idracadm output.
        """
        stdout, unused_err, ret_code = utils.RunCommand('%s get %s.%s' % (self._idracadm_path, group, setting))
        if ret_code != 0:
            logging.error('Cannot read %s BIOS setting!', setting)
            return None
        else:
            for entry in stdout.splitlines():
                key, sep, value = entry.partition('=')
                if sep and key == setting:
                    return value.strip()

            return None

    def ConfigureBIOS(self):
        success = True
        if self._GetBiosSetting('BIOS.BiosBootSettings', 'BootMode') != 'Bios':
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s set BIOS.BiosBootSettings.BootMode Bios' % self._idracadm_path, dry_run=self._dry_run)
            if ret_code != 0:
                success = False
                logging.error('Cannot set boot mode to BIOS!')
            else:
                self._bios_settings_changed = True
        if self._GetBiosSetting('BIOS.MiscSettings', 'ErrPrompt') != 'Disabled':
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s set BIOS.MiscSettings.ErrPrompt Disabled' % self._idracadm_path, dry_run=self._dry_run)
            if ret_code != 0:
                success = False
                logging.error('Cannot disable F1 prompt on errors!')
            else:
                self._bios_settings_changed = True
        if not success:
            utils.Print('WARNING: BIOS settings update failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def _ConfigureHddSequence(self):
        logging.info('Current BIOS HDD sequence: %s', ','.join(self._bios_hdd_sequence))
        disks = [ device for device in self._bios_hdd_sequence if device.startswith('RAID.Integrated.') or device.startswith('RAID.Slot.')
                ]
        if not disks:
            logging.error('No internal disks in the BIOS HDD list!')
            return False
        disks.sort()
        disks += [ device for device in self._bios_hdd_sequence if device not in disks
                 ]
        if self._bios_hdd_sequence != disks:
            logging.info('Setting the BIOS HDD sequence to: %s', ','.join(disks))
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s set BIOS.BiosBootSettings.HddSeq %s' % (
             self._idracadm_path, ','.join(disks)), dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Cannot set BIOS HDD sequence to: %s!', ','.join(disks))
                return False
            self._bios_settings_changed = True
        return True

    def _ConfigureBootSequence(self):
        logging.info('Current BIOS boot sequence: %s', ','.join(self._bios_boot_sequence))
        boot_disks = [ device for device in self._bios_boot_sequence if device.startswith('HardDisk.')
                     ]
        if not boot_disks:
            logging.error('No hard disks in the BIOS boot list!')
            return False
        boot_disks.sort()
        boot_disks += [ device for device in self._bios_boot_sequence if device not in boot_disks
                      ]
        if self._bios_boot_sequence != boot_disks:
            logging.info('Setting the BIOS boot sequence to: %s', ','.join(boot_disks))
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s set BIOS.BiosBootSettings.BootSeq %s' % (
             self._idracadm_path, ','.join(boot_disks)), dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Cannot set BIOS boot sequence to: %s!', ','.join(boot_disks))
                return False
            self._bios_settings_changed = True
        return True

    def ConfigureBootOrder(self):
        success = self._ConfigureHddSequence()
        success = self._ConfigureBootSequence() and success
        if not success:
            utils.Print('WARNING: BIOS boot order update failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def CreateBIOSJobQueue(self):
        if self._bios_settings_changed:
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s jobqueue create BIOS.Setup.1-1' % self._idracadm_path, dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Cannot create BIOS job queue')
                utils.Print('WARNING: BIOS update job creation failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0]


class PlatformDellR430(PlatformDell):
    """Dell R430."""

    @classmethod
    def GetName(cls):
        return 'Dell-R430'

    @classmethod
    def _CheckModel(cls, model):
        return '430' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return network == [
         platformutils.SUPPORTED_NETWORK_CARDS['BCM5720']]

    @classmethod
    def _CheckStorage(cls, storage):
        return storage == [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI']]


platformutils.RegisterHardwarePlatform(PlatformDellR430)

class PlatformDellR430_MLX(PlatformDell):
    """Dell R430/Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R430-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '430' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return storage == [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI']]

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR430_MLX)

class PlatformDellR630(PlatformDell):
    """Dell R630."""

    @classmethod
    def GetName(cls):
        return 'Dell-R630'

    @classmethod
    def _CheckModel(cls, model):
        return '630' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return network == [
         platformutils.SUPPORTED_NETWORK_CARDS['BCM57800']]

    @classmethod
    def _CheckStorage(cls, storage):
        return storage == [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H730_MINI']]

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR630)

class PlatformDellR630_MLX(PlatformDell):
    """Dell R630/Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R630-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '630' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return storage == [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H730_MINI']]

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR630_MLX)

class PlatformDellR710(PlatformDell):
    """Dell R710."""
    DEFAULT_MEGACLI_PATH = '/usr/local/sbin/MegaCli'

    @classmethod
    def GetName(cls):
        return 'Dell-R710'

    @classmethod
    def _CheckModel(cls, model):
        return '710' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['BCM5709'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_6I'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H700']]

    def _ReadBootSequence(self):
        """Read the current BootSeq and HddSeq from the BIOS.
        
        Returns:
          Boolean indicating if we were able to read BIOS settings.
        """
        self._bios_boot_sequence = self._GetBIOSSequence('BootSeq')
        self._bios_hdd_sequence = self._GetBIOSSequence('HddSeq')
        if self._bios_boot_sequence is None or self._bios_hdd_sequence is None:
            return False
        else:
            return True

    def _GetBIOSSequence(self, sequence_name):
        """Read the current HddSeq from the BIOS.
        
        Get the current value for a Dell R710 BIOS configuration sequence.
        
        Arguments:
          sequence_name: a BIOS sequence name. The currently supported values are
                         'BootSeq' and 'HddSeq'.
        
        Returns:
          A list of entries. It may be an empty list.
          None if we're unable to communicate with the BIOS.
          An empty list does not mean there are no entries. Only that we don't have
          multiple options to choose from.
        """
        stdout, unused_err, ret_code = utils.RunCommand('%s --%s' % (self._syscfg_path, sequence_name))
        if ret_code == 117:
            logging.info('No value for %s.', sequence_name)
            return []
        else:
            if ret_code != 0:
                logging.error('Failed to read %s.', sequence_name)
                return None
            return self._ParseBIOSSequence(stdout)

    def _ParseBIOSSequence(self, output):
        """Parse device lists as formatted by syscfg.
        
        Arguments:
          output: the full output as generated by syscfg.
        
        Returns:
          A list of BIOS device names. It may be an empty list.
          None if we're unable to parse it.
        """
        if output.startswith('The following devices are set in the '):
            entries = output.splitlines()
            try:
                devices = [ entry.split(' ')[2] for entry in entries if entry.startswith('Device ')
                          ]
            except IndexError:
                return None

            return devices
        else:
            return None

    def _GetBIOSScalar(self, name):
        """Read scalar values from the BIOS.
        
        Read scalar values (such as f1f2promptonerror or bootmode) from the BIOS.
        
        Arguments:
          name: name of the scalar setting.
        
        Returns:
          A string value or None is the command failed.
        """
        stdout, unused_err, ret_code = utils.RunCommand('%s --%s' % (self._syscfg_path, name))
        if ret_code != 0:
            logging.error('Failed to read %s.', name)
            return None
        else:
            return self._ParseBIOSScalar(stdout)

    def _ParseBIOSScalar(self, output):
        """Parse scalar values in the syscfg's output.
        
        Arguments:
           output: syscfg output.
        
        Returns:
          A string value or None is the string is not parsable.
        """
        lines = output.split('\n', 1)
        if not lines:
            return None
        else:
            tokens = lines[0].split('=', 1)
            if not tokens or len(tokens) < 2:
                return None
            return tokens[1]

    def ConfigureBIOS(self):
        success = True
        if self._GetBIOSScalar('bootmode') != 'bios':
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s --bootmode=bios' % self._syscfg_path, dry_run=self._dry_run)
            if ret_code != 0:
                success = False
                logging.error('Cannot set boot mode to BIOS!')
            else:
                self._bios_settings_changed = True
        if self._GetBIOSScalar('f1f2promptonerror') != 'disable':
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s --f1f2promptonerror=disable' % self._syscfg_path, dry_run=self._dry_run)
            if ret_code != 0:
                success = False
                logging.error('Cannot disable F1 prompt on errors!')
            else:
                self._bios_settings_changed = True
        if not success:
            utils.Print('WARNING: BIOS settings update failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def _ConfigureHddSequence(self):
        logging.info('Current BIOS HDD sequence: %s', ','.join(self._bios_hdd_sequence))
        if not self._bios_hdd_sequence:
            return True
        disks = [ device for device in self._bios_hdd_sequence if device.startswith('sasraid.emb.')
                ]
        if not disks:
            logging.error('No internal disks in the BIOS HDD list!')
            return False
        disks.sort()
        disks += [ device for device in self._bios_hdd_sequence if device not in disks
                 ]
        if self._bios_hdd_sequence != disks:
            logging.info('Setting the BIOS HDD sequence to: %s', ','.join(disks))
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s --HddSeq=%s' % (self._syscfg_path, ','.join(disks)), dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Cannot set BIOS HDD sequence to: %s!', ','.join(disks))
                return False
            self._bios_settings_changed = True
        return True

    def _ConfigureBootSequence(self):
        logging.info('Current BIOS boot sequence: %s', ','.join(self._bios_boot_sequence))
        boot_disks = [ device for device in self._bios_boot_sequence if device.startswith('hdd.emb.')
                     ]
        if not boot_disks:
            logging.error('No hard disks in the BIOS boot list!')
            return False
        boot_disks.sort()
        boot_disks += [ device for device in self._bios_boot_sequence if device not in boot_disks
                      ]
        if self._bios_boot_sequence != boot_disks:
            logging.info('Setting the BIOS boot sequence to: %s', ','.join(boot_disks))
            unused_stdout, unused_err, ret_code = utils.RunCommand('%s --BootSeq=%s' % (self._syscfg_path, ','.join(boot_disks)), dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Cannot set BIOS boot sequence to: %s!', ','.join(boot_disks))
                return False
            self._bios_settings_changed = True
        return True

    def CreateBIOSJobQueue(self):
        return True


platformutils.RegisterHardwarePlatform(PlatformDellR710)

class PlatformDellR720(PlatformDell):
    """Dell R720 1st generation."""

    @classmethod
    def GetName(cls):
        return 'Dell-R720'

    @classmethod
    def _CheckModel(cls, model):
        return '720' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return network == [platformutils.SUPPORTED_NETWORK_CARDS['BCM5720']]

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H310_MINI'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H710_MINI']]


platformutils.RegisterHardwarePlatform(PlatformDellR720)

class PlatformDellR720_10G(PlatformDell):
    """Dell R720 2nd generation."""

    @classmethod
    def GetName(cls):
        return 'Dell-R720-10G'

    @classmethod
    def _CheckModel(cls, model):
        return '720' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return network == [platformutils.SUPPORTED_NETWORK_CARDS['BCM57800']]

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H310_MINI'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H710_MINI']]


platformutils.RegisterHardwarePlatform(PlatformDellR720_10G)

class PlatformDellR720_MLX(PlatformDell):
    """Dell R720 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R720-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '720' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H310_MINI'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H710_MINI']]


platformutils.RegisterHardwarePlatform(PlatformDellR720_MLX)

class PlatformDellR730(PlatformDell):
    """Dell R730."""

    @classmethod
    def GetName(cls):
        return 'Dell-R730'

    @classmethod
    def _CheckModel(cls, model):
        return '730' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return (platformutils.SUPPORTED_NETWORK_CARDS['BCM57800'] in network or platformutils.SUPPORTED_NETWORK_CARDS['BCM57810'] in network) and all((netdev.vendor_id == platformutils.PCI_VENDOR_BROADCOM for netdev in network))

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H730_MINI']]

    def GetRootDiskPhysicalDriveIds(self):
        return [
         12, 13]


platformutils.RegisterHardwarePlatform(PlatformDellR730)

class PlatformDellR730_MLX(PlatformDell):
    """Dell R730 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R730-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '730' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return len(storage) == 1 and storage[0] in [
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'],
         platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H730_MINI']]

    def GetRootDiskPhysicalDriveIds(self):
        return [
         12, 13]


platformutils.RegisterHardwarePlatform(PlatformDellR730_MLX)

class PlatformDellR440(PlatformDell):
    """Dell R440."""

    @classmethod
    def GetName(cls):
        return 'Dell-R440'

    @classmethod
    def _CheckModel(cls, model):
        return '440' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['BCM5720'] in network and all((netdev.vendor_id == platformutils.PCI_VENDOR_BROADCOM for netdev in network))

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'] in storage


platformutils.RegisterHardwarePlatform(PlatformDellR440)

class PlatformDellR440_MLX(PlatformDell):
    """Dell R440 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R440-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '440' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'] in storage

    def PrepareNetworkDevice(self):
        """Set sane ports types on ConnectX3 40G NIC.
        
        Since OOB on Dell works only on the 1st port, set 1st port to Ethernet
        to force the NIC to always bring up an eth interface, even if nothing is
        plugged in.
        
        Returns:
          Configuration status from ifconfig.ConfigureMellanoxNic()
          or True if no setup is necessary.
        """
        mlx_address = platformutils.GetDevicePciAddress(platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'], True)
        if not mlx_address:
            return True
        vendor_id, device_id = platformutils.GetDeviceSubsystemId(mlx_address)
        if vendor_id == platformutils.PCI_VENDOR_MELLANOX and device_id == platformutils.PCI_SUBSYSTEM_DEVICE_MLX_CONNECTX3PRO40G:
            return True
        return ifconfig.ConfigureMellanoxNic(mlx_address, self._mstconfig_path, {1: ifconfig.MLX_LINK_TYPE_ETHERNET,2: ifconfig.MLX_LINK_TYPE_INFINIBAND
           })

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR440_MLX)

class PlatformDellR740_MLX(PlatformDell):
    """Dell R740 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R740-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '740' in model and 'xd2' not in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX4'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_SAS_CONTROLLERS['HBA330'] in storage and platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'] in storage

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR740_MLX)

class PlatformDellR740XD2_MLX(PlatformDell):
    """Dell R740xd2 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R740xd2-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '740xd2' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX4'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_SAS_CONTROLLERS['HBA330'] in storage and platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H330_MINI'] in storage

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0]


platformutils.RegisterHardwarePlatform(PlatformDellR740XD2_MLX)

class PlatformDellR640_MLX(PlatformDell):
    """Dell R640 / Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Dell-R640-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return '640' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27500'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_RAID_CONTROLLERS['PERC_H730_MINI'] in storage

    def PrepareNetworkDevice(self):
        """Set sane ports types on ConnectX3 40G NIC.
        
        Since OOB on Dell works only on the 1st port, set 1st port to Ethernet
        to force the NIC to always bring up an eth interface, even if nothing is
        plugged in.
        
        Returns:
          Configuration status from ifconfig.ConfigureMellanoxNic()
          or True if no setup is necessary.
        """
        mlx_address = platformutils.GetDevicePciAddress(platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'], True)
        if not mlx_address:
            return True
        vendor_id, device_id = platformutils.GetDeviceSubsystemId(mlx_address)
        if vendor_id == platformutils.PCI_VENDOR_MELLANOX and device_id == platformutils.PCI_SUBSYSTEM_DEVICE_MLX_CONNECTX3PRO40G:
            return True
        return ifconfig.ConfigureMellanoxNic(mlx_address, self._mstconfig_path, {1: ifconfig.MLX_LINK_TYPE_ETHERNET,2: ifconfig.MLX_LINK_TYPE_INFINIBAND
           })

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0, 1]


platformutils.RegisterHardwarePlatform(PlatformDellR640_MLX)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/platform_dell.pyc
