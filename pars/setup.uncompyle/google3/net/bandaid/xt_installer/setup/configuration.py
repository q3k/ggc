# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/configuration.py
# Compiled at: 2019-06-18 16:41:38
"""Installer configuration reader and accessor."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
import ConfigParser
import logging
import re
import ipaddr
from google3.net.bandaid.xt_installer.setup import installer
from google3.net.bandaid.xt_installer.setup import installer_ec
from google3.net.bandaid.xt_installer.setup import installer_gfiber
from google3.net.bandaid.xt_installer.setup import installer_marconi
from google3.net.bandaid.xt_installer.setup import installer_towerbridge
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils

class ConfigurationError(Exception):
    """Error processing configuration entries."""
    pass


class ConfigurationKeyError(ConfigurationError):
    """Error changing incorrect configuration entry."""
    pass


class ConfigurationValueError(ConfigurationError):
    """Error changing configuration entry with incorrect value."""
    pass


class Configuration(object):
    """Holds configuration data used for installation.
    
    
    """
    INSTALLER_PLATFORMS = {'xt': installer.Installer,
       'ec': installer_ec.InstallerEC,
       'ec2': installer_ec.InstallerEC,
       'gfiber': installer_gfiber.InstallerGfiber,
       'marconi': installer_marconi.InstallerMarconi,
       'towerbridge': installer_towerbridge.InstallerTowerBridge
       }
    RACK_CONFIG_RE = re.compile('(?P<svctag>[0-9A-Za-z]+)\n      [ \\t;,]+\n      (?P<network>((\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3})|\n                   ((?:[0-9A-Fa-f]{0,4}:){1,7}[0-9A-Fa-f]{0,4})))\n                   (/(?P<prefix>\\d{1,2}))?\n      [ \\t;,]+\n      (?P<machine>\\d{1,2})\n      ', re.VERBOSE)

    def __init__(self, proc_cmdline='/proc/cmdline', config_file='/lib/live/mount/medium/installer.cfg', network_config_file='/lib/live/mount/medium/network.cfg', rack_config_file='/lib/live/mount/medium/rack.cfg', live_mountpoint='/lib/live/mount/medium'):
        self._proc_cmdline = proc_cmdline
        self._config_file = config_file
        self._network_config_file = network_config_file
        self._rack_config_file = rack_config_file
        self._live_mountpoint = live_mountpoint
        self.installer_config = {'platform': 'xt',
           'prompt': None,
           'pxe': None
           }
        self.network_config = {'subnet': None,
           'ipaddress': None,
           'netmask': None,
           'gateway': None,
           'lacp': None,
           'machine': 0
           }
        self.Read()
        return

    @property
    def platform(self):
        if self.installer_config['platform'] not in self.INSTALLER_PLATFORMS:
            logging.info('Unknown or unset platform: %s, assuming XT', self.installer_config['platform'])
            self.installer_config['platform'] = 'xt'
        return self.installer_config['platform']

    @property
    def prompt(self):
        if self.installer_config['prompt'] is None:
            self.installer_config['prompt'] = True
        return self.installer_config['prompt']

    @property
    def pxe(self):
        if self.installer_config['pxe'] is None:
            self.installer_config['pxe'] = False
        return self.installer_config['pxe']

    @property
    def subnet(self):
        return self.network_config['subnet']

    @property
    def ipaddress(self):
        return self.network_config['ipaddress']

    @property
    def netmask(self):
        return self.network_config['netmask']

    @property
    def gateway(self):
        return self.network_config['gateway']

    @property
    def lacp(self):
        return self.network_config['lacp']

    @property
    def machine_number(self):
        return self.network_config['machine']

    @property
    def installer(self):
        return self.INSTALLER_PLATFORMS[self.platform]

    def SetNetworkParameter(self, key, value):
        if key not in self.network_config:
            raise ConfigurationKeyError(key)
        try:
            if key == 'subnet':
                self.network_config[key] = ipaddr.IPNetwork(value)
            if key == 'netmask':
                if value != 64:
                    value = ipaddr.IPAddress(value)
                self.network_config[key] = value
            if key in ('ipaddress', 'gateway'):
                self.network_config[key] = ipaddr.IPAddress(value)
            if key == 'lacp':
                self.network_config[key] = bool(value)
            if key == 'machine':
                self.network_config[key] = int(value)
        except ValueError as e:
            raise ConfigurationValueError(e)

    def _ParseIPAddressFromConfigValue(self, value):
        """Return 'value' as an IPAddress.
        
        Args:
          value: The raw parameter to convert.
        
        Returns:
          An IPAddress or None if the 'value' couldn't be parsed.
        """
        if not value:
            return None
        else:
            ipaddress = str(value)
            try:
                return ipaddr.IPAddress(ipaddress)
            except ValueError as e:
                logging.error('Invalid config value %r for IP address: %s', value, e)

            return None

    def _ParseIPNetworkFromConfigValue(self, value, mask):
        """Return 'value' or 'value/mask' as an IPNetwork.
        
        Args:
          value: The raw parameter to convert.
          mask: Netmask to use for conversion to IPNetwork.
        
        Returns:
          An IPNetwork or None if the 'value' couldn't be parsed.
        """
        if not value:
            return None
        else:
            ipaddress = str(value)
            netmask = str(mask)
            try:
                if '/' in ipaddress:
                    return ipaddr.IPNetwork(ipaddress)
                return ipaddr.IPNetwork(ipaddress + '/' + netmask)
            except ValueError as e:
                logging.error('Invalid config value %r for IP network: %s', value, e)

            return None

    def ReadInstallerConfigurationFile(self):
        """Read options from configuration file."""
        logging.info('Reading Installer configuration file %s', self._config_file)
        config = ConfigParser.RawConfigParser()
        try:
            if config.read(self._config_file):
                section = 'installer'
                try:
                    section_data = dict(config.items(section))
                    self.installer_config['platform'] = section_data.pop('platform', 'xt')
                    self.installer_config['prompt'] = section_data.pop('prompt', None)
                    while section_data:
                        logging.info('Unknown parameter in [installer] section: %r', section_data.popitem())

                except ConfigParser.NoSectionError:
                    logging.warning('Missing [installer] section in configuration file %s', self._config_file)

            else:
                logging.info('Config file %s not found.', self._config_file)
        except ConfigParser.MissingSectionHeaderError:
            logging.warning('Missing [installer] section in configuration file %s', self._config_file)
        except ConfigParser.ParsingError as e:
            logging.warning('Junk in Installer configuration file %s: %s', self._config_file, str(e))

        logging.info('Raw Installer settings after parsing %s: %r', self._config_file, self.installer_config)
        self._ValidateInstallerConfiguration()
        return

    def ReadNetworkConfigurationFile(self):
        """Read options from configuration file."""
        logging.info('Reading network configuration file %s', self._network_config_file)
        config = ConfigParser.RawConfigParser()
        try:
            if config.read(self._network_config_file):
                section = 'network'
                try:
                    section_data = dict(config.items(section))
                    self.network_config['ipaddress'] = section_data.pop('ipaddress', None)
                    self.network_config['netmask'] = section_data.pop('netmask', None)
                    self.network_config['gateway'] = section_data.pop('gateway', None)
                    self.network_config['subnet'] = section_data.pop('subnet', None)
                    self.network_config['lacp'] = section_data.pop('lacp', None)
                    self.network_config['machine'] = section_data.pop('machine', 0)
                    while section_data:
                        logging.info('Unknown parameter in [network] section: %r', section_data.popitem())

                except ConfigParser.NoSectionError:
                    logging.warning('Missing [network] section in configuration file %s', self._network_config_file)

            else:
                logging.info('Config file %s not found.', self._network_config_file)
        except ConfigParser.MissingSectionHeaderError:
            logging.warning('Missing [network] section in configuration file %s', self._network_config_file)
        except ConfigParser.ParsingError as e:
            logging.warning('Junk in network configuration file %s: %s', self._network_config_file, str(e))

        logging.info('Raw network settings after parsing %s: %r', self._network_config_file, self.network_config)
        self._ValidateNetworkConfiguration()
        return

    def _ParseNetworkConfigurationForMachine(self, config_line, service_tag):
        """Extracts and reports back the ip config if the service tag matches."""
        if not config_line or config_line.startswith('#'):
            return False
        else:
            match = self.RACK_CONFIG_RE.match(config_line)
            if not match:
                return False
            if match.group('svctag') != service_tag:
                return False
            network_match = match.group('network')
            prefix_match = match.group('prefix')
            if not prefix_match:
                if ':' in network_match:
                    prefix_match = '64'
                else:
                    prefix_match = '26'
            network = self._ParseIPNetworkFromConfigValue(network_match, prefix_match)
            if not network:
                return False
            machine = int(match.group('machine'))
            if machine < 1 or machine > network.numhosts:
                logging.error('Machine index %d outside of subnet %s for service tag %s', machine, network, service_tag)
                return False
            self.network_config['machine'] = machine
            self.network_config['ipaddress'] = None
            self.network_config['netmask'] = None
            self.network_config['gateway'] = None
            self.network_config['subnet'] = network
            self.network_config['lacp'] = None
            return True

    def ReadRackConfigurationFile(self):
        """Scan an rack.cfg file."""
        logging.info('Reading rack configuration file %s', self._rack_config_file)
        service_tag = platformutils.GetPlatformSerialNumber()
        try:
            with open(self._rack_config_file, 'r') as rack_config:
                self.network_config = {'subnet': None,
                   'ipaddress': None,
                   'netmask': None,
                   'gateway': None,
                   'lacp': None,
                   'machine': 0
                   }
                for line in rack_config:
                    if self._ParseNetworkConfigurationForMachine(line, service_tag):
                        return

            logging.error('Cannot find config for %s', service_tag)
        except IOError:
            logging.info('Cannot open rack config file %s', self._rack_config_file)

        return

    def ReadConfigurationFromProcCmdline(self):
        """Read configuration from parameters passed in to /proc/cmdline."""
        logging.info('Parsing installer configuration from %s', self._proc_cmdline)
        cmdline = utils.ParseProcCmdline(self._proc_cmdline)
        for key, value in cmdline.iteritems():
            if key.startswith('installer.'):
                option = key[10:]
                if option not in self.installer_config:
                    logging.info('Unknown option "%s" in %s.', key, self._proc_cmdline)
                else:
                    self.installer_config[option] = value
            if key.startswith('network.'):
                option = key[8:]
                if option not in self.network_config:
                    logging.info('Unknown option "%s" in %s.', key, self._proc_cmdline)
                else:
                    self.network_config[option] = value

        logging.info('Raw Installer settings after parsing %s: %r', self._proc_cmdline, self.installer_config)
        logging.info('Raw network settings after parsing %s: %r', self._proc_cmdline, self.network_config)
        self._ValidateInstallerConfiguration()
        self._ValidateNetworkConfiguration()

    def _CheckTrue(self, value):
        return str(value).strip().lower()[0] in ('t', '1', 'y')

    def _ValidateInstallerConfiguration(self):
        """Check configuration settings for validity.
        
        Performs type checks of the options and resets incorrect to None.
        """
        if self.installer_config['prompt'] is not None:
            self.installer_config['prompt'] = self._CheckTrue(self.installer_config['prompt'])
        if self.installer_config['pxe'] is not None:
            self.installer_config['pxe'] = self._CheckTrue(self.installer_config['pxe'])
        return

    def _ValidateNetworkConfiguration(self):
        """Check configuration settings for validity.
        
        Performs type checks of the options and resets incorrect to None.
        """
        if self.network_config['lacp'] is not None:
            self.network_config['lacp'] = self._CheckTrue(self.network_config['lacp'])
        self.network_config['ipaddress'] = self._ParseIPAddressFromConfigValue(self.network_config['ipaddress'])
        self.network_config['gateway'] = self._ParseIPAddressFromConfigValue(self.network_config['gateway'])
        self.network_config['netmask'] = self._ParseIPAddressFromConfigValue(self.network_config['netmask'])
        if self.network_config['ipaddress'] and self.network_config['ipaddress'].version == 6:
            self.network_config['netmask'] = self.installer.IPV6_PREFIX_LEN
        parsed_subnet = self._ParseIPNetworkFromConfigValue(self.network_config['subnet'], self.network_config['netmask'])
        if parsed_subnet:
            self.network_config['subnet'] = parsed_subnet
        else:
            self.network_config['subnet'] = self._ParseIPNetworkFromConfigValue(self.network_config['ipaddress'], self.network_config['netmask'])
        try:
            self.network_config['machine'] = int(self.network_config['machine'])
        except ValueError:
            self.network_config['machine'] = 0

        return

    def Read(self):
        """Read installer configuration from all known sources.
        
        Raises:
          ConfigurationError: if required options are missing in non interactive
                              mode.
        """
        self.ReadInstallerConfigurationFile()
        self.ReadNetworkConfigurationFile()
        self.ReadRackConfigurationFile()
        self.ReadConfigurationFromProcCmdline()
        logging.info('Installer configured for platform: %s', self.platform)
        logging.info('Installer configured in interactive mode: %s', self.prompt)
        logging.info('Configured IP address: %s', self.ipaddress)
        logging.info('Configured IP netmask: %s', self.netmask)
        logging.info('Configured IP gateway: %s', self.gateway)
        logging.info('Configured IP subnet: %s', self.subnet)
        logging.info('Configured LACP: %s', self.lacp)
        logging.info('Configured machine number: %d', self.machine_number)
        if not self.prompt:
            if self.ipaddress and self.netmask:
                return
            if self.subnet and self.machine_number:
                return
            raise ConfigurationError('Missing IP configuration data.')

    def Write(self, force=False):
        """Save configuration files on the boot device.
        
        Unconditionally save network configuration file, save installer
        configuration only if explicitly told to. Installer needs to keep last good
        network settings for reuse, but does not need to keep install type which is
        menu/boot time driven.
        
        Args:
          force: Force saving installer configuration (bool).
        """
        if self.pxe:
            logging.info('PXE booted, not writing config file.')
            return
        unused_stdout, unused_stderr, exitcode = utils.RunCommand('/bin/mount -o remount,rw %s' % self._live_mountpoint)
        if exitcode != 0:
            logging.warning('Cannot remount %s, cannot save configuration file(s).', self._live_mountpoint)
            return
        if force:
            logging.info('Forced to save installer config file: %s', self._config_file)
            config = ConfigParser.RawConfigParser()
            section = 'installer'
            config.add_section(section)
            for key, value in sorted(self.installer_config.iteritems()):
                config.set(section, key, value)

            try:
                with open(self._config_file, 'w') as installer_config:
                    config.write(installer_config)
            except IOError:
                logging.warning('Cannot save installer configuration to %s.', self._config_file)

        else:
            logging.info('Not writing installer config file: %s', self._config_file)
        logging.info('Writing network config file: %s', self._network_config_file)
        config = ConfigParser.RawConfigParser()
        section = 'network'
        config.add_section(section)
        for key, value in sorted(self.network_config.iteritems()):
            config.set(section, key, value)

        try:
            with open(self._network_config_file, 'w') as network_config:
                config.write(network_config)
        except IOError:
            logging.warning('Cannot save network configuration to %s.', self._network_config_file)

        utils.RunCommand('/bin/mount -o remount,ro %s' % self._live_mountpoint)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/configuration.pyc
