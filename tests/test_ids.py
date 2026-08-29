from nepal_jobs.ids import canonical_url, normalize_text, stable_id


def test_canonical_url_removes_tracking_and_sorts_query() -> None:
    assert canonical_url("HTTPS://Example.COM:443/jobs//1/?utm_source=x&b=2&a=1#top") == (
        "https://example.com/jobs/1?a=1&b=2"
    )


def test_normalize_text_preserves_nepali_and_collapses_space() -> None:
    assert normalize_text("  सूचना   प्रविधि  ") == "सूचना प्रविधि"


def test_stable_id_is_deterministic() -> None:
    assert stable_id("company", "Example") == stable_id("company", " example ")
