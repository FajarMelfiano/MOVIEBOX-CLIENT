"""Language normalization and display helpers."""

from __future__ import annotations

import re

_UNKNOWN = "unknown"

_CANONICAL_TO_DISPLAY = {
    "eng": "English",
    "ind": "Indonesian",
    "spa": "Spanish",
    "fre": "French",
    "ger": "German",
    "ita": "Italian",
    "por": "Portuguese",
    "rus": "Russian",
    "ara": "Arabic",
    "tur": "Turkish",
    "jpn": "Japanese",
    "kor": "Korean",
    "zho": "Chinese",
    "vie": "Vietnamese",
    "tha": "Thai",
    "dut": "Dutch",
    "pol": "Polish",
    "rum": "Romanian",
    "per": "Persian",
    "hin": "Hindi",
    "msa": "Malay",
    "tgl": "Tagalog",
    "ukr": "Ukrainian",
}

_CANONICAL_TO_ISO6391 = {
    "eng": "en",
    "ind": "id",
    "spa": "es",
    "fre": "fr",
    "ger": "de",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "ara": "ar",
    "tur": "tr",
    "jpn": "ja",
    "kor": "ko",
    "zho": "zh",
    "vie": "vi",
    "tha": "th",
    "dut": "nl",
    "pol": "pl",
    "rum": "ro",
    "per": "fa",
    "hin": "hi",
    "msa": "ms",
    "tgl": "tl",
    "ukr": "uk",
}

_ALIASES = {
    "english": "eng",
    "eng": "eng",
    "en": "eng",
    "indonesian": "ind",
    "ind": "ind",
    "id": "ind",
    "bahasa": "ind",
    "spanish": "spa",
    "spa": "spa",
    "es": "spa",
    "french": "fre",
    "fre": "fre",
    "fra": "fre",
    "fr": "fre",
    "german": "ger",
    "ger": "ger",
    "deu": "ger",
    "de": "ger",
    "italian": "ita",
    "ita": "ita",
    "it": "ita",
    "portuguese": "por",
    "por": "por",
    "pt": "por",
    "russian": "rus",
    "rus": "rus",
    "ru": "rus",
    "arabic": "ara",
    "ara": "ara",
    "ar": "ara",
    "turkish": "tur",
    "tur": "tur",
    "tr": "tur",
    "japanese": "jpn",
    "jpn": "jpn",
    "ja": "jpn",
    "korean": "kor",
    "kor": "kor",
    "ko": "kor",
    "chinese": "zho",
    "zho": "zho",
    "chi": "zho",
    "zh": "zho",
    "vietnamese": "vie",
    "vie": "vie",
    "vi": "vie",
    "thai": "tha",
    "tha": "tha",
    "th": "tha",
    "dutch": "dut",
    "dut": "dut",
    "nld": "dut",
    "nl": "dut",
    "polish": "pol",
    "pol": "pol",
    "pl": "pol",
    "romanian": "rum",
    "rum": "rum",
    "ron": "rum",
    "ro": "rum",
    "persian": "per",
    "farsi": "per",
    "per": "per",
    "fas": "per",
    "fa": "per",
    "hindi": "hin",
    "hin": "hin",
    "hi": "hin",
    "malay": "msa",
    "msa": "msa",
    "may": "msa",
    "ms": "msa",
    "tagalog": "tgl",
    "filipino": "tgl",
    "tgl": "tgl",
    "tl": "tgl",
    "ukrainian": "ukr",
    "ukr": "ukr",
    "uk": "ukr",
}


def normalize_language_id(language: str | None) -> str:
    """Normalize input language string into canonical short id."""

    if not language:
        return _UNKNOWN

    lowered = language.strip().lower()
    if not lowered:
        return _UNKNOWN

    if lowered in _ALIASES:
        return _ALIASES[lowered]

    compact = re.sub(r"[^a-z]", "", lowered)
    if not compact:
        return _UNKNOWN

    if compact in _ALIASES:
        return _ALIASES[compact]

    if len(compact) == 2 and compact.isascii():
        return compact

    if len(compact) >= 3:
        return compact[:3]

    return _UNKNOWN


def language_display_name(language: str | None) -> str:
    """Return user-friendly language name."""

    normalized = normalize_language_id(language)
    if normalized == _UNKNOWN:
        return "Unknown"

    if normalized in _CANONICAL_TO_DISPLAY:
        return _CANONICAL_TO_DISPLAY[normalized]

    if len(normalized) == 2:
        return normalized.upper()

    return normalized.title()


def to_iso639_1(language: str | None) -> str | None:
    """Return ISO-639-1 code when known."""

    normalized = normalize_language_id(language)
    if normalized == _UNKNOWN:
        return None

    if len(normalized) == 2:
        return normalized

    return _CANONICAL_TO_ISO6391.get(normalized)
