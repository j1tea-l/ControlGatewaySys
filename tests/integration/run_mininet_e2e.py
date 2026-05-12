import json
import re
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSBridge


def parse_pshu_log(text: str) -> dict:
    patterns = {
        'route_hit': r'ROUTE HIT',
        'route_miss': r'ROUTE MISS',
        'rx_udp': r'RX UDP',
        'tx_ok': r'TX OK',
        'tx_fail': r'TX FAIL',
        'telemetry_rx': r'TELEMETRY RX',
        'telemetry_fwd': r'TELEMETRY FWD',
    }
    return {k: len(re.findall(v, text)) for k, v in patterns.items()}


def parse_route_miss_addresses(text: str) -> list[str]:
    return re.findall(r"ROUTE MISS address=([^ ]+)", text)


def _to_int_safe(v: str) -> int:
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else 0


def _count_lines(path: str) -> str:
    return (
        "python3 - <<'EOF'\n"
        "from pathlib import Path\n"
        f"p=Path('{path}')\n"
        "print(sum(1 for _ in p.open()) if p.exists() else 0)\n"
        "EOF"
    )


def _extract_first_int(text: str) -> int:
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def _count_tcpdump_packets(text: str) -> int:
    # tcpdump packet rows start with epoch timestamp when -tt is used
    return sum(1 for line in text.splitlines() if re.match(r"^\d+\.\d+\s", line))

