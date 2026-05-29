from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class ControlSocketServer:
    """Unix-socket JSON line protocol. Used by mywhisprctl (GNOME shortcut)."""

    def __init__(self, path: Path, handler) -> None:
        self.path = path
        self.handler = handler
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except FileNotFoundError:
            pass
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.server = await asyncio.start_unix_server(self._client, path=str(self.path))
        os.chmod(self.path, 0o600)
        log.info("control socket listening path=%s", self.path)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not line:
                return
            try:
                req = json.loads(line.decode("utf-8"))
            except Exception:
                writer.write(json.dumps({"ok": False, "reason": "invalid_json"}).encode("utf-8") + b"\n")
                await writer.drain()
                return
            try:
                resp = await self.handler(req)
            except Exception as e:
                log.exception("control handler failed")
                resp = {"ok": False, "reason": f"exception: {e}"}
            writer.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
            await writer.drain()
        except asyncio.TimeoutError:
            return
        except ConnectionResetError:
            return
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:
                pass
            self.server = None
        try:
            if self.path.exists():
                self.path.unlink()
        except FileNotFoundError:
            pass
