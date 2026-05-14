import argparse
import json
import socket
import time
import struct

p = argparse.ArgumentParser()
p.add_argument('--host', default='0.0.0.0')
p.add_argument('--port', type=int, default=9000)
p.add_argument('--out', default='/tmp/device_messages.jsonl')
# Добавлены аргументы для синхронизации единого контекста времени
p.add_argument('--ntp-server', default=None)
p.add_argument('--ntp-port', type=int, default=12345)
args = p.parse_args()

offset_sec = 0.0
if args.ntp_server:
    try:
        packet = b"\x1b" + 47 * b"\0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            t0 = time.time()
            s.sendto(packet, (args.ntp_server, args.ntp_port))
            data, _ = s.recvfrom(48)
            t3 = time.time()
        sec, frac = struct.unpack("!II", data[40:48])
        NTP_EPOCH_OFFSET = 2208988800
        t_server = sec - NTP_EPOCH_OFFSET + frac / 2**32
        offset_sec = t_server - ((t0 + t3) / 2.0)
        print(f"Mock device synced to NTP. Offset: {offset_sec:.6f}s")
    except Exception as e:
        print(f"NTP Sync failed: {e}")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((args.host, args.port))
print(f"mock_device_udp listening on {args.host}:{args.port}")

with open(args.out, 'a', encoding='utf-8') as f:
    while True:
        data, addr = sock.recvfrom(65535)
        # Получаем единое стендовое время
        synced_ts = time.time() + offset_sec
        rec = {"ts": synced_ts, "from": addr, "payload": data.decode(errors='ignore')}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
