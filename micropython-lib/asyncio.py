from uasyncio import *


def __getattr__(attr):
    import uasyncio

    return getattr(uasyncio, attr)
