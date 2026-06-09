from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")
_WORD = re.compile(r"[\w']+", re.UNICODE)
_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", text.replace("\r", " ").replace("\n", " ")).strip()


def _norm_repeat_unit(text: str) -> str:
    text = _PUNCT.sub(" ", text).casefold()
    return _WS.sub(" ", text).strip()


def collapse_repeated_sentences(text: str) -> str:
    """Collapse consecutive repeated Whisper loop sentences.

    Whisper can occasionally get stuck repeating the same sentence many times
    when confidence is low or the tail audio is quiet. Only collapse adjacent
    units with at least four words so intentional short repetitions survive.
    """
    parts = _SENTENCE.findall(text)
    if len(parts) < 2:
        return text
    out: list[str] = []
    prev_norm = ""
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        norm = _norm_repeat_unit(cleaned)
        if norm and norm == prev_norm and len(_WORD.findall(norm)) >= 4:
            continue
        out.append(cleaned)
        prev_norm = norm
    if not out:
        return text
    return collapse_whitespace(" ".join(out))


def lowercase_first_cased(text: str) -> str:
    """Lowercase the first cased character without assuming an alphabet."""
    for idx, ch in enumerate(text):
        lowered = ch.lower()
        uppered = ch.upper()
        if lowered != uppered:
            return text[:idx] + lowered + text[idx + 1 :]
    return text


def finalize(text: str, *, append_trailing_space: bool, lowercase_initial: bool = False) -> str:
    text = collapse_whitespace(text)
    text = collapse_repeated_sentences(text)
    if not text:
        return ""
    if lowercase_initial:
        text = lowercase_first_cased(text)
    if append_trailing_space:
        text = text + " "
    return text
