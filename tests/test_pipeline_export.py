from datetime import UTC, datetime
from pathlib import Path

import yaml

from nepal_jobs.database import Database
from nepal_jobs.exporting import export_public_data
from nepal_jobs.models import CollectionBatch, JobCandidate, SourceDefinition, WorkplaceType
from nepal_jobs.pipeline import Pipeline
from nepal_jobs.settings import Settings
from nepal_jobs.source_catalog import SourceCatalog


def settings_for(root: Path) -> Settings:
    return Settings(
        root=root,
        data_dir=root / "data",
        db_path=root / "data" / "work" / "jobs.duckdb",
        raw_dir=root / "data" / "private" / "raw",
        source_dir=root / "config" / "sources",
        user_agent="Fixture/1.0 (contact: fixture@example.com)",
        contact_email="fixture@example.com",
        brave_api_key=None,
        google_places_api_key=None,
        r2_endpoint_url=None,
        r2_bucket=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
    )


def fixture_source() -> SourceDefinition:
    return SourceDefinition(
        id="fixture",
        name="Fixture API",
        owner="Tests",
        kind="remote_jobs",
        connector="remotive",
        base_url="https://example.test/api",
        access_mode="api",
        obey_robots=False,
        attribution="Fixture attribution",
        redistribution="attributed",
    )


def fixture_job() -> JobCandidate:
    return JobCandidate(
        source_id="fixture",
        source_url="https://example.test/jobs/1",
        external_id="1",
        company_name="Example Labs",
        company_website="https://example.test",
        title="Junior Python Engineer",
        description="PRIVATE LONG DESCRIPTION Python and Docker. 1-2 years experience.",
        description_public=True,
        apply_url="https://example.test/apply/1?utm_source=fixture",
        location_text="Worldwide",
        candidate_location="Worldwide",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(UTC),
    )


def write_source(root: Path, source: SourceDefinition) -> SourceCatalog:
    source_dir = root / "config" / "sources"
    source_dir.mkdir(parents=True)
    (source_dir / "fixture.yaml").write_text(
        yaml.safe_dump(source.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return SourceCatalog(source_dir)


def test_pipeline_archives_deduplicates_exports_and_bootstraps(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    events: list[tuple[str, dict[str, object]]] = []
    pipeline = Pipeline(settings, lambda event, fields=None: events.append((event, fields or {})))
    source = fixture_source()
    catalog = write_source(tmp_path, source)
    batch = CollectionBatch(jobs=[fixture_job()], full_snapshot=True)

    with Database(settings.db_path) as database:
        result = pipeline._persist(database, source, "fixture-run", batch)
        assert result.jobs == 1
        assert database.connection.execute("SELECT count(*) FROM companies").fetchone()[0] == 1
        assert database.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2
        export_public_data(database, catalog, settings.data_dir / "current", "csv")

    event_names = [event for event, _ in events]
    assert "archive_started" in event_names
    assert "jobs_progress" in event_names
    assert "persistence_completed" in event_names

    jobs_csv = (settings.data_dir / "current" / "jobs.csv").read_text(encoding="utf-8")
    assert "public_description" not in jobs_csv.splitlines()[0]
    assert "PRIVATE LONG DESCRIPTION" not in jobs_csv

    bootstrap_path = settings.data_dir / "work" / "bootstrap.duckdb"
    with Database(bootstrap_path) as bootstrapped:
        assert bootstrapped.bootstrap_from_public_exports(settings.data_dir / "current") is True
        assert bootstrapped.connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert bootstrapped.connection.execute("SELECT missing_runs FROM jobs").fetchone()[0] == 0


def test_empty_snapshot_cannot_close_jobs_and_two_absences_do(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    pipeline = Pipeline(settings)
    source = fixture_source()
    with Database(settings.db_path) as database:
        pipeline._persist(
            database,
            source,
            "fixture-run",
            CollectionBatch(jobs=[fixture_job()], full_snapshot=True),
        )
        pipeline._apply_missing_job_lifecycle(database, source.id, set())
        assert database.connection.execute("SELECT status FROM jobs").fetchone()[0] == "active"
        pipeline._apply_missing_job_lifecycle(database, source.id, {"different-id"})
        assert database.connection.execute("SELECT missing_runs FROM jobs").fetchone()[0] == 1
        pipeline._apply_missing_job_lifecycle(database, source.id, {"different-id"})
        assert database.connection.execute("SELECT status FROM jobs").fetchone()[0] == "closed"
