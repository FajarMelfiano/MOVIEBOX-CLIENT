from datetime import date

from moviebox_api.constants import SubjectType
from moviebox_api.stremio.catalog import StremioSearchItem, _search_sort_key


def _item(*, title: str, year: int, rating: float, subject_type: SubjectType) -> StremioSearchItem:
    stremio_type = "series" if subject_type == SubjectType.TV_SERIES else "movie"
    return StremioSearchItem(
        subjectId=title.lower().replace(" ", "-"),
        subjectType=subject_type,
        title=title,
        description="",
        releaseDate=date(year, 1, 1),
        imdbRatingValue=rating,
        genre=[],
        imdbId="",
        releaseInfo=str(year),
        page_url="",
        stremioType=stremio_type,
        metadata={},
    )


def test_search_sort_key_prefers_exact_title_over_related_spinoff():
    exact_match = _item(
        title="Stranger Things",
        year=2016,
        rating=8.7,
        subject_type=SubjectType.TV_SERIES,
    )
    related_spinoff = _item(
        title="Beyond Stranger Things",
        year=2017,
        rating=9.9,
        subject_type=SubjectType.TV_SERIES,
    )

    assert _search_sort_key("Stranger Things", exact_match) > _search_sort_key(
        "Stranger Things",
        related_spinoff,
    )
