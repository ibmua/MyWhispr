from __future__ import annotations

import re

_WS = re.compile(r"\s+")
# A sentence boundary is a terminator followed by whitespace (or end of text).
# Requiring the trailing whitespace keeps dotted tokens intact: "CLAUDE.md",
# "psymeasure.com", and decimals like "2.5" are NOT sentence boundaries because
# no space follows the dot. A naive split on "." alone shattered those tokens
# (e.g. "CLAUDE.md" -> "CLAUDE. md").
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")
_WORD = re.compile(r"[\w']+", re.UNICODE)
_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", text.replace("\r", " ").replace("\n", " ")).strip()


def text_from_segments(segments, fallback: str = "") -> str:
    """Reconstruct transcript text by concatenating Whisper segment texts.

    Whisper segment texts carry their own leading space at word boundaries and
    no leading space mid-word, so plain concatenation rebuilds the original
    token stream exactly. The whisper.cpp server's top-level ``text`` field
    instead joins segments with ``"\n"``; ``collapse_whitespace`` then turns
    that newline into a space, which becomes a visible mid-word break whenever
    a segment starts in the middle of a word. That is common for Ukrainian and
    other languages whose words tokenize into many sub-word pieces, and happens
    in English too at BPE seams ("negligible" -> "neglig" + "ible"). Falls back
    to ``fallback`` when no segment carries text (e.g. GPU backends that return
    ``segments: []``).

    Some external APIs instead trim every segment text; concatenating those
    would glue words together, so when no segment carries a leading space we
    space-join the trimmed pieces. The convention is detected per response.
    """
    parts: list[str] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        chunk = seg.get("text")
        if chunk:
            parts.append(str(chunk))
    if not parts:
        return fallback
    if any(part[:1].isspace() for part in parts):
        return "".join(parts)
    return " ".join(part.strip() for part in parts)


def _norm_repeat_unit(text: str) -> str:
    text = _PUNCT.sub(" ", text).casefold()
    return _WS.sub(" ", text).strip()


def collapse_repeated_sentences(text: str) -> str:
    """Collapse consecutive repeated Whisper loop sentences.

    Whisper can occasionally get stuck repeating the same sentence many times
    when confidence is low or the tail audio is quiet. Only collapse adjacent
    units with at least four words so intentional short repetitions survive.

    Sentences are split only at a terminator followed by whitespace, so dotted
    tokens (filenames, domains, decimals) are never broken apart.
    """
    parts = _SENTENCE_BOUNDARY.split(text)
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
