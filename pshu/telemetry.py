from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

logger = logging.getLogger("PSHU_Telemetry")


@dataclass
class TelemetryForwardTarget:
    name: str
    host: str
    port: int


class TelemetryBridge(asyncio.DatagramProtocol):
    """Receives OSC-over-UDP telemetry and forwards the original OSC datagram to controllers."""

    def __init__(self, targets: list[TelemetryForwardTarget]):
        self.targets = targets

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        summary = self._parse_summary(data)
        if summary is None:
            logger.error("TELEMETRY DROP invalid_osc from=%s:%s bytes=%s", addr[0], addr[1], len(data))
            return

        logger.info(
            "TELEMETRY RX kind=%s address=%s from=%s:%s bytes=%s ts=%.6f",
            summary["kind"],
            summary["address"],
            addr[0],
            addr[1],
            len(data),
            time.time(),
        )
        for target in self.targets:
            self._send_to_target(target, data)

    def _parse_summary(self, data: bytes) -> dict | None:
        try:
            if data.startswith(b"#bundle"):
                bundle = OscBundle(data)
                first_address = "bundle"
                for item in bundle:
                    if isinstance(item, OscMessage):
                        first_address = item.address
                        break
                return {"kind": "bundle", "address": first_address}
            if data.startswith(b"/"):
                msg = OscMessage(data)
                return {"kind": "message", "address": msg.address}
        except Exception:
            return None
        return None

    def _send_to_target(self, target: TelemetryForwardTarget, payload: bytes) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (target.host, target.port))
            logger.info("TELEMETRY FWD target=%s host=%s port=%s bytes=%s", target.name, target.host, target.port, len(payload))
        except Exception as exc:
            logger.error("TELEMETRY FWD FAIL target=%s host=%s port=%s err=%s", target.name, target.host, target.port, exc)


async def start_telemetry_bridge(listen_ip: str, listen_port: int, targets: list[TelemetryForwardTarget]):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: TelemetryBridge(targets),
        local_addr=(listen_ip, listen_port),
    )
    logger.info("TELEMETRY BRIDGE started ip=%s port=%s targets=%s", listen_ip, listen_port, [t.name for t in targets])
    return transport
