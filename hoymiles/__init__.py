#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hoymiles micro-inverters python shared code
"""
import sys

HOYMILES_DEBUG_LOGGING = False  # ok global
HOYMILES_TRANSACTION_LOGGING = False  # ok global


def hexify_payload(byte_var):  # global
    """
    Represent bytes

    :param bytes byte_var: bytes to be hexlified
    :return: two-byte while-space padded byte representation
    :rtype: str
    """
    return ' '.join([f"{b:02x}" for b in byte_var])


_attrs = {"HoymilesDTU": "dtu"}


# Lazy loader, effectively does:
#   global attr
#   from .mod import attr
def __getattr__(attr):
    mod = _attrs.get(attr, None)
    if mod is None:
        raise AttributeError(attr)
    imp = __import__(mod, None, None, True, 1) if sys.implementation.name == "micropython" \
        else __import__(mod, locals=None, globals=globals(), fromlist=[None], level=1)
    value = getattr(imp, attr)
    globals()[attr] = value
    return value
