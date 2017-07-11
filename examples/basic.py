import asyncio
import logging

# Add project directory to the search path so that version of the module
# is used for tests.
import sys
import os
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '..'))

from russound_rio import Russound, ZoneID, CommandException  # noqa: E402


@asyncio.coroutine
def demo(loop, host):
    rus = Russound(loop, host)
    yield from rus.connect()

    print("Determining valid zones")
    # Determine Zones
    valid_zones = []

    @asyncio.coroutine
    def try_watch_zone(zone_id):
        try:
            yield from rus.watch_zone(zone_id)
            return zone_id
        except CommandException:
            return None

    for controller in range(1, 17):
        futures = [try_watch_zone(ZoneID(x, controller))
                   for x in range(1, 17)]
        results = yield from asyncio.gather(*futures)
        if any(results):
            valid_zones.extend([x for x in results if x])
        else:
            break

    for zone_id in valid_zones:
        name = yield from rus.get_zone_variable(zone_id, 'name')
        print("%s: %s" % (zone_id, name))

    yield from rus.watch_zone(ZoneID(1))
    yield from asyncio.sleep(1)
    yield from rus.send_zone_event(ZoneID(1), "KeyPress", "Volume", 40)
    yield from asyncio.sleep(1)
    r = yield from rus.get_zone_variable(ZoneID(1), "volume")
    print("Volume:", r)
    source = rus.get_cached_zone_variable(ZoneID(1), "currentsource")
    name = yield from rus.get_source_variable(source, 'name')
    print("Zone 1 source name: %s" % name)
    yield from rus.close()
    print("Done")


logging.basicConfig(level=logging.DEBUG)
loop = asyncio.get_event_loop()
loop.set_debug(True)
loop.run_until_complete(demo(loop, sys.argv[1]))
loop.close()
