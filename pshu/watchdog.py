import time
import socket
import threading
import logging
from collections import deque

logger = logging.getLogger("PSHU_Watchdog")

HEARTBEAT_TIMEOUT = 3.0
CHECK_INTERVAL = 0.5
MAX_BACKOFF = 30


class DeviceState:

    def __init__(self, name, host, port):

        self.name = name
        self.host = host
        self.port = port

        self.last_seen = time.time()

        self.online = True

        self.sock = None

        self.reconnect_attempts = 0

        self.pending_packets = deque(maxlen=1024)

    def mark_seen(self):

        self.last_seen = time.time()

        if not self.online:

            logger.info(
                f"DEVICE ONLINE device={self.name}"
            )

        self.online = True

        self.reconnect_attempts = 0

    def is_alive(self):

        delta = time.time() - self.last_seen

        return delta < HEARTBEAT_TIMEOUT


class Watchdog:

    def __init__(self):

        self.devices = {}

        self.running = False

    def register(self, name, host, port):

        dev = DeviceState(name, host, port)

        self.devices[name] = dev

        logger.info(
            f"REGISTER DEVICE "
            f"name={name} "
            f"host={host} "
            f"port={port}"
        )

        return dev

    def mark_seen(self, device_name):

        dev = self.devices.get(device_name)

        if dev:

            dev.mark_seen()

    def enqueue_packet(self, device_name, packet):

        dev = self.devices.get(device_name)

        if dev:

            dev.pending_packets.append(packet)

    def flush_queue(self, dev):

        while dev.pending_packets:

            packet = dev.pending_packets.popleft()

            try:

                dev.sock.sendto(
                    packet,
                    (dev.host, dev.port)
                )

            except Exception as ex:

                logger.error(
                    f"QUEUE FLUSH FAIL "
                    f"device={dev.name} "
                    f"error={ex}"
                )

                break

    def reconnect(self, dev):

        try:

            logger.warning(
                f"RECONNECT START "
                f"device={dev.name}"
            )

            if dev.sock:

                try:
                    dev.sock.close()
                except:
                    pass

            sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1
            )

            sock.settimeout(1.0)

            dev.sock = sock

            self.flush_queue(dev)

            dev.online = True

            dev.reconnect_attempts += 1

            logger.info(
                f"RECONNECT OK "
                f"device={dev.name} "
                f"attempt={dev.reconnect_attempts}"
            )

        except Exception as ex:

            logger.error(
                f"RECONNECT FAIL "
                f"device={dev.name} "
                f"error={ex}"
            )

    def watchdog_loop(self):

        logger.info("WATCHDOG STARTED")

        while self.running:

            for dev in self.devices.values():

                if not dev.is_alive():

                    if dev.online:

                        logger.warning(
                            f"LINK LOST "
                            f"device={dev.name}"
                        )

                    dev.online = False

                    self.reconnect(dev)

                    backoff = min(
                        MAX_BACKOFF,
                        2 ** max(1, dev.reconnect_attempts)
                    )

                    time.sleep(backoff)

            time.sleep(CHECK_INTERVAL)

    def start(self):

        self.running = True

        thread = threading.Thread(
            target=self.watchdog_loop,
            daemon=True
        )

        thread.start()
