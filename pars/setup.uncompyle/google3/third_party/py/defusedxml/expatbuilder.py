# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/third_party/py/defusedxml/expatbuilder.py
# Compiled at: 2019-06-18 16:41:38
"""Defused xml.dom.expatbuilder
"""
from __future__ import print_function, absolute_import
from xml.dom.expatbuilder import ExpatBuilder as _ExpatBuilder
from xml.dom.expatbuilder import Namespaces as _Namespaces
from .common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
__origin__ = 'xml.dom.expatbuilder'

class DefusedExpatBuilder(_ExpatBuilder):
    """Defused document builder"""

    def __init__(self, options=None, forbid_dtd=False, forbid_entities=True, forbid_external=True):
        _ExpatBuilder.__init__(self, options)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities
        self.forbid_external = forbid_external

    def defused_start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise DTDForbidden(name, sysid, pubid)

    def defused_entity_decl(self, name, is_parameter_entity, value, base, sysid, pubid, notation_name):
        raise EntitiesForbidden(name, value, base, sysid, pubid, notation_name)

    def defused_unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        raise EntitiesForbidden(name, None, base, sysid, pubid, notation_name)
        return

    def defused_external_entity_ref_handler(self, context, base, sysid, pubid):
        raise ExternalReferenceForbidden(context, base, sysid, pubid)

    def install(self, parser):
        _ExpatBuilder.install(self, parser)
        if self.forbid_dtd:
            parser.StartDoctypeDeclHandler = self.defused_start_doctype_decl
        if self.forbid_entities:
            parser.EntityDeclHandler = self.defused_entity_decl
            parser.UnparsedEntityDeclHandler = self.defused_unparsed_entity_decl
        if self.forbid_external:
            parser.ExternalEntityRefHandler = self.defused_external_entity_ref_handler


class DefusedExpatBuilderNS(_Namespaces, DefusedExpatBuilder):
    """Defused document builder that supports namespaces."""

    def install(self, parser):
        DefusedExpatBuilder.install(self, parser)
        if self._options.namespace_declarations:
            parser.StartNamespaceDeclHandler = self.start_namespace_decl_handler

    def reset(self):
        DefusedExpatBuilder.reset(self)
        self._initNamespaces()


def parse(file, namespaces=True, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    """Parse a document, returning the resulting Document node.
    
    'file' may be either a file name or an open file object.
    """
    if namespaces:
        build_builder = DefusedExpatBuilderNS
    else:
        build_builder = DefusedExpatBuilder
    builder = build_builder(forbid_dtd=forbid_dtd, forbid_entities=forbid_entities, forbid_external=forbid_external)
    if isinstance(file, str):
        fp = open(file, 'rb')
        try:
            result = builder.parseFile(fp)
        finally:
            fp.close()

    else:
        result = builder.parseFile(file)
    return result


def parseString(string, namespaces=True, forbid_dtd=False, forbid_entities=True, forbid_external=True):
    """Parse a document from a string, returning the resulting
    Document node.
    """
    if namespaces:
        build_builder = DefusedExpatBuilderNS
    else:
        build_builder = DefusedExpatBuilder
    builder = build_builder(forbid_dtd=forbid_dtd, forbid_entities=forbid_entities, forbid_external=forbid_external)
    return builder.parseString(string)
# okay decompiling ./google3/third_party/py/defusedxml/expatbuilder.pyc
