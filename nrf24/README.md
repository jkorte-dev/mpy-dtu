Micropython Driver for Nordic Semiconductor nRF24L01 radio module
=======================================================================

This nRF24L01 driver supports `auto acknowledge` and `dynamic payloads` in contrast to the official Micropython driver. It's a port of the Adafruit CircuitPython driver [1] to Micropython.
The API is unchanged except initialization. Therefore the excellent documentation from Adafruit [2] is still valid. 
As the driver consumes a lot of memory I recommend installing the driver as an mpy module. You can achieve this by using Micropython `mip`.

```code
 mpremote mip install --index https://github.com/jkorte-dev/mpy-dtu/nrf24 nrf24
```

References
----------

- [1] https://github.com/nRF24/CircuitPython_nRF24L01
- [2] https://circuitpython-nrf24l01.readthedocs.io/en/latest/
