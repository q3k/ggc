# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/installer_towerbridge.py
# Compiled at: 2019-06-18 16:41:38
"""Installer implementation for TowerBridge deployments."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
from google3.net.bandaid.xt_installer.setup import installer

class InstallerTowerBridge(installer.Installer):
    """Tracks the state of the installation.
    
    This class supports only TowerBridge deployments.
    """
    PLATFORM = 'TowerBridge'
    MIN_PREFIX_LEN = 24
    MAX_PREFIX_LEN = 30
    FIRST_HOST_INDEX = 2
    LAST_HOST_INDEX = -2
    GATEWAY_INDEX = 1

    def GetNicConfigFromUser(self):
        """Propose which NIC(s) need to be configured.
        
        Configurations to be supported: see b/12660436
        <1> R720 (legacy): 1x10Ge without LACP
        <2> R630: 1x10Ge without LACP
        
        Returns:
          True if expected intefaces have been found. False otherwise.
        """
        if not self.machine.ten_ge_interfaces:
            return False
        ten_ge_ifaces_up = [ iface for iface in self.machine.ten_ge_interfaces if iface in self.machine.interfaces_with_link
                           ]
        if ten_ge_ifaces_up:
            self._interfaces_to_configure = ten_ge_ifaces_up
        else:
            self._interfaces_to_configure = self.machine.ten_ge_interfaces
        self._lacp_guess = False
        self._FinalizeNICConfiguration(self._PromptUserForLacp())
        return True
# okay decompiling ./google3/net/bandaid/xt_installer/setup/installer_towerbridge.pyc
