import argparse
import json
import socket
import time

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage


p = argparse.ArgumentParser()
p.add_argument('--host', default='0.0.0.0')
p.add_argument('--port', type=int, default=9200)
p.add_argument('--out', default='/tmp/controller_telemetry.jsonl')
args = p.parse_args()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((args.host, args.port))
print(f'telemetry_sink listening on {args.host}:{args.port}')


def parse_osc(data: bytes) -> dict:
    if data.startswith(b'#bundle'):
        bundle = OscBundle(data)
        first = 'bundle'
        for item in bundle:
            if isinstance(item, OscMessage):
                first = item.address
                break
        return {'kind': 'bundle', 'address': first}
    msg = OscMessage(data)
    return {'kind': 'message', 'address': msg.address, 'args': list(msg.params)}


with open(args.out, 'a', encoding='utf-8') as f:
    while True:
        data, addr = sock.recvfrom(65535)
        rec = {'recv_ts': time.time(), 'from': addr, 'bytes': len(data), 'osc': parse_osc(data)}
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        f.flush()
        print(rec)
