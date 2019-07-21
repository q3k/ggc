# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/pulldom.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xml.dom.pulldom
"""
from __future__ import print_function, absolute_import
from xml.dom.pulldom import parse as _parse
from xml.dom.pulldom import parseString as _parseString
from .sax import make_parser
__origin__ = 'xml.dom.pulldom'

def parse(stream_or_string, parser=None, bufsize=None, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    if parser is None:
        parser = make_parser()
        parser.forbid_dtd = forbid_dtd
        parser.forbid_entities = forbid_entities
        parser.forbid_external = forbid_external
    return _parse(stream_or_string, parser, bufsize)


def parseString(string, parser=None, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    if parser is None:
        parser = make_parser()
        parser.forbid_dtd = forbid_dtd
        parser.forbid_entities = forbid_entities
        parser.forbid_external = forbid_external
    return _parseString(string, parser)
# okay decompiling ./google3/third_party/py/defusedxml/pulldom.pyc
