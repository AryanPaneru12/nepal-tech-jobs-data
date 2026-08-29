from datetime import UTC, datetime

from nepal_jobs.database import Database
from nepal_jobs.models import CompanyCandidate, NepalRelationship
from nepal_jobs.resolution import CompanyResolver


def candidate(name: str, website: str | None = None) -> CompanyCandidate:
    return CompanyCandidate(
        source_id="fixture",
        source_url="https://source.example/record",
        name=name,
        website=website,
        country="Nepal",
        nepal_relationship=NepalRelationship.BASED,
        observed_at=datetime.now(UTC),
    )


def test_domain_is_authoritative_merge_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with Database(tmp_path / "test.duckdb") as database:
        resolver = CompanyResolver(database)
        first, _ = resolver.resolve(candidate("Example Technologies", "https://example.com"))
        database.upsert_company(first)
        second, review = resolver.resolve(
            candidate("Example Tech Pvt Ltd", "https://www.example.com/about")
        )
        assert second.company_id == first.company_id
        assert review is False


def test_similar_but_ambiguous_name_requires_review(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with Database(tmp_path / "test.duckdb") as database:
        resolver = CompanyResolver(database)
        first, _ = resolver.resolve(candidate("Kathmandu Software Solutions"))
        database.upsert_company(first)
        _, review = resolver.resolve(candidate("Kathmandu Software Solution Pvt Ltd"))
        assert review is True
