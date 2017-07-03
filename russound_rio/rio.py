import asyncio
import re
import logging

logger = logging.getLogger('russound')

_re_response = re.compile(
        r"(?:(?:S\[(?P<source>\d+)\])|(?:C\[(?P<controller>\d+)\]"
        r".Z\[(?P<zone>\d+)\]))\.(?P<variable>\S+)=\"(?P<value>.*)\"")


class CommandException(Exception):
    pass


class UncachedVariable(Exception):
    pass


class ZoneID:
    def __init__(self, zone, controller=1):
        self.zone = int(zone)
        self.controller = int(controller)

    def __str__(self):
        return "%d:%d" % (self.controller, self.zone)

    def __eq__(self, other):
        return hasattr(other, 'zone') and \
            hasattr(other, 'controller') and \
            other.zone == self.zone and \
            other.controller == self.controller

    def __hash__(self):
        return hash(str(self))

    def device_str(self):
        return "C[%d].Z[%d]" % (self.controller, self.zone)


class Russound:
    def __init__(self, loop, host, port):
        self._loop = loop
        self._host = host
        self._port = port
        self._ioloop_future = None
        self._outbound = asyncio.Queue(loop=loop)
        self._source_state = {}
        self._zone_state = {}
        self._watched_zones = set()
        self._watched_sources = set()

    def _process_response(self, res):
        s = str(res, 'utf-8').strip()
        ty, payload = s[0], s[2:]
        if ty == 'E':
            logger.error("Device responded with error: %s", payload)
            raise CommandException(payload)

        m = _re_response.match(payload)
        if not m:
            return ty, None

        logger.debug(payload)

        p = m.groupdict()
        if p['source']:
            source = int(p['source'])
            source_state = self._source_state.setdefault(source, {})
            source_state[p['variable']] = p['value']
            logger.debug("S[%d].%s = %s" % (source, p['variable'], p['value']))
        elif p['zone']:
            zone_id = ZoneID(controller=p['controller'], zone=p['zone'])
            zone_state = self._zone_state.setdefault(zone_id, {})
            zone_state[p['variable']] = p['value']
            logger.debug("%s.%s = %s",
                         zone_id.device_str(), p['variable'], p['value'])

        return ty, p['value']

    @asyncio.coroutine
    def _ioloop(self, reader, writer):
        queue_future = asyncio.ensure_future(
                self._outbound.get(), loop=self._loop)
        net_future = asyncio.ensure_future(
                reader.readline(), loop=self._loop)
        try:
            logger.debug("Starting IO loop")
            while True:
                done, pending = yield from asyncio.wait(
                        [queue_future, net_future],
                        return_when=asyncio.FIRST_COMPLETED,
                        loop=self._loop)

                if net_future in done:
                    response = net_future.result()
                    try:
                        self._process_response(response)
                    except CommandException:
                        pass
                    net_future = asyncio.ensure_future(
                            reader.readline(), loop=self._loop)

                if queue_future in done:
                    cmd, future = queue_future.result()
                    cmd += '\r'
                    writer.write(bytearray(cmd, 'utf-8'))
                    yield from writer.drain()

                    queue_future = asyncio.ensure_future(
                            self._outbound.get(), loop=self._loop)

                    while True:
                        response = yield from net_future
                        net_future = asyncio.ensure_future(
                                reader.readline(), loop=self._loop)
                        try:
                            ty, value = self._process_response(response)
                            if ty == 'S':
                                future.set_result(value)
                                break
                        except CommandException as e:
                            future.set_exception(e)
                            break
            logger.debug("IO loop exited")
        except asyncio.CancelledError:
            logger.debug("IO loop cancelled")
            writer.close()
            queue_future.cancel()
            net_future.cancel()
            raise
        except:
            logger.exception("Unhandled exception in IO loop")
            raise

    @asyncio.coroutine
    def _send_cmd(self, cmd):
        future = asyncio.Future(loop=self._loop)
        yield from self._outbound.put((cmd, future))
        r = yield from future
        return r

    def _get_cached_zone_variable(self, zone_id, variable):
        if zone_id not in self._watched_zones:
            raise UncachedVariable

        try:
            s = self._zone_state[zone_id][variable]
            logger.debug("Retrieved %s.%s from cache",
                         zone_id.device_str(), variable)
            return s
        except KeyError:
            raise UncachedVariable

    @asyncio.coroutine
    def connect(self):
        logger.info("Connecting to %s:%s", self._host, self._port)
        reader, writer = yield from asyncio.open_connection(
                self._host, self._port, loop=self._loop)
        self._ioloop_future = asyncio.ensure_future(
                self._ioloop(reader, writer), loop=self._loop)
        logger.info("Connected")

    @asyncio.coroutine
    def close(self):
        logger.info("Closing connection to %s:%s", self._host, self._port)
        self._ioloop_future.cancel()
        try:
            yield from self._ioloop_future
        except asyncio.CancelledError:
            pass

    @asyncio.coroutine
    def set_zone_variable(self, zone_id, variable, value):
        return self._send_cmd("SET %s.%s=\"%s\"" % (
            zone_id.device_str(), variable, value))

    @asyncio.coroutine
    def get_zone_variable(self, zone_id, variable):
        try:
            return self._get_cached_zone_variable(zone_id, variable)
        except UncachedVariable:
            return (yield from self._send_cmd("GET %s.%s" % (
                zone_id.device_str(), variable)))

    @asyncio.coroutine
    def watch_zone(self, zone_id):
        r = yield from self._send_cmd(
                "WATCH %s ON" % (zone_id.device_str(), ))
        self._watched_zones.add(zone_id)
        return r

    @asyncio.coroutine
    def unwatch_zone(self, zone_id):
        self._watched_zones.remove(zone_id)
        return (yield from
                self._send_cmd("WATCH %s OFF" % (zone_id.device_str(), )))

    @asyncio.coroutine
    def send_zone_event(self, zone_id, event_name, *args):
        cmd = "EVENT %s!%s %s" % (
                zone_id.device_str(), event_name,
                " ".join(str(x) for x in args))
        return (yield from self._send_cmd(cmd))
