import json
import re
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink

def _count_lines(path: str) -> str:
    return f"cat {path} 2>/dev/null | wc -l"

def _to_int_safe(v: str) -> int:
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else 0

def run():
    repo = Path(__file__).resolve().parents[2]
    
    print("[1/6] Инициализация Mininet и топологии 'Звезда' с TCLink...")
    net = Mininet(controller=None, switch=OVSBridge, link=TCLink)
    s1 = net.addSwitch('s1')
    
    client = net.addHost('client', ip='10.0.0.1/24')
    pshu = net.addHost('pshu', ip='10.0.0.2/24')
    dsp1 = net.addHost('dsp1', ip='10.0.0.3/24')
    ppp1 = net.addHost('ppp1', ip='10.0.0.4/24')

    net.addLink(client, s1, delay='5ms', jitter='2ms')
    net.addLink(pshu, s1, delay='2ms', jitter='1ms')
    net.addLink(dsp1, s1, delay='10ms', jitter='3ms')
    net.addLink(ppp1, s1, delay='15ms', jitter='5ms')

    net.start()
    net.pingAll()

    pshu.cmd("rm -f /tmp/pshu.log /tmp/pshu.stdout")
    dsp1.cmd("rm -f /tmp/dsp.log /tmp/dsp_messages.jsonl")
    ppp1.cmd("rm -f /tmp/ppp.log /tmp/ppp_messages.jsonl /tmp/ppp_profile.json /tmp/ppp_recovery.log")
    client.cmd("rm -f /tmp/telemetry_sink.log /tmp/client_telemetry.jsonl /tmp/client_capture.pcap /tmp/ntp_server.log")

    print("[2/6] Запуск эмуляторов устройств, телеметрии и ЛОКАЛЬНОГО NTP СЕРВЕРА...")
    dsp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9000 --out /tmp/dsp_messages.jsonl > /tmp/dsp.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp.log 2>&1 &')
    client.cmd(f'cd {repo} && python3 tests/integration/telemetry_sink.py --port 9200 --out /tmp/client_telemetry.jsonl > /tmp/telemetry_sink.log 2>&1 &')
    client.cmd("tcpdump -i any -n -tt -w /tmp/client_capture.pcap udp port 8000 or udp port 9100 or udp port 9200 > /dev/null 2>&1 &")

    # Встроенный фейковый NTP-сервер на хосте client (10.0.0.1)
    ntp_server_script = """
import socket
import struct
import time
NTP_EPOCH_OFFSET = 2208988800
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', 123))
while True:
    try:
        data, addr = sock.recvfrom(1024)
        if len(data) >= 48:
            now = time.time()
            ntp_time = now + NTP_EPOCH_OFFSET
            sec = int(ntp_time)
            frac = int((ntp_time - sec) * (2**32))
            resp = bytearray(48)
            resp[0] = 0x24  # Leap indicator 0, Version 4, Mode 4 (Server)
            struct.pack_into("!II", resp, 40, sec, frac)
            sock.sendto(resp, addr)
    except Exception:
        pass
"""
    client.cmd(f"python3 -c \"{ntp_server_script.strip()}\" > /tmp/ntp_server.log 2>&1 &")

    print("[3/6] Запуск подсистемы шлюза управления (ПШУ)...")
    cfg = {
        "listen_ip": "0.0.0.0",
        "listen_port": 8000,
        "log_level": "DEBUG",
        "log_file": "/tmp/pshu.log",
        "ntp": {
            "enabled": True,
            "server": "10.0.0.1",
            "port": 123,
            "poll_interval_sec": 2.0,
            "timeout_sec": 1.0,
            "alpha": 0.5
        },
        "routes": [
            {"prefix": "/dsp1", "route_type": "local", "driver": {"name": "dsp1", "host": "10.0.0.3", "port": 9000, "protocol": "udp", "output_mode": "mapped_json"}},
            {"prefix": "/ppp1", "route_type": "ppp", "driver": {"name": "ppp1", "host": "10.0.0.4", "port": 9001, "protocol": "tcp", "output_mode": "osc_native", "ppp_profile": {"signing_key": "secret", "rules": {"mode": "test"}}}}
        ],
        "telemetry": {
            "enabled": True, "listen_ip": "0.0.0.0", "transport": "udp", "listen_port": 9100,
            "targets": [{"name": "client_app", "host": "10.0.0.1", "port": 9200}]
        }
    }
    (repo / 'config.e2e.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    pshu.cmd(f'cd {repo} && cp config.e2e.json config.example.json && python3 main.py > /tmp/pshu.stdout 2>&1 &')
    
    # Даем ПШУ время на запуск и синхронизацию с локальным NTP
    time.sleep(4.0)

    print("[4/6] Тест №1 и №2: Синхронизация (OSC Bundle) и Телеметрия...")
    sync_test_script = """
import time
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder

c = SimpleUDPClient('10.0.0.2', 8000)
target_time = time.time() + 1.5

msg = OscMessageBuilder(address='/dsp1/sync_test')
msg.add_arg('delayed_execution')
msg.add_arg(target_time)

bundle = OscBundleBuilder(target_time)
bundle.add_content(msg.build())
c.send(bundle.build())
"""
    client.cmd(f"python3 -c \"{sync_test_script}\" > /tmp/sync_test.log")
    time.sleep(3.0) 

    client.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 10 --mode message --address /ppp1/volume')
    dsp1.cmd(f'cd {repo} && python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device dsp1 --count 10 --interval 0.05 > /dev/null 2>&1 &')
    time.sleep(1.0)

    print("[5/6] Тест №3: Обрыв связи (Heartbeat) и автовосстановление ППП...")
    ppp1.cmd('pkill -f "mock_ppp_tcp_device.py" || true')
    time.sleep(4.0) 
    ppp1.cmd("rm -f /tmp/ppp_profile.json")

    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp_recovery.log 2>&1 &')
    time.sleep(4.0) 

    client.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 1 --mode message --address /ppp1/after_recovery')
    time.sleep(1.0)

    print("[6/6] Сбор логов и расчет метрик...")
    pshu_log = pshu.cmd('cat /tmp/pshu.log 2>/dev/null || true')
    dsp_messages = dsp1.cmd('cat /tmp/dsp_messages.jsonl 2>/dev/null || true').strip().split('\n')
    ppp_messages = ppp1.cmd('cat /tmp/ppp_messages.jsonl 2>/dev/null || true')
    
    sync_delta_ms = 0.0
    for line in dsp_messages:
        if 'sync_test' in line:
            rec = json.loads(line)
            payload = json.loads(rec['payload'])
            target_ts = payload['args'][1]
            actual_receive_ts = rec['ts']
            sync_delta_ms = (actual_receive_ts - target_ts) * 1000
            break

    dsp_count = _to_int_safe(dsp1.cmd(_count_lines('/tmp/dsp_messages.jsonl')))
    telem_count = _to_int_safe(client.cmd(_count_lines('/tmp/client_telemetry.jsonl')))

    heartbeat_dropped = 'ОБРЫВ СВЯЗИ' in pshu_log
    heartbeat_recovered = 'СВЯЗЬ ВОССТАНОВЛЕНА' in pshu_log
    profile_pushed_again = _to_int_safe(ppp1.cmd("cat /tmp/ppp_profile.json 2>/dev/null | wc -l")) > 0
    recovery_cmd_delivered = 'after_recovery' in ppp_messages
    ntp_synced = 'NTP Синхронизация успешна' in pshu_log

    print("\n" + "="*80)
    print(" ОТЧЕТ О ТЕСТИРОВАНИИ ПШУ (Mininet Advanced E2E) - RAW DATA")
    print("="*80)
    print("ПАРАМЕТРЫ СЕТИ (TCLink):")
    print("  Client <-> Switch : delay=5ms, jitter=2ms")
    print("  PSHU <-> Switch   : delay=2ms, jitter=1ms")
    print("  DSP1 <-> Switch   : delay=10ms, jitter=3ms")
    print("  PPP1 <-> Switch   : delay=15ms, jitter=5ms\n")
    
    print("ТЕСТ СИНХРОНИЗАЦИИ:")
    print(f"  NTP Синхронизация с 10.0.0.1: {ntp_synced}")
    print(f"  Транспортная задержка (сеть): {sync_delta_ms:.2f} мс\n")
    
    print("ТЕСТ АВТОВОССТАНОВЛЕНИЯ (Heartbeat):")
    print(f"  Детекция обрыва связи: {heartbeat_dropped}")
    print(f"  Авто-переподключение (TCP): {heartbeat_recovered}")
    print(f"  Повторная отправка профиля: {profile_pushed_again}")
    print(f"  Доставка команды после сбоя: {recovery_cmd_delivered}\n")

    print("СТАТИСТИКА ПАКЕТОВ:")
    print(f"  Команд доставлено на DSP: {dsp_count}")
    print(f"  Телеметрии получено клиентом: {telem_count}")
    print("-" * 80)

    print("\n=== СЫРЫЕ ЛОГИ МАРШРУТИЗАЦИИ И ЯДРА ПШУ (tail -n 20) ===")
    print(pshu.cmd('grep -E "ROUTE|TX|RX|BUNDLE|СВЯЗЬ|ОБРЫВ|NTP" /tmp/pshu.log | tail -n 20').strip())

    print("\n=== СЫРЫЕ ЛОГИ СООБЩЕНИЙ КОНЕЧНЫХ УСТРОЙСТВ ===")
    print("DSP Messages (tail -n 3):")
    print(dsp1.cmd('tail -n 3 /tmp/dsp_messages.jsonl').strip())
    print("\nPPP Messages (tail -n 3):")
    print(ppp1.cmd('tail -n 3 /tmp/ppp_messages.jsonl').strip())
    print("\nClient Telemetry Sink (tail -n 3):")
    print(client.cmd('tail -n 3 /tmp/client_telemetry.jsonl').strip())

    print("\n=== РЕАЛЬНЫЕ ЛОГИ MININET (TCPDUMP CLIENT) ===")
    print(client.cmd('tcpdump -r /tmp/client_capture.pcap -n -tt -c 15 2>/dev/null || true').strip())
    print("="*80 + "\n")

    result = {
        'network_delays': {'client_to_pshu_link': '5ms+2ms', 'pshu_to_dsp_link': '2ms+10ms'},
        'sync_system_test': {'ntp_synced': ntp_synced, 'latency_ms': round(sync_delta_ms, 2)},
        'heartbeat_test': {
            'dropped_detected': heartbeat_dropped, 
            'recovered': heartbeat_recovered,
            'profile_repushed': profile_pushed_again,
            'command_delivered': recovery_cmd_delivered
        },
        'routing_and_telemetry': {'dsp_count': dsp_count, 'telem_count': telem_count}
    }
    (repo / 'mininet_advanced_report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    pshu.cmd('pkill -f "python3 main.py" || true')
    client.cmd('pkill -f "ntp_server" || true')
    dsp1.cmd('pkill -f "mock_device_udp.py" || true')
    ppp1.cmd('pkill -f "mock_ppp_tcp_device.py" || true')
    dsp1.cmd('pkill -f "telemetry_gen.py" || true')
    client.cmd('pkill -f "telemetry_sink.py" || true')
    client.cmd('pkill -f tcpdump || true')
    net.stop()

if __name__ == '__main__':
    run()
