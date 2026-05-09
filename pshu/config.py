from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class RouteConfig:
    prefix: str
    route_type: str
    driver: Dict[str, Any]


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyYAML is required for YAML config") from exc
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if p.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml(p)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_routes(cfg: Dict[str, Any]) -> List[RouteConfig]:
    return [RouteConfig(**r) for r in cfg.get("routes", [])]


def parse_ntp(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg.get("ntp", {})
