import json
import re
import subprocess
import sys
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSBridge


def wait_file(host, path: str, timeout: float = 10.0) -> bool:
    started = time.time()
    while time.time() - started < timeout:
        out = host.cmd(f'test -f {path} && echo ok || echo no').strip()
        if out == 'ok':
            return True
        time.sleep(0.2)
    return False


def parse_pshu_log(text: str) -> dict:
    patterns = {
        'route_hit': r'ROUTE HIT',
        'route_miss': r'ROUTE MISS',
        'rx_udp': r'RX UDP',
        'tx_ok': r'TX OK',
        'tx_fail': r'TX FAIL',
    }
    return {k: len(re.findall(v, text)) for k, v in patterns.items()}


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

    # setup endpoints
    dsp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9000 --out /tmp/dsp_messages.jsonl > /tmp/dsp.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9001 --out /tmp/ppp_messages.jsonl > /tmp/ppp.log 2>&1 &')

    # prepare runtime config for pshu namespace
    cfg = {
        "listen_ip": "0.0.0.0",
        "listen_port": 8000,
        "log_level": "INFO",
        "log_file": "/tmp/pshu.log",
        "ntp": {"enabled": False},
        "routes": [
            {"prefix": "/dsp1", "route_type": "local", "driver": {"name": "dsp1", "host": "10.0.0.3", "port": 9000, "protocol": "udp", "retry": {"retries": 1}}},
            {"prefix": "/ppp1", "route_type": "ppp", "driver": {"name": "ppp1", "host": "10.0.0.4", "port": 9001, "protocol": "udp", "retry": {"retries": 1}}},
        ],
    }
    (repo / 'config.e2e.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    pshu.cmd(f'cd {repo} && cp config.e2e.json config.example.json && python3 main.py > /tmp/pshu.stdout 2>&1 &')
    time.sleep(1.5)

    controller.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 20 --mode message')
    controller.cmd("python3 - <<'EOF'\nfrom pythonosc.udp_client import SimpleUDPClient\nc=SimpleUDPClient('10.0.0.2',8000)\nfor i in range(10):\n c.send_message('/ppp1/cmd',[i])\nEOF")

    time.sleep(1.0)

    pshu_log = pshu.cmd('cat /tmp/pshu.log 2>/dev/null || cat /tmp/pshu.stdout 2>/dev/null || true')
    dsp_count_raw = dsp1.cmd("python3 - <<'EOF'\nfrom pathlib import Path\np=Path('/tmp/dsp_messages.jsonl')\nprint(sum(1 for _ in p.open()) if p.exists() else 0)\nEOF").strip()
    ppp_count_raw = ppp1.cmd("python3 - <<'EOF'\nfrom pathlib import Path\np=Path('/tmp/ppp_messages.jsonl')\nprint(sum(1 for _ in p.open()) if p.exists() else 0)\nEOF").strip()

    def _to_int_safe(v: str) -> int:
        import re
        m = re.search(r"(\\d+)", v)
        return int(m.group(1)) if m else 0

    dsp_count = _to_int_safe(dsp_count_raw)
    ppp_count = _to_int_safe(ppp_count_raw)

    parsed = parse_pshu_log(pshu_log)
    result = {
        'ping_drop': ping_drop,
        'dsp_count': int(dsp_count),
        'ppp_count': int(ppp_count),
        'log_counts': parsed,
    }

    (repo / 'mininet_e2e_report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    # assertions (single-file self-test)
    ok = True
    ok &= ping_drop == 0.0
    ok &= result['dsp_count'] > 0
    ok &= result['ppp_count'] > 0
    ok &= parsed['route_hit'] > 0
    ok &= parsed['tx_ok'] > 0

    pshu.cmd('pkill -f "python3 main.py" || true')
    dsp1.cmd('pkill -f "mock_device_udp.py" || true')
    ppp1.cmd('pkill -f "mock_device_udp.py" || true')
    net.stop()

    if not ok:
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
