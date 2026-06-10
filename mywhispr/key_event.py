from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KeyEvent:
    device_path: str
    device_name: str
    code: int
    value: int  # 0=up, 1=down, 2=repeat
