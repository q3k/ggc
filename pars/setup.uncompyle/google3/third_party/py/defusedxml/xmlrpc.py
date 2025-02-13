# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/xmlrpc.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xmlrpclib

Also defuses gzip bomb
"""
from __future__ import print_function, absolute_import
import io
from .common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden, PY3
if PY3:
    __origin__ = 'xmlrpc.client'
    from xmlrpc.client import ExpatParser
    from xmlrpc import client as xmlrpc_client
    from xmlrpc import server as xmlrpc_server
    from xmlrpc.client import gzip_decode as _orig_gzip_decode
    from xmlrpc.client import GzipDecodedResponse as _OrigGzipDecodedResponse
else:
    __origin__ = 'xmlrpclib'
    from xmlrpclib import ExpatParser
    import xmlrpclib as xmlrpc_client
    xmlrpc_server = None
    from xmlrpclib import gzip_decode as _orig_gzip_decode
    from xmlrpclib import GzipDecodedResponse as _OrigGzipDecodedResponse
try:
    import gzip
except ImportError:
    gzip = None

MAX_DATA = 31457280

def defused_gzip_decode(data, limit=None):
    """gzip encoded data -> unencoded data
    
    Decode data using the gzip content encoding as described in RFC 1952
    """
    if not gzip:
        raise NotImplementedError
    if limit is None:
        limit = MAX_DATA
    f = io.BytesIO(data)
    gzf = gzip.GzipFile(mode='rb', fileobj=f)
    try:
        if limit < 0:
            decoded = gzf.read()
        else:
            decoded = gzf.read(limit + 1)
    except IOError:
        raise ValueError('invalid data')

    f.close()
    gzf.close()
    if limit >= 0 and len(decoded) > limit:
        raise ValueError('max gzipped payload length exceeded')
    return decoded


class DefusedGzipDecodedResponse(gzip.GzipFile if gzip else object):
    """a file-like object to decode a response encoded with the gzip
    method, as described in RFC 1952.
    """

    def __init__(self, response, limit=None):
        if not gzip:
            raise NotImplementedError
        self.limit = limit = limit if limit is not None else MAX_DATA
        if limit < 0:
            data = response.read()
            self.readlength = None
        else:
            data = response.read(limit + 1)
            self.readlength = 0
        if limit >= 0 and len(data) > limit:
            raise ValueError('max payload length exceeded')
        self.stringio = io.BytesIO(data)
        gzip.GzipFile.__init__(self, mode='rb', fileobj=self.stringio)
        return

    def read(self, n):
        if self.limit >= 0:
            left = self.limit - self.readlength
            n = min(n, left + 1)
            data = gzip.GzipFile.read(self, n)
            self.readlength += len(data)
            if self.readlength > self.limit:
                raise ValueError('max payload length exceeded')
            return data
        else:
            return gzip.GzipFile.read(self, n)

    def close(self):
        gzip.GzipFile.close(self)
        self.stringio.close()


class DefusedExpatParser(ExpatParser):

    def __init__(self, target, forbid_dtd=False, forbid_entities=True, forbid_external=True):
        ExpatParser.__init__(self, target)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities
        self.forbid_external = forbid_external
        parser = self._parser
        if self.forbid_dtd:
            parser.StartDoctypeDeclHandler = self.defused_start_doctype_decl
        if self.forbid_entities:
            parser.EntityDeclHandler = self.defused_entity_decl
            parser.UnparsedEntityDeclHandler = self.defused_unparsed_entity_decl
        if self.forbid_external:
            parser.ExternalEntityRefHandler = self.defused_external_entity_ref_handler

    def defused_start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise DTDForbidden(name, sysid, pubid)

    def defused_entity_decl(self, name, is_parameter_entity, value, base, sysid, pubid, notation_name):
        raise EntitiesForbidden(name, value, base, sysid, pubid, notation_name)

    def defused_unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        raise EntitiesForbidden(name, None, base, sysid, pubid, notation_name)
        return

    def defused_external_entity_ref_handler(self, context, base, sysid, pubid):
        raise ExternalReferenceForbidden(context, base, sysid, pubid)


def monkey_patch():
    xmlrpc_client.FastParser = DefusedExpatParser
    xmlrpc_client.GzipDecodedResponse = DefusedGzipDecodedResponse
    xmlrpc_client.gzip_decode = defused_gzip_decode
    if xmlrpc_server:
        xmlrpc_server.gzip_decode = defused_gzip_decode


def unmonkey_patch():
    xmlrpc_client.FastParser = None
    xmlrpc_client.GzipDecodedResponse = _OrigGzipDecodedResponse
    xmlrpc_client.gzip_decode = _orig_gzip_decode
    if xmlrpc_server:
        xmlrpc_server.gzip_decode = _orig_gzip_decode
    return
# okay decompiling ./google3/third_party/py/defusedxml/xmlrpc.pyc
