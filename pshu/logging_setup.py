import logging
from logging.handlers import RotatingFileHandler


def setup_logging(log_file: str = "logs/pshu.log", level: str = "INFO") -> None:
    import os
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3)
    fh.setFormatter(fmt)

    root.handlers.clear()
    root.addHandler(ch)
    root.addHandler(fh)
