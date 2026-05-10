import argparse
import asyncio
import time
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder


def send_message(client, address, value):
    client.send_message(address, [value, time.time()])


def send_bundle(client, address, value, delay_sec):
    mb = OscMessageBuilder(address=address)
    mb.add_arg(value)
    msg = mb.build()
    bb = OscBundleBuilder(time.time() + delay_sec)
    bb.add_content(msg)
    client.send(bb.build())


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--mode", choices=["message", "bundle"], default="message")
    p.add_argument("--address", default="/device/amp/gain")
    args = p.parse_args()
    client = SimpleUDPClient(args.host, args.port)
    for i in range(args.count):
        if args.mode == "message":
            send_message(client, args.address, i)
        else:
            send_bundle(client, args.address, i, 0.1)
        await asyncio.sleep(0.01)


if __name__ == "__main__":
    asyncio.run(main())
