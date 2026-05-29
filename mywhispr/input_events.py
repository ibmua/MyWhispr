from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import evdev
import pyudev

log = logging.getLogger(__name__)


@dataclass
class KeyEvent:
    device_path: str
    device_name: str
    code: int
    value: int  # 0=up, 1=down, 2=repeat


def _is_keyboard(dev: evdev.InputDevice) -> bool:
    caps = dev.capabilities()
    keys = caps.get(evdev.ecodes.EV_KEY, [])
    # A real keyboard has letter keys; KEY_A=30 is a reasonable marker.
    return evdev.ecodes.KEY_A in keys and evdev.ecodes.KEY_ENTER in keys


def list_keyboards() -> list[evdev.InputDevice]:
    out: list[evdev.InputDevice] = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            if _is_keyboard(dev):
                out.append(dev)
            else:
                dev.close()
        except Exception:
            dev.close()
    return out


class InputSupervisor:
    """Owns evdev tasks for all keyboards. Supports hot-plug via pyudev.
    Provides a non-blocking EVIOCGRAB on a configured subset of devices.
    """

    def __init__(
        self,
        on_key,
        *,
        include_patterns: list[str] | None,
        exclude_patterns: list[str],
    ) -> None:
        self._on_key = on_key
        self._include_patterns = [p.lower() for p in (include_patterns or [])]
        self._exclude_patterns = [p.lower() for p in (exclude_patterns or [])]
        self._devices: dict[str, evdev.InputDevice] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._grabbed: set[str] = set()
        self._udev_task: asyncio.Task | None = None

    def _device_matches_grab(self, name: str) -> bool:
        n = (name or "").lower()
        for ex in self._exclude_patterns:
            if ex and ex in n:
                return False
        if not self._include_patterns:
            return True
        for inc in self._include_patterns:
            if inc and inc in n:
                return True
        return False

    async def start(self) -> None:
        for dev in list_keyboards():
            self._add(dev)
        self._udev_task = asyncio.create_task(self._watch_udev())

    async def stop(self) -> None:
        if self._udev_task:
            self._udev_task.cancel()
            try:
                await self._udev_task
            except asyncio.CancelledError:
                pass
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for path, dev in list(self._devices.items()):
            try:
                if path in self._grabbed:
                    try:
                        dev.ungrab()
                    except Exception:
                        pass
                dev.close()
            except Exception:
                pass
        self._devices.clear()
        self._tasks.clear()
        self._grabbed.clear()

    def _add(self, dev: evdev.InputDevice) -> None:
        if dev.path in self._devices:
            return
        log.info("evdev attach path=%s name=%r", dev.path, dev.name)
        self._devices[dev.path] = dev
        self._tasks[dev.path] = asyncio.create_task(self._watch(dev))

    def _remove(self, path: str, *, cancel_task: bool = True) -> None:
        task = self._tasks.pop(path, None)
        if task and cancel_task and task is not asyncio.current_task():
            task.cancel()
        dev = self._devices.pop(path, None)
        if dev:
            try:
                dev.close()
            except Exception:
                pass
            log.info("evdev detach path=%s", path)
        self._grabbed.discard(path)

    async def _watch(self, dev: evdev.InputDevice) -> None:
        try:
            async for ev in dev.async_read_loop():
                if ev.type != evdev.ecodes.EV_KEY:
                    continue
                self._on_key(KeyEvent(dev.path, dev.name or "", ev.code, ev.value))
        except OSError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("evdev watcher crashed path=%s", dev.path)
        finally:
            self._remove(dev.path, cancel_task=False)

    async def _watch_udev(self) -> None:
        ctx = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(ctx)
        monitor.filter_by("input")
        monitor.start()
        loop = asyncio.get_event_loop()
        # Drain udev events without blocking the loop.
        try:
            while True:
                action_dev = await loop.run_in_executor(None, _udev_poll, monitor)
                if action_dev is None:
                    continue
                action, devnode, name = action_dev
                if action == "add" and devnode and devnode.startswith("/dev/input/event"):
                    try:
                        dev = evdev.InputDevice(devnode)
                    except OSError:
                        continue
                    if _is_keyboard(dev):
                        self._add(dev)
                    else:
                        dev.close()
                elif action == "remove" and devnode in self._devices:
                    self._remove(devnode)
        except asyncio.CancelledError:
            return

    def grab_for_combo(self) -> int:
        """Grab matching devices. Returns count grabbed."""
        n = 0
        for path, dev in self._devices.items():
            if path in self._grabbed:
                continue
            if not self._device_matches_grab(dev.name or ""):
                continue
            try:
                dev.grab()
                self._grabbed.add(path)
                n += 1
            except Exception as e:
                log.warning("grab failed path=%s err=%s", path, e)
        if n:
            log.info("grab acquired devices=%d", n)
        return n

    def ungrab_all(self) -> None:
        if not self._grabbed:
            return
        for path in list(self._grabbed):
            dev = self._devices.get(path)
            if dev is None:
                self._grabbed.discard(path)
                continue
            try:
                dev.ungrab()
            except Exception:
                pass
            self._grabbed.discard(path)
        log.info("grab released")

    def device_names(self) -> list[str]:
        return [d.name or "" for d in self._devices.values()]


def _udev_poll(monitor: pyudev.Monitor):
    try:
        dev = monitor.poll(timeout=1.0)
    except Exception:
        return None
    if dev is None:
        return None
    return (dev.action, dev.device_node, dev.get("NAME") or "")
