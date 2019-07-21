# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/sax.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xml.sax
"""
from __future__ import print_function, absolute_import
from xml.sax import InputSource as _InputSource
from xml.sax import ErrorHandler as _ErrorHandler
from . import expatreader
__origin__ = 'xml.sax'

def parse(source, handler, errorHandler=_ErrorHandler(), forbid_dtd=False, forbid_entities=True, forbid_external=True):
    parser = make_parser()
    parser.setContentHandler(handler)
    parser.setErrorHandler(errorHandler)
    parser.forbid_dtd = forbid_dtd
    parser.forbid_entities = forbid_entities
    parser.forbid_external = forbid_external
    parser.parse(source)


def parseString(string, handler, errorHandler=_ErrorHandler(), forbid_dtd=False, forbid_entities=True, forbid_external=True):
    from io import BytesIO
    if errorHandler is None:
        errorHandler = _ErrorHandler()
    parser = make_parser()
    parser.setContentHandler(handler)
    parser.setErrorHandler(errorHandler)
    parser.forbid_dtd = forbid_dtd
    parser.forbid_entities = forbid_entities
    parser.forbid_external = forbid_external
    inpsrc = _InputSource()
    inpsrc.setByteStream(BytesIO(string))
    parser.parse(inpsrc)
    return


def make_parser(parser_list=[]):
    return expatreader.create_parser()
# okay decompiling ./google3/third_party/py/defusedxml/sax.pyc
