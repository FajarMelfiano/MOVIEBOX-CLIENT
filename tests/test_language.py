from moviebox_api.language import language_display_name, normalize_language_id, to_iso639_1


def test_normalize_language_id_maps_aliases():
    assert normalize_language_id("Indonesian") == "ind"
    assert normalize_language_id("id") == "ind"
    assert normalize_language_id("ENG") == "eng"


def test_language_display_name_returns_full_language_name():
    assert language_display_name("ind") == "Indonesian"
    assert language_display_name("ara") == "Arabic"


def test_to_iso639_1_converts_known_languages():
    assert to_iso639_1("ind") == "id"
    assert to_iso639_1("eng") == "en"
