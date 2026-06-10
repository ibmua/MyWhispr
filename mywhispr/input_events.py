from __future__ import annotations

import sys

from .key_event import KeyEvent

if sys.platform == "win32":
    from .input_events_windows import WindowsInputSupervisor as InputSupervisor
else:
    from .input_events_linux import InputSupervisor

__all__ = ["KeyEvent", "InputSupervisor"]
