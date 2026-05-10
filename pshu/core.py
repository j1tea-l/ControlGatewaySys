from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from pshu.ntp_sync import NTPClock

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

from pshu.drivers import BaseDriver

logger = logging.getLogger("PSHU_Core")


@dataclass(frozen=True)
class RouteEntry:
    prefix: str
    driver: BaseDriver
    route_type: str


class OSCRouter:
    def __init__(self, routing_table: Dict[str, RouteEntry]):
        self.routing_table = routing_table
        self._sorted_prefixes = sorted(self.routing_table.keys(), key=len, reverse=True)
        logger.info("ROUTE TABLE size=%s prefixes=%s", len(self._sorted_prefixes), self._sorted_prefixes)

    def resolve(self, address: str) -> Optional[RouteEntry]:
        normalized = self._normalize_address(address)
        for prefix in self._sorted_prefixes:
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return self.routing_table[prefix]
        return None

    async def route(self, address: str, args: list, timestamp: float) -> None:
        entry = self.resolve(address)
        if not entry:
            logger.warning("ROUTE MISS address=%s args=%s ts=%.6f", address, args, timestamp)
            raise LookupError(address)
        logger.info("ROUTE HIT prefix=%s type=%s address=%s args=%s ts=%.6f", entry.prefix, entry.route_type, address, args, timestamp)
        await entry.driver.send_command(address, args)

    @staticmethod
    def _normalize_address(address: str) -> str:
        p = address.strip()
        while "//" in p:
            p = p.replace("//", "/")
        if len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        return p


class OSCGatewayProtocol(asyncio.DatagramProtocol):
    def __init__(self, router: OSCRouter, ntp_clock: Optional[NTPClock] = None, ntp_buffer_sec: float = 0.005):
        self.router = router
        self.ntp_clock = ntp_clock
        self.ntp_buffer_sec = ntp_buffer_sec
        self.time_tolerance = 0.001
        self.background_tasks: Set[asyncio.Task] = set()

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        logger.info("RX UDP from=%s:%s bytes=%s", addr[0], addr[1], len(data))
        task = asyncio.create_task(self.process_packet(data, addr))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def process_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            if data.startswith(b"#bundle"):
                await self.handle_bundle(OscBundle(data))
            elif data.startswith(b"/"):
                msg = OscMessage(data)
                logger.info("OSC MESSAGE address=%s args=%s", msg.address, msg.params)
                await self.router.route(msg.address, msg.params, self._now())
        except Exception as exc:
            logger.error("Packet error from %s: %s", addr, exc)

    async def handle_bundle(self, bundle: OscBundle) -> None:
        now = self._now()
        execute_at = bundle.timestamp + self.ntp_buffer_sec
        logger.info("BUNDLE ts=%.6f execute_at=%.6f now=%.6f delta=%.6f", bundle.timestamp, execute_at, now, execute_at-now)
        if execute_at <= now + self.time_tolerance:
            for item in bundle:
                if isinstance(item, OscMessage):
                    await self.router.route(item.address, item.params, execute_at)
                elif isinstance(item, OscBundle):
                    await self.handle_bundle(item)
        else:
            await asyncio.sleep(max(0.0, execute_at - now))
            await self.handle_bundle(bundle)

    def _now(self) -> float:
        return self.ntp_clock.now() if self.ntp_clock else time.time()
