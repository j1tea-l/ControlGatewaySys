import json
from pathlib import Path


def test_metrics_file_exists_and_thresholds():
    p = Path('metrics.prom')
    assert p.exists(), 'metrics.prom not found'
    text = p.read_text(encoding='utf-8')
    vals = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        k, v = line.split(' ', 1)
        vals[k] = float(v)
    assert vals.get('pshu_loss_rate', 1.0) <= 0.5
    assert vals.get('pshu_latency_p95_ms', 999999) <= 2000
