from __future__ import annotations

import ast
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KB_SCHEMA = f"{SCHEMA}.custom-keybinding"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

KEY_PRESETS: list[dict[str, Any]] = [
    {"label": "` / grave", "binding": "grave", "keycode": 41},
    {"label": "F8", "binding": "F8", "keycode": 66},
    {"label": "F9", "binding": "F9", "keycode": 67},
    {"label": "F10", "binding": "F10", "keycode": 68},
    {"label": "F11", "binding": "F11", "keycode": 87},
    {"label": "F12", "binding": "F12", "keycode": 88},
]

COMBO_KEY_PRESETS: list[dict[str, Any]] = [
    {"label": "1", "binding": "1", "keycode": 2},
    {"label": "2", "binding": "2", "keycode": 3},
    {"label": "3", "binding": "3", "keycode": 4},
    {"label": "4", "binding": "4", "keycode": 5},
    {"label": "5", "binding": "5", "keycode": 6},
    {"label": "6", "binding": "6", "keycode": 7},
    {"label": "7", "binding": "7", "keycode": 8},
    {"label": "8", "binding": "8", "keycode": 9},
    {"label": "9", "binding": "9", "keycode": 10},
    {"label": "0", "binding": "0", "keycode": 11},
    {"label": "F8", "binding": "F8", "keycode": 66},
    {"label": "F9", "binding": "F9", "keycode": 67},
    {"label": "F10", "binding": "F10", "keycode": 68},
]

WHISPER_LANGUAGES: list[dict[str, str]] = [
    {"code": code, "name": name}
    for code, name in [
        ("auto", "Auto detect"), ("en", "English"), ("uk", "Ukrainian"), ("af", "Afrikaans"),
        ("am", "Amharic"), ("ar", "Arabic"), ("as", "Assamese"), ("az", "Azerbaijani"),
        ("ba", "Bashkir"), ("be", "Belarusian"), ("bg", "Bulgarian"), ("bn", "Bengali"),
        ("bo", "Tibetan"), ("br", "Breton"), ("bs", "Bosnian"), ("ca", "Catalan"),
        ("cs", "Czech"), ("cy", "Welsh"), ("da", "Danish"), ("de", "German"),
        ("el", "Greek"), ("es", "Spanish"), ("et", "Estonian"), ("eu", "Basque"),
        ("fa", "Persian"), ("fi", "Finnish"), ("fo", "Faroese"), ("fr", "French"),
        ("gl", "Galician"), ("gu", "Gujarati"), ("ha", "Hausa"), ("haw", "Hawaiian"),
        ("he", "Hebrew"), ("hi", "Hindi"), ("hr", "Croatian"), ("ht", "Haitian Creole"),
        ("hu", "Hungarian"), ("hy", "Armenian"), ("id", "Indonesian"), ("is", "Icelandic"),
        ("it", "Italian"), ("ja", "Japanese"), ("jw", "Javanese"), ("ka", "Georgian"),
        ("kk", "Kazakh"), ("km", "Khmer"), ("kn", "Kannada"), ("ko", "Korean"),
        ("la", "Latin"), ("lb", "Luxembourgish"), ("ln", "Lingala"), ("lo", "Lao"),
        ("lt", "Lithuanian"), ("lv", "Latvian"), ("mg", "Malagasy"), ("mi", "Maori"),
        ("mk", "Macedonian"), ("ml", "Malayalam"), ("mn", "Mongolian"), ("mr", "Marathi"),
        ("ms", "Malay"), ("mt", "Maltese"), ("my", "Burmese"), ("ne", "Nepali"),
        ("nl", "Dutch"), ("nn", "Nynorsk"), ("no", "Norwegian"), ("oc", "Occitan"),
        ("pa", "Punjabi"), ("pl", "Polish"), ("ps", "Pashto"), ("pt", "Portuguese"),
        ("ro", "Romanian"), ("ru", "Russian"), ("sa", "Sanskrit"), ("sd", "Sindhi"),
        ("si", "Sinhala"), ("sk", "Slovak"), ("sl", "Slovenian"), ("sn", "Shona"),
        ("so", "Somali"), ("sq", "Albanian"), ("sr", "Serbian"), ("su", "Sundanese"),
        ("sv", "Swedish"), ("sw", "Swahili"), ("ta", "Tamil"), ("te", "Telugu"),
        ("tg", "Tajik"), ("th", "Thai"), ("tk", "Turkmen"), ("tl", "Tagalog"),
        ("tr", "Turkish"), ("tt", "Tatar"), ("ur", "Urdu"), ("uz", "Uzbek"),
        ("vi", "Vietnamese"), ("yi", "Yiddish"), ("yo", "Yoruba"), ("yue", "Cantonese"),
        ("zh", "Chinese"),
    ]
]


def keycode_for_binding(binding: str) -> int | None:
    for preset in KEY_PRESETS:
        if preset["binding"] == binding:
            return int(preset["keycode"])
    return None


