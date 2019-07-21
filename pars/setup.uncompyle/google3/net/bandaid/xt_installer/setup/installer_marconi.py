# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/installer_marconi.py
# Compiled at: 2019-06-18 16:41:38
"""Installer implementation for Marconi deployments."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
from google3.net.bandaid.xt_installer.setup import installer

class InstallerMarconi(installer.Installer):
    """Tracks the state of the installation.
    
    This class supports only Marconi deployments.
    """
    PLATFORM = 'Marconi'
    MIN_PREFIX_LEN = 24
    MAX_PREFIX_LEN = 28
    FIRST_HOST_INDEX = 4
    LAST_HOST_INDEX = 11
    GATEWAY_INDEX = 1
    IPV6_PREFIX_LEN = 64

    def GetNicConfigFromUser(self):
        """Propose which NIC(s) need to be configured.
        
        Configurations to be supported: see b/12660436, b/110367601
        <1> R720 (legacy): 2x10Ge Mellanox with LACP
        <2> R630: 2x10Ge Mellanox with LACP
        <3> R440: 2x10Ge Mellanox with LACP
        <4> R440: 1x40Ge Mellanox without LACP
        <5> R640: 1x40Ge Mellanox without LACP
        
        Returns:
          True if expected intefaces have been found. False otherwise.
        """
        if not self.machine.mlx_interfaces:
            return False
        self._interfaces_to_configure = self.machine.mlx_interfaces
        if not self.machine.forty_ge_interfaces:
            self._lacp_guess = True
        else:
            self._lacp_guess = False
        self._kmod_blacklist = 'bnxt_en,bnx2x,tg3'
        self._FinalizeNICConfiguration(self._PromptUserForLacp())
        return True
# okay decompiling ./google3/net/bandaid/xt_installer/setup/installer_marconi.pyc
