# stripped down to a minimum from cpython crcmod
# https://crcmod.sourceforge.net/intro.html#license
# mkCrcFun 0x18005 0xffff, True 0 => _crc16r (modbus)
# mkCrcFun 0x101 0 True 0 => _crc8r

def mkCrcFun(poly, initCrc=~0, xorOut=0):
    if xorOut != 0:
        raise ValueError("not implemented")
    if poly == 0x101:
        sizeBits = 8
        _fun = _crc8r
        #print("_crc8r")
    elif poly == 0x18005:
        sizeBits = 16
        _fun = _crc16r
        #print("_crc16r (modbus)")
    else:
        raise ValueError("not implemented")

    _table = _mkTable_r(poly, sizeBits)

    def crcfun(data, crc=initCrc, table=_table, fun=_fun):
        return fun(data, crc, table)

    return crcfun


def _crc8r(data, crc, table):
    crc = crc & 0xFF
    for x in data:
        crc = table[x ^ crc]
    return crc


def _crc16r(data, crc, table):
    crc = crc & 0xFFFF
    for x in data:
        crc = table[x ^ (crc & 0xFF)] ^ (crc >> 8)
    return crc


def _mkTable_r(poly, n):  # n= sizebits
    mask = (1 << n) - 1
    poly = _bitrev(poly & mask, n)
    table = [_bytecrc_r(i, poly, n) for i in range(256)]
    return table


def _bitrev(x, n):
    y = 0
    for i in range(n):
        y = (y << 1) | (x & 1)
        x = x >> 1
    return y


def _bytecrc_r(crc, poly, n):
    for i in range(8):
        if crc & 1:
            crc = (crc >> 1) ^ poly
        else:
            crc = crc >> 1
    mask = (1 << n) - 1
    crc = crc & mask
    return crc
