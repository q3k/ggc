# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/cElementTree.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xml.etree.cElementTree
"""
from __future__ import absolute_import
from xml.etree.cElementTree import TreeBuilder as _TreeBuilder
from xml.etree.cElementTree import parse as _parse
from xml.etree.cElementTree import tostring
from xml.etree.ElementTree import iterparse as _iterparse
from .ElementTree import DefusedXMLParser
from .common import _generate_etree_functions
__origin__ = 'xml.etree.cElementTree'
XMLTreeBuilder = XMLParse = DefusedXMLParser
parse, iterparse, fromstring = _generate_etree_functions(DefusedXMLParser, _TreeBuilder, _parse, _iterparse)
XML = fromstring
__all__ = [
 'XML', 'XMLParse', 'XMLTreeBuilder', 'fromstring', 'iterparse',
 'parse', 'tostring']
# okay decompiling ./google3/third_party/py/defusedxml/cElementTree.pyc
