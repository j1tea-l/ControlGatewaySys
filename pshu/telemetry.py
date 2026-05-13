from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

if TYPE_CHECKING:
    from pshu.heartbeat import HeartbeatManager

logger = logging.getLogger("PSHU_Telemetry")


@dataclass
class TelemetryForwardTarget:
    name: str
    host: str
    port: int


class TelemetryBridge(asyncio.DatagramProtocol):
    def __init__(self, targets: list[TelemetryForwardTarget], heartbeat: Optional['HeartbeatManager'] = None):
        self.targets = targets
        self.heartbeat = heartbeat

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        summary = _parse_summary(data)
        if summary is None:
            logger.error("TELEMETRY DROP invalid_osc from=%s:%s bytes=%s", addr[0], addr[1], len(data))
            return
            
        logger.info("TELEMETRY RX kind=%s address=%s from=%s:%s bytes=%s ts=%.6f", 
                    summary["kind"], summary["address"], addr[0], addr[1], len(data), time.time())
        
        # Интеграция с Heartbeat: отмечаем устройство как активное при получении телеметрии
        if self.heartbeat:
            _mark_device_seen(self.heartbeat, summary["address"])
            
        for target in self.targets:
            _send_udp(target, data)


class TelemetryTCPServer:
    def __init__(self, targets: list[TelemetryForwardTarget], heartbeat: Optional['HeartbeatManager'] = None):
        self.targets = targets
        self.heartbeat = heartbeat

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            header = await reader.readexactly(4)
            size = struct.unpack("!I", header)[0]
            data = await reader.readexactly(size)
            summary = _parse_summary(data)
            
            if summary is None:
                logger.error("TELEMETRY DROP invalid_osc_tcp from=%s bytes=%s", peer, len(data))
                return
                
            logger.info("TELEMETRY RX kind=%s address=%s from=%s bytes=%s ts=%.6f", 
                        summary["kind"], summary["address"], peer, len(data), time.time())
            
            # Интеграция с Heartbeat: отмечаем устройство как активное при получении телеметрии
            if self.heartbeat:
                _mark_device_seen(self.heartbeat, summary["address"])
                
            for target in self.targets:
                _send_udp(target, data)
        except Exception as exc:
            logger.error("TELEMETRY TCP handler error from=%s err=%s", peer, exc)
        finally:
            writer.close()
            await writer.wait_closed()


def _mark_device_seen(heartbeat: 'HeartbeatManager', address: str) -> None:
    """Извлекает имя устройства из OSC адреса (например, /dsp1/...) и сбрасывает таймаут."""
    parts = address.split('/')
    if len(parts) > 1 and parts[1]:
        device_name = parts[1]
        heartbeat.mark_seen(device_name)


def _parse_summary(data: bytes) -> dict | None:
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


def _send_udp(target: TelemetryForwardTarget, payload: bytes) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (target.host, target.port))
        logger.info("TELEMETRY FWD target=%s host=%s port=%s bytes=%s", 
                    target.name, target.host, target.port, len(payload))
    except Exception as exc:
        logger.error("TELEMETRY FWD FAIL target=%s host=%s port=%s err=%s", 
                     target.name, target.host, target.port, exc)


async def start_telemetry_bridge(
    listen_ip: str, 
    listen_port: int, 
    targets: list[TelemetryForwardTarget], 
    transport: str = "udp",
    heartbeat: Optional['HeartbeatManager'] = None
):
    loop = asyncio.get_running_loop()
    if transport == "tcp":
        server = await asyncio.start_server(
            TelemetryTCPServer(targets, heartbeat).handle, 
            listen_ip, 
            listen_port
        )
        logger.info("TELEMETRY BRIDGE started transport=tcp ip=%s port=%s targets=%s", 
                    listen_ip, listen_port, [t.name for t in targets])
        return server
        
    udp_transport, _ = await loop.create_datagram_endpoint(
        lambda: TelemetryBridge(targets, heartbeat), 
        local_addr=(listen_ip, listen_port)
    )
    logger.info("TELEMETRY BRIDGE started transport=udp ip=%s port=%s targets=%s", 
                listen_ip, listen_port, [t.name for t in targets])
    return udp_transport
