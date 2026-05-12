import argparse
import asyncio
import random
import struct
import time

from pythonosc.osc_message_builder import OscMessageBuilder


async def send_one(host: str, port: int, payload: bytes):
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(struct.pack('!I', len(payload)) + payload)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    p = argparse.ArgumentParser(description='Generate OSC-over-TCP framed telemetry')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=9100)
    p.add_argument('--device', default='ppp1')
    p.add_argument('--metric', default='voltage_v')
    p.add_argument('--count', type=int, default=20)
    p.add_argument('--interval', type=float, default=0.1)
    p.add_argument('--base', type=float, default=40.0)
    p.add_argument('--jitter', type=float, default=3.0)
    args = p.parse_args()
    address = f"/{args.device}/telemetry/{args.metric}"

    for i in range(args.count):
        value = round(args.base + random.uniform(-args.jitter, args.jitter), 3)
        mb = OscMessageBuilder(address=address)
        mb.add_arg(value)
        mb.add_arg(i)
        mb.add_arg(time.time())
        payload = mb.build().dgram
        await send_one(args.host, args.port, payload)
        print({'address': address, 'seq': i})
        await asyncio.sleep(args.interval)


if __name__ == '__main__':
    asyncio.run(main())
