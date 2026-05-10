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
    routes = [RouteConfig(**r) for r in cfg.get("routes", [])]
    seen: Dict[str, int] = {}
    for i, route in enumerate(routes):
        prefix = _normalize_prefix(route.prefix)
        if prefix in seen:
            raise ValueError(f"Duplicate route prefix: {prefix} (entries {seen[prefix]} and {i})")
        seen[prefix] = i
        route.prefix = prefix
        _validate_driver(route.driver, route.prefix)
    return routes


def parse_ntp(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg.get("ntp", {})


def _normalize_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("Route prefix must be a non-empty string")
    p = prefix.strip()
    if not p.startswith("/"):
        raise ValueError(f"Route prefix must start with '/': {prefix}")
    while "//" in p:
        p = p.replace("//", "/")
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def _validate_driver(driver: Dict[str, Any], prefix: str) -> None:
    required = ("name", "host", "port")
    missing = [k for k in required if k not in driver]
    if missing:
        raise ValueError(f"Route {prefix}: missing driver keys: {', '.join(missing)}")
