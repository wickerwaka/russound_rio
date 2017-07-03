import asyncio
import logging

# Add project directory to the search path so that version of the module
# is used for tests.
import sys
import os
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '..'))

from russound_rio import Russound, ZoneID  # noqa: E402


@asyncio.coroutine
def demo(loop):
    rus = Russound(loop, '192.168.105.116', 9621)
    yield from rus.connect()

    yield from rus.watch_zone(ZoneID(1))
    yield from asyncio.sleep(1)
    yield from rus.send_zone_event(ZoneID(1), "KeyPress", "Volume", 40)
    yield from asyncio.sleep(1)
    r = yield from rus.get_zone_variable(ZoneID(1), "volume")
    print("Volume:", r)
    yield from rus.close()
    print("Done")


logging.basicConfig(level=logging.DEBUG)
loop = asyncio.get_event_loop()
loop.set_debug(True)
loop.run_until_complete(demo(loop))
loop.close()