def run():
    repo = Path(__file__).resolve().parents[2]
    net = Mininet(controller=None, switch=OVSBridge)
    s1 = net.addSwitch('s1')
    controller = net.addHost('controller')
    pshu = net.addHost('pshu')
    dsp1 = net.addHost('dsp1')
    ppp1 = net.addHost('ppp1')

    for h in (controller, pshu, dsp1, ppp1):
        net.addLink(h, s1)

    net.start()
    ping_drop = net.pingAll()

    # Clear stale artifacts from previous runs to keep counters deterministic.
    pshu.cmd("rm -f /tmp/pshu.log /tmp/pshu.stdout /tmp/pshu.log.*")
    dsp1.cmd("rm -f /tmp/dsp.log /tmp/dsp_messages.jsonl")
    ppp1.cmd("rm -f /tmp/ppp.log /tmp/ppp_messages.jsonl /tmp/ppp_profile.json")
    controller.cmd("rm -f /tmp/telemetry_sink.log /tmp/controller_telemetry.jsonl /tmp/controller.tcpdump.log")
    pshu.cmd("rm -f /tmp/pshu.tcpdump.log")

    dsp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9000 --out /tmp/dsp_messages.jsonl > /tmp/dsp.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp.log 2>&1 &')
    controller.cmd(f'cd {repo} && python3 tests/integration/telemetry_sink.py --port 9200 --out /tmp/controller_telemetry.jsonl > /tmp/telemetry_sink.log 2>&1 &')

    # Real network capture (not app-level counters): sniff OSC/telemetry UDP traffic in namespaces.
    pshu.cmd("timeout 30 tcpdump -n -tt -l -i any udp and '(port 8000 or port 9100 or port 9200)' > /tmp/pshu.tcpdump.log 2>&1 &")
    controller.cmd("timeout 30 tcpdump -n -tt -l -i any udp and '(port 8000 or port 9100 or port 9200)' > /tmp/controller.tcpdump.log 2>&1 &")

    cfg = {
        "listen_ip": "0.0.0.0",
        "listen_port": 8000,
        "log_level": "INFO",
        "log_file": "/tmp/pshu.log",
        "ntp": {"enabled": False},
        "routes": [
            {"prefix": "/dsp1", "route_type": "local", "driver": {"name": "dsp1", "host": "10.0.0.3", "port": 9000, "protocol": "udp", "output_mode": "mapped_json", "mapping_rules": {"/dsp1/cmd": {"endpoint": "amp.apply", "fields": {"arg0": "gain"}}}, "retry": {"retries": 1}}},
            {"prefix": "/ppp1", "route_type": "ppp", "driver": {"name": "ppp1", "host": "10.0.0.4", "port": 9001, "protocol": "tcp", "output_mode": "osc_native", "ppp_profile": {"signing_key": "test-key", "rules": {"serial_map": {"/cmd": "RS485:WRITE"}, "telemetry": {"target": "/telemetry/voltage_v", "period_ms": 100}}}, "retry": {"retries": 1}}},
        ],
        "telemetry": {
            "enabled": True,
            "listen_ip": "0.0.0.0",
            "transport": "tcp",
            "listen_port": 9100,
            "targets": [
                {"name": "controller", "host": "10.0.0.1", "port": 9200}
            ]
        }
    }
    (repo / 'config.e2e.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    pshu.cmd(f'cd {repo} && cp config.e2e.json config.example.json && python3 main.py > /tmp/pshu.stdout 2>&1 &')
    time.sleep(1.5)

    pshu_proc = pshu.cmd("pgrep -af 'python3 main.py' || true")
    if not pshu_proc.strip():
        startup_log = pshu.cmd('cat /tmp/pshu.stdout 2>/dev/null || true')
        net.stop()
        raise SystemExit(f"PSHU failed to start in namespace. Log:\n{startup_log}")

    controller.cmd(
        f'cd {repo} && python3 scripts/osc_loadgen.py '
        '--host 10.0.0.2 --port 8000 --count 20 --mode message --address /dsp1/cmd'
    )
    controller.cmd("python3 - <<'EOF'\nfrom pythonosc.udp_client import SimpleUDPClient\nc=SimpleUDPClient('10.0.0.2',8000)\nfor i in range(10):\n c.send_message('/ppp1/cmd',[i])\nEOF")
    dsp1.cmd(f'cd {repo} && python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device dsp1 --count 25 --interval 0.03 > /tmp/dsp_telem.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/telemetry_gen_tcp.py --host 10.0.0.2 --port 9100 --device ppp1 --metric voltage_v --count 25 --interval 0.03 > /tmp/ppp_telem.log 2>&1 &')
    time.sleep(2.0)

    pshu_log = pshu.cmd('cat /tmp/pshu.log 2>/dev/null || cat /tmp/pshu.stdout 2>/dev/null || true')
    dsp_count_raw = dsp1.cmd(_count_lines('/tmp/dsp_messages.jsonl')).strip()
    ppp_count_raw = ppp1.cmd(_count_lines('/tmp/ppp_messages.jsonl')).strip()
    ppp_profile_pushed_raw = ppp1.cmd("python3 - <<'EOF'\nfrom pathlib import Path\np=Path('/tmp/ppp_profile.json')\nprint(1 if p.exists() and p.stat().st_size > 0 else 0)\nEOF").strip()

    dsp_count = _to_int_safe(dsp_count_raw)
    ppp_count = _to_int_safe(ppp_count_raw)
    telemetry_count_raw = controller.cmd(_count_lines('/tmp/controller_telemetry.jsonl')).strip()
    telemetry_count = _to_int_safe(telemetry_count_raw)
    ppp_profile_pushed = _to_int_safe(ppp_profile_pushed_raw)
    parsed = parse_pshu_log(pshu_log)
    miss_addresses = parse_route_miss_addresses(pshu_log)

    pshu_tcpdump = pshu.cmd("cat /tmp/pshu.tcpdump.log 2>/dev/null || true")
    controller_tcpdump = controller.cmd("cat /tmp/controller.tcpdump.log 2>/dev/null || true")
    pshu_udp_packets = _count_tcpdump_packets(pshu_tcpdump)
    controller_udp_packets = _count_tcpdump_packets(controller_tcpdump)

    result = {
        'ping_drop': ping_drop,
        'dsp_count': dsp_count,
        'ppp_count': ppp_count,
        'controller_telemetry_count': telemetry_count,
        'ppp_profile_pushed': ppp_profile_pushed,
        'log_counts': parsed,
        'route_miss_addresses': miss_addresses,
        'pshu_proc': pshu_proc.strip(),
        'pshu_log_tail': '\n'.join(pshu_log.splitlines()[-30:]),
        'dsp_log_tail': dsp1.cmd('tail -n 30 /tmp/dsp.log 2>/dev/null || true'),
        'ppp_log_tail': ppp1.cmd('tail -n 30 /tmp/ppp.log 2>/dev/null || true'),
        'telemetry_sink_tail': controller.cmd('tail -n 30 /tmp/telemetry_sink.log 2>/dev/null || true'),
        'network_capture': {
            'pshu_udp_packets_captured': pshu_udp_packets,
            'controller_udp_packets_captured': controller_udp_packets,
            'pshu_tcpdump_tail': '\n'.join(pshu_tcpdump.splitlines()[-40:]),
            'controller_tcpdump_tail': '\n'.join(controller_tcpdump.splitlines()[-40:]),
        },
    }

    (repo / 'mininet_e2e_report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    ok = all([
        ping_drop == 0.0,
        dsp_count > 0,
        ppp_count > 0,
        parsed['route_hit'] > 0,
        parsed['tx_ok'] > 0,
        telemetry_count > 0,
        ppp_profile_pushed > 0,
        parsed['telemetry_rx'] > 0,
        parsed['telemetry_fwd'] > 0,
        pshu_udp_packets > 0,
        controller_udp_packets > 0,
    ])

    pshu.cmd('pkill -f "python3 main.py" || true')
    dsp1.cmd('pkill -f "mock_device_udp.py" || true')
    ppp1.cmd('pkill -f "mock_ppp_tcp_device.py" || true')
    controller.cmd('pkill -f "telemetry_sink.py" || true')
    dsp1.cmd('pkill -f "telemetry_gen.py" || true')
    ppp1.cmd('pkill -f "telemetry_gen.py" || true')
    ppp1.cmd('pkill -f "telemetry_gen_tcp.py" || true')
    pshu.cmd('pkill -f "tcpdump -n -tt -l -i any udp" || true')
    controller.cmd('pkill -f "tcpdump -n -tt -l -i any udp" || true')
    net.stop()

    if not ok:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit('E2E assertions failed: see mininet_e2e_report.json for diagnostics')

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    run()
