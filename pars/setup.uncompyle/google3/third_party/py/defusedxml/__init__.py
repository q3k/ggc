# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/__init__.py
# Compiled at: 2019-06-18 16:41:38
"""Defuse XML bomb denial of service vulnerabilities
"""
from __future__ import print_function, absolute_import
from .common import DefusedXmlException, DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden, NotSupportedError, _apply_defusing

def defuse_stdlib():
    """Monkey patch and defuse all stdlib packages
    
    :warning: The monkey patch is an EXPERIMETNAL feature.
    """
    defused = {}
    from . import cElementTree
    from . import ElementTree
    from . import minidom
    from . import pulldom
    from . import sax
    from . import expatbuilder
    from . import expatreader
    from . import xmlrpc
    xmlrpc.monkey_patch()
    defused[xmlrpc] = None
    for defused_mod in [cElementTree, ElementTree, minidom, pulldom, sax,
     expatbuilder, expatreader]:
        stdlib_mod = _apply_defusing(defused_mod)
        defused[defused_mod] = stdlib_mod

    return defused


__version__ = '0.5.0'
__all__ = [
 'DefusedXmlException', 'DTDForbidden', 'EntitiesForbidden',
 'ExternalReferenceForbidden', 'NotSupportedError']
# okay decompiling ./google3/third_party/py/defusedxml/__init__.pyc
