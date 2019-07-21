# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/installer_ec.py
# Compiled at: 2019-06-18 16:41:38
"""Installer implementation for Dell EC deployments."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
from google3.net.bandaid.xt_installer.setup import installer

class InstallerEC(installer.Installer):
    """Tracks the state of the installation.
    
    This class supports Dell EC deployments, both legacy and 2.0.
    """
    PLATFORM = 'EC'
    MIN_PREFIX_LEN = 24
    MAX_PREFIX_LEN = 28
    FIRST_HOST_INDEX = 1
    LAST_HOST_INDEX = 18
    GATEWAY_INDEX = -2

    def GetNicConfigFromUser(self):
        """Propose which NIC(s) need to be configured.
        
        Configurations to be supported: see b/12660436
        <1> R720 4x1Ge with LACP - EC 1.0
        <2> R720 (legacy): 1x10Ge Mellanox without LACP - EC 2.0
        <3> R730: 2x10Ge Mellanox with LACP - EC 2.0
        <4> HP APOLLO 4200: 1x40Ge without LACP
        
        Returns:
          True. We setup LACP over all interfaces for EC 1.0
            and over Mellanox interfaces for EC 2.0.
        """
        self._lacp_guess = True
        if not self.machine.mlx_interfaces:
            self._interfaces_to_configure = self.machine.interfaces
        elif not self.machine.forty_ge_interfaces:
            self._interfaces_to_configure = self.machine.mlx_interfaces
        else:
            self._interfaces_to_configure = self.machine.forty_ge_interfaces
            self._lacp_guess = False
        self._FinalizeNICConfiguration(self._PromptUserForLacp())
        return True
# okay decompiling ./google3/net/bandaid/xt_installer/setup/installer_ec.pyc
