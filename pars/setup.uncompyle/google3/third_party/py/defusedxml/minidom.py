# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/minidom.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xml.dom.minidom
"""
from __future__ import print_function, absolute_import
from xml.dom.minidom import _do_pulldom_parse
from . import expatbuilder as _expatbuilder
from . import pulldom as _pulldom
__origin__ = 'xml.dom.minidom'

def parse(file, parser=None, bufsize=None, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    """Parse a file into a DOM by filename or file object."""
    if parser is None and not bufsize:
        return _expatbuilder.parse(file, forbid_dtd=forbid_dtd, forbid_entities=forbid_entities, forbid_external=forbid_external)
    else:
        return _do_pulldom_parse(_pulldom.parse, (file,), {'parser': parser,'bufsize': bufsize,'forbid_dtd': forbid_dtd,
           'forbid_entities': forbid_entities,'forbid_external': forbid_external
           })
        return


def parseString(string, parser=None, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    """Parse a file into a DOM from a string."""
    if parser is None:
        return _expatbuilder.parseString(string, forbid_dtd=forbid_dtd, forbid_entities=forbid_entities, forbid_external=forbid_external)
    else:
        return _do_pulldom_parse(_pulldom.parseString, (string,), {'parser': parser,'forbid_dtd': forbid_dtd,'forbid_entities': forbid_entities,
           'forbid_external': forbid_external
           })
        return
# okay decompiling ./google3/third_party/py/defusedxml/minidom.pyc