def _parse_paths(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("@as "):
        raw = raw[4:]
    try:
        parsed = ast.literal_eval(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(p) for p in parsed]


def _paths_variant(paths: list[str]) -> str:
    return "[" + ", ".join(repr(p) for p in paths) + "]"


class ShortcutManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.ctl_path = project_root / "bin" / "mywhisprctl"

    async def _run(self, *args: str) -> tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            return 127, "", str(e)
        out, err = await proc.communicate()
        return (
            proc.returncode,
            out.decode("utf-8", "replace").strip(),
            err.decode("utf-8", "replace").strip(),
        )

    async def _get(self, schema: str, key: str, *, path: str | None = None) -> str:
        target = f"{schema}:{path}" if path else schema
        rc, out, err = await self._run("gsettings", "get", target, key)
        if rc != 0:
            raise RuntimeError(err or f"gsettings get failed rc={rc}")
        return out

    async def _set(self, schema: str, key: str, value: str, *, path: str | None = None) -> None:
        target = f"{schema}:{path}" if path else schema
        rc, _out, err = await self._run("gsettings", "set", target, key, value)
        if rc != 0:
            raise RuntimeError(err or f"gsettings set failed rc={rc}")

    def command_for(self, trigger: str) -> str:
        return f"{self.ctl_path} start {trigger}"

    async def snapshot(self, triggers: dict[str, Any]) -> dict[str, Any]:
        installed: dict[str, Any] = {}
        error = ""
        if sys.platform == "win32":
            # The keyboard hook reads stop_on_release_codes straight from the
            # config; there is no desktop-level binding to install.
            return {
                "presets": KEY_PRESETS,
                "combo_presets": COMBO_KEY_PRESETS,
                "languages": WHISPER_LANGUAGES,
                "triggers": triggers,
                "installed": installed,
                "error": error,
            }
        try:
            raw = await self._get(SCHEMA, "custom-keybindings")
            paths = _parse_paths(raw)
            for path in paths:
                try:
                    name = await self._get(KB_SCHEMA, "name", path=path)
                    command = await self._get(KB_SCHEMA, "command", path=path)
                    binding = await self._get(KB_SCHEMA, "binding", path=path)
                except Exception:
                    continue
                installed[path] = {
                    "name": name.strip("'"),
                    "command": command.strip("'"),
                    "binding": binding.strip("'"),
                }
        except Exception as e:
            error = str(e)
        return {
            "presets": KEY_PRESETS,
            "combo_presets": COMBO_KEY_PRESETS,
            "languages": WHISPER_LANGUAGES,
            "triggers": triggers,
            "installed": installed,
            "error": error,
        }

    async def install_trigger(self, *, trigger: str, binding: str) -> tuple[bool, str, str]:
        if sys.platform == "win32":
            return True, "handled by keyboard hook", ""
        command = self.command_for(trigger)
        name = f"MyWhispr {trigger}"
        our_path = f"{PATH_PREFIX}/mywhispr-{trigger}/"
        raw = await self._get(SCHEMA, "custom-keybindings")
        paths = _parse_paths(raw)

        existing = ""
        for path in paths:
            try:
                cur_binding = (await self._get(KB_SCHEMA, "binding", path=path)).strip("'")
                cur_command = (await self._get(KB_SCHEMA, "command", path=path)).strip("'")
                cur_name = (await self._get(KB_SCHEMA, "name", path=path)).strip("'")
            except Exception:
                continue
            if cur_command == command or cur_name == name:
                existing = path
                break
            if cur_binding == binding:
                return False, f"{binding} is already used by {cur_name or path}", path

        path = existing or our_path
        if path not in paths:
            paths.append(path)
            await self._set(SCHEMA, "custom-keybindings", _paths_variant(paths))

        await self._set(KB_SCHEMA, "name", name, path=path)
        await self._set(KB_SCHEMA, "command", command, path=path)
        await self._set(KB_SCHEMA, "binding", binding, path=path)
        log.info("shortcut installed trigger=%s binding=%s path=%s", trigger, binding, path)
        return True, "updated", path

    async def remove_trigger(self, *, trigger: str) -> tuple[bool, str]:
        if sys.platform == "win32":
            return True, "removed"
        command = self.command_for(trigger)
        name = f"MyWhispr {trigger}"
        try:
            raw = await self._get(SCHEMA, "custom-keybindings")
            paths = _parse_paths(raw)
        except Exception as e:
            return False, str(e)
        kept: list[str] = []
        changed = False
        for path in paths:
            try:
                cur_command = (await self._get(KB_SCHEMA, "command", path=path)).strip("'")
                cur_name = (await self._get(KB_SCHEMA, "name", path=path)).strip("'")
            except Exception:
                kept.append(path)
                continue
            if cur_command == command or cur_name == name:
                changed = True
                try:
                    await self._set(KB_SCHEMA, "binding", "''", path=path)
                except Exception:
                    pass
                continue
            kept.append(path)
        if changed:
            await self._set(SCHEMA, "custom-keybindings", _paths_variant(kept))
        return True, "removed" if changed else "not_installed"
