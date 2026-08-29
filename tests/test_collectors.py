from datetime import UTC, datetime
from pathlib import Path

from nepal_jobs.collectors.remote_feeds import RemoteOkCollector, RemotiveCollector
from nepal_jobs.models import FetchedDocument, SourceDefinition

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureClient:
    def __init__(self, fixture: str):
        self.payload = (FIXTURES / fixture).read_bytes()

    def fetch(self, url, source, **kwargs):  # type: ignore[no-untyped-def]
        return FetchedDocument(
            source_id=source.id,
            url=url,
            fetched_at=datetime.now(UTC),
            status_code=200,
            content_type="application/json",
            content=self.payload,
        )


def source(source_id: str, connector: str, base_url: str) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        name=source_id,
        owner="fixture",
        kind="remote_jobs",
        connector=connector,
        base_url=base_url,
        access_mode="api",
        obey_robots=False,
        attribution="fixture",
        redistribution="attributed",
    )


def test_remoteok_fixture() -> None:
    batch = RemoteOkCollector().collect(
        FixtureClient("remoteok.json"), source("remoteok", "remoteok", "https://example.test/api")
    )
    assert len(batch.jobs) == 1
    assert batch.jobs[0].title == "Junior Python Engineer"
    assert batch.jobs[0].candidate_location == "Worldwide"


def test_remotive_fixture() -> None:
    batch = RemotiveCollector().collect(
        FixtureClient("remotive.json"), source("remotive", "remotive", "https://example.test/api")
    )
    assert len(batch.jobs) == 1
    assert batch.jobs[0].company_name == "Quality Works"
    assert batch.jobs[0].description_public is True
