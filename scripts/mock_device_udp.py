import argparse
import json
import socket
import time

p = argparse.ArgumentParser()
p.add_argument('--host', default='0.0.0.0')
p.add_argument('--port', type=int, default=9000)
p.add_argument('--out', default='/tmp/device_messages.jsonl')
args = p.parse_args()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((args.host, args.port))
print(f"mock_device_udp listening on {args.host}:{args.port}")

with open(args.out, 'a', encoding='utf-8') as f:
    while True:
        data, addr = sock.recvfrom(65535)
        rec = {"ts": time.time(), "from": addr, "payload": data.decode(errors='ignore')}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        print(rec)
