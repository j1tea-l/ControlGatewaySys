from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass
from typing import Optional

NTP_EPOCH_OFFSET = 2208988800  # 1900 -> 1970


@dataclass
class NTPState:
    server: str
    port: int = 123
    alpha: float = 0.2  # smoothing factor for clock offset
    poll_interval_sec: float = 30.0
    timeout_sec: float = 1.0


class NTPClock:
    def __init__(self, state: NTPState):
        self.state = state
        self.offset_sec: float = 0.0
        self.last_sync_ts: Optional[float] = None
        self.sync_failures: int = 0

    def now(self) -> float:
        return time.time() + self.offset_sec

    async def sync_once(self) -> None:
        loop = asyncio.get_running_loop()
        offset = await asyncio.wait_for(loop.run_in_executor(None, self._query_offset), timeout=self.state.timeout_sec)
        self.offset_sec = (1.0 - self.state.alpha) * self.offset_sec + self.state.alpha * offset
        self.last_sync_ts = time.time()

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.sync_once()
            except Exception:
                self.sync_failures += 1
            await asyncio.sleep(self.state.poll_interval_sec)

    def _query_offset(self) -> float:
        packet = b"\x1b" + 47 * b"\0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(self.state.timeout_sec)
            t0 = time.time()
            s.sendto(packet, (self.state.server, self.state.port))
            data, _ = s.recvfrom(48)
            t3 = time.time()

        if len(data) < 48:
            raise RuntimeError("Invalid NTP response")

        # Transmit timestamp from server (seconds since 1900)
        sec, frac = struct.unpack("!II", data[40:48])
        t_server = sec - NTP_EPOCH_OFFSET + frac / 2**32

        # Simplified NTP offset estimate
        t1 = (t0 + t3) / 2.0
        return t_server - t1
