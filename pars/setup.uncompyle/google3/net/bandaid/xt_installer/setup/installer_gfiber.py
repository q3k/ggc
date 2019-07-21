# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/installer_gfiber.py
# Compiled at: 2019-06-18 16:41:38
"""Installer implementation for Google Fiber deployments."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
from google3.net.bandaid.xt_installer.setup import installer

class InstallerGfiber(installer.Installer):
    """Tracks the state of the installation.
    
    This class supports only Gfiber deployments.
    """
    PLATFORM = 'GFiber'
    MIN_PREFIX_LEN = 24
    MAX_PREFIX_LEN = 28
    FIRST_HOST_INDEX = 4
    LAST_HOST_INDEX = 11
    GATEWAY_INDEX = 1
    IPV6_PREFIX_LEN = 64

    def GetNicConfigFromUser(self):
        """Propose which NIC(s) need to be configured.
        
        Configurations to be supported: see b/28561292
        <1> R630: 2x10Ge Mellanox with LACP
        <2> R630: 2x10Ge with LACP
        <3> R720: 2x10Ge with LACP
        
        Returns:
          True if expected intefaces have been found. False otherwise.
        """
        if not self.machine.ten_ge_interfaces:
            return False
        if self.machine.mlx_interfaces:
            self._interfaces_to_configure = self.machine.mlx_interfaces
        else:
            self._interfaces_to_configure = self.machine.ten_ge_interfaces
        self._lacp_guess = True
        self._FinalizeNICConfiguration(self._PromptUserForLacp())
        return True
# okay decompiling ./google3/net/bandaid/xt_installer/setup/installer_gfiber.pyc
