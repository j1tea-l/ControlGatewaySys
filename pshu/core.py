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

    def resolve(self, address: str) -> Optional[RouteEntry]:
        for prefix in sorted(self.routing_table.keys(), key=len, reverse=True):
            if address.startswith(prefix):
                return self.routing_table[prefix]
        return None

    async def route(self, address: str, args: list, timestamp: float) -> None:
        entry = self.resolve(address)
        if not entry:
            raise LookupError(address)
        await entry.driver.send_command(address, args)


class OSCGatewayProtocol(asyncio.DatagramProtocol):
    def __init__(self, router: OSCRouter, ntp_clock: Optional[NTPClock] = None, ntp_buffer_sec: float = 0.005):
        self.router = router
        self.ntp_clock = ntp_clock
        self.ntp_buffer_sec = ntp_buffer_sec
        self.time_tolerance = 0.001
        self.background_tasks: Set[asyncio.Task] = set()

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        task = asyncio.create_task(self.process_packet(data, addr))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def process_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            if data.startswith(b"#bundle"):
                await self.handle_bundle(OscBundle(data))
            elif data.startswith(b"/"):
                msg = OscMessage(data)
                await self.router.route(msg.address, msg.params, self._now())
        except Exception as exc:
            logger.error("Packet error from %s: %s", addr, exc)

    async def handle_bundle(self, bundle: OscBundle) -> None:
        now = self._now()
        execute_at = bundle.timestamp + self.ntp_buffer_sec
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
