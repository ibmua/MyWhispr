from __future__ import annotations

import array
import math
import re


_TRIM = re.compile(r"^[\s,.;:!?…\"'()\[\]{}-]+|[\s,.;:!?…\"'()\[\]{}-]+$")
_JUNK_BYLINE = re.compile(
    r"\b(?:transcription|translation|subtitles?|captions?)\s+by(?:\s+[A-Za-z0-9_.’'-]+){0,8}\s*[.?!…—–-]*",
    re.IGNORECASE,
)
_LEFTOVER = re.compile(r"^[\s,.;:!?…\"'()\[\]{}—–-]*$")
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)
_BYLINE_HINT = re.compile(r"\b(?:transcription|translation|subtitles?|captions?)\s+by\b", re.IGNORECASE)


def rms_int16(buf: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(buf)
    n = len(samples)
    if n == 0:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / n)


def strip_outros(text: str, language: str, phrases: dict[str, list[str]]) -> str:
    """If text ends with one of the language's outro phrases, strip it."""
    bucket = phrases.get(language) or []
    bucket = sorted(bucket, key=len, reverse=True)
    stripped = text.rstrip(" .!?…")
    for phrase in bucket:
        target = phrase.strip()
        if not target:
            continue
        if text.rstrip().endswith(target):
            cut = text.rstrip()[: -len(target)]
            return cut.rstrip(" ,.!?…")
        # Try case-insensitive fallback for Latin scripts
        if language == "en" and stripped.lower().endswith(target.rstrip(" .!?").lower()):
            idx = stripped.lower().rfind(target.rstrip(" .!?").lower())
            return stripped[:idx].rstrip(" ,.!?…")
        pattern = _phrase_pattern(target, end=True)
        if pattern:
            match = pattern.search(text)
            if match:
                return text[: match.start()].rstrip(" ,.!?…")
    return text


def _norm_phrase(text: str) -> str:
    return _TRIM.sub("", text).casefold()


def _compact_phrase(text: str) -> str:
    return "".join(_TOKEN.findall(text.casefold()))


def _phrase_pattern(phrase: str, *, end: bool = False) -> re.Pattern | None:
    tokens = _TOKEN.findall(phrase)
    if not tokens:
        return None
    body = r"[^\w]+".join(re.escape(t) for t in tokens)
    suffix = r"[\s,.;:!?…\"'()\[\]{}—–-]*" + ("$" if end else "")
    return re.compile(r"(?<!\w)" + body + r"(?!\w)" + suffix, re.IGNORECASE)


def _phrase_iter(phrases: dict[str, list[str]], always_strip_phrases: list[str] | None = None):
    for bucket in phrases.values():
        for phrase in bucket or []:
            yield str(phrase)
    for phrase in always_strip_phrases or []:
        yield str(phrase)


def is_exact_phrase(
    text: str,
    phrases: dict[str, list[str]],
    always_strip_phrases: list[str] | None = None,
) -> bool:
    """Return True when the whole transcript is one known hallucination phrase."""
    got = _norm_phrase(text)
    compact_got = _compact_phrase(text)
    if not got:
        return False
    for phrase in _phrase_iter(phrases, always_strip_phrases):
        if got == _norm_phrase(phrase) or compact_got == _compact_phrase(phrase):
            return True
    return False


def _strip_phrase_pattern(text: str, phrase: str) -> str:
    pattern = _phrase_pattern(phrase)
    if not pattern:
        return text
    return pattern.sub("", text)


def strip_global_junk(
    text: str,
    always_strip_phrases: list[str] | None = None,
    phrases: dict[str, list[str]] | None = None,
) -> str:
    """Remove known global transcript/translation byline hallucinations."""
    out = text
    for phrase in always_strip_phrases or []:
        target = str(phrase).strip()
        if not target:
            continue
        out = re.sub(re.escape(target), "", out, flags=re.IGNORECASE)
        out = _strip_phrase_pattern(out, target)
    for phrase in _phrase_iter(phrases or {}):
        target = str(phrase).strip()
        if target and _BYLINE_HINT.search(target):
            out = _strip_phrase_pattern(out, target)
    out = _JUNK_BYLINE.sub("", out)
    out = _WS.sub(" ", out).strip(" ,.;:!?…—–-")
    if _LEFTOVER.match(out):
        return ""
    return out


def apply(
    text: str,
    *,
    tail_audio_pcm: bytes,
    language: str,
    enabled: bool,
    silence_rms_threshold: float,
    phrases: dict[str, list[str]],
    always_strip_phrases: list[str] | None = None,
) -> str:
    if not enabled or not text:
        return text
    if is_exact_phrase(text, phrases, always_strip_phrases):
        return ""
    text = strip_global_junk(text, always_strip_phrases, phrases)
    if not text:
        return ""
    tail_rms = rms_int16(tail_audio_pcm)
    if tail_rms >= silence_rms_threshold:
        return text
    return strip_outros(text, language, phrases)
