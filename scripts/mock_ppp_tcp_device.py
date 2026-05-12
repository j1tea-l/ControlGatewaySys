import argparse
import asyncio
import json
import struct
import time
from pathlib import Path

from pythonosc.osc_message import OscMessage

p = argparse.ArgumentParser()
p.add_argument('--host', default='0.0.0.0')
p.add_argument('--port', type=int, default=9001)
p.add_argument('--out', default='/tmp/ppp_messages.jsonl')
p.add_argument('--profile-out', default='/tmp/ppp_profile.json')
args = p.parse_args()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    data = await reader.read(65535)
    if data:
        # profile is line-delimited json
        if data.startswith(b'{') and b'ppp_driver_profile' in data:
            rec = json.loads(data.decode('utf-8').strip())
            Path(args.profile_out).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding='utf-8')
            print({'profile': rec})
        elif len(data) >= 4:
            size = struct.unpack('!I', data[:4])[0]
            payload = data[4:4+size]
            msg = OscMessage(payload)
            rec = {'ts': time.time(), 'address': msg.address, 'args': list(msg.params)}
            with open(args.out, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            print(rec)
    writer.close()
    await writer.wait_closed()


async def main():
    server = await asyncio.start_server(handle, args.host, args.port)
    print(f'mock_ppp_tcp_device listening on {args.host}:{args.port}')
    async with server:
        await server.serve_forever()


asyncio.run(main())
