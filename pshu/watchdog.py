import time
import socket
import threading
import logging

logger = logging.getLogger("PSHU_Watchdog")

HEARTBEAT_TIMEOUT = 3.0
CHECK_INTERVAL = 0.5


class DeviceState:
    def __init__(self, name, host, port):
        self.name = name
        self.host = host
        self.port = port

        self.last_seen = time.time()
        self.online = True

        self.reconnect_attempts = 0
        self.sock = None

    def mark_seen(self):
        self.last_seen = time.time()

    def is_alive(self):
        return (time.time() - self.last_seen) < HEARTBEAT_TIMEOUT


class Watchdog:
    def __init__(self):
        self.devices = {}

    def register(self, device):
        self.devices[device.name] = device

    def run(self):
        while True:
            for dev in self.devices.values():

                if not dev.is_alive():

                    if dev.online:
                        logger.warning(
                            f"LINK LOST device={dev.name}"
                        )

                    dev.online = False

                    self.reconnect(dev)

            time.sleep(CHECK_INTERVAL)

    def reconnect(self, dev):

        try:
            if dev.sock:
                dev.sock.close()

            sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            sock.settimeout(1.0)

            dev.sock = sock

            dev.reconnect_attempts += 1

            logger.info(
                f"RECONNECT OK "
                f"device={dev.name} "
                f"attempt={dev.reconnect_attempts}"
            )

            dev.online = True

        except Exception as ex:

            logger.error(
                f"RECONNECT FAIL "
                f"device={dev.name} "
                f"error={ex}"
            )
