from pathlib import Path

from nepal_jobs.source_catalog import SourceCatalog


def test_repository_source_catalog_is_valid() -> None:
    root = Path(__file__).parents[1]
    catalog = SourceCatalog(root / "config" / "sources")
    assert catalog.check() == []
    assert {"remoteok", "remotive", "himalayas", "greenhouse", "google_places"} <= set(
        catalog.load()
    )
