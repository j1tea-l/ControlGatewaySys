import argparse
import asyncio
import random
import time

from pythonosc.udp_client import SimpleUDPClient


async def main() -> None:
    p = argparse.ArgumentParser(description='Generate OSC-over-UDP telemetry traffic for PSHU tests')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=9100)
    p.add_argument('--device', default='dsp1')
    p.add_argument('--metric', default='temp_c')
    p.add_argument('--count', type=int, default=20)
    p.add_argument('--interval', type=float, default=0.1)
    p.add_argument('--base', type=float, default=40.0)
    p.add_argument('--jitter', type=float, default=3.0)
    args = p.parse_args()

    address = f"/{args.device}/telemetry/{args.metric}"
    client = SimpleUDPClient(args.host, args.port)

    for i in range(args.count):
        value = round(args.base + random.uniform(-args.jitter, args.jitter), 3)
        payload = [value, i, time.time()]
        client.send_message(address, payload)
        print({'address': address, 'args': payload})
        await asyncio.sleep(args.interval)


if __name__ == '__main__':
    asyncio.run(main())
