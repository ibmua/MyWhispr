from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .daemon import Daemon


def _setup_logging() -> None:
    level = os.environ.get("MYWHISPR_LOG", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def _config_path() -> Path:
    env = os.environ.get("MYWHISPR_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config.json"


def _webui_dir() -> Path:
    env = os.environ.get("MYWHISPR_WEBUI_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "webui"


async def _amain() -> int:
    _setup_logging()
    log = logging.getLogger("mywhispr.main")
    cfg_path = _config_path()
    try:
        config = load_config(cfg_path)
    except ConfigError as e:
        log.error("config error: %s", e)
        return 2
    log.info("loaded config path=%s default_model=%s", cfg_path, config.get("default_model"))
    daemon = Daemon(config, _webui_dir())
    await daemon.setup()

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _handle_signal(signame: str):
        log.info("signal %s received; shutting down", signame)
        stop_event.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal, sig.name)
    except NotImplementedError:
        # Windows: no loop signal handlers; fall back to classic handlers.
        for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGTERM)):
            signal.signal(sig, lambda *_a, s=sig: loop.call_soon_threadsafe(_handle_signal, signal.Signals(s).name))

    daemon.request_shutdown = lambda: loop.call_soon_threadsafe(stop_event.set)

    try:
        await stop_event.wait()
    finally:
        await daemon.shutdown()
    return 0


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
