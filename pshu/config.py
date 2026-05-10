from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("PSHU_Config")

OSC_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)*)?$")


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
    _validate_route_overlaps(routes)
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
    if not OSC_PATH_RE.match(p):
        raise ValueError(f"Malformed OSC route prefix: {prefix}")
    return p


def _validate_driver(driver: Dict[str, Any], prefix: str) -> None:
    required = ("name", "host", "port")
    missing = [k for k in required if k not in driver]
    if missing:
        raise ValueError(f"Route {prefix}: missing driver keys: {', '.join(missing)}")


def _validate_route_overlaps(routes: List[RouteConfig]) -> None:
    prefixes = sorted((r.prefix for r in routes), key=len)
    for i, base in enumerate(prefixes):
        for other in prefixes[i + 1:]:
            if other.startswith(base + "/"):
                logger.warning(
                    "Route namespace overlap detected: base=%s shadowed_by=%s (longest-prefix will apply)",
                    base,
                    other,
                )
