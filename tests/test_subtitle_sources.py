from moviebox_api.stremio.subtitle_sources import _normalise_language_code, _preferred_language_codes


def test_normalise_language_code_keeps_canonical_three_letter_codes():
    assert _normalise_language_code("ind") == "ind"
    assert _normalise_language_code("id") == "ind"
    assert _normalise_language_code("english") == "eng"


def test_preferred_language_codes_default_to_eng_and_ind():
    assert _preferred_language_codes(None) == ["eng", "ind"]


def test_preferred_language_codes_respects_language_aliases():
    assert _preferred_language_codes(["Indonesian", "English"]) == ["ind", "eng"]
