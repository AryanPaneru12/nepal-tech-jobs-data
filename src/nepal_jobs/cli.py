from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from .database import Database
from .exporting import export_public_data, export_review_queue
from .pipeline import Pipeline, WeeklyRunError
from .progress import ProgressReporter
from .settings import Settings
from .source_catalog import SourceCatalog
from .validation import validate_database, write_validation_report

app = typer.Typer(
    help="Nepal technology employers and remote jobs data pipeline.", no_args_is_help=True
)
sources_app = typer.Typer(help="Inspect and validate source policies.")
run_app = typer.Typer(help="Run orchestrated pipelines.")
review_app = typer.Typer(help="Manage human-review artifacts.")
app.add_typer(sources_app, name="sources")
app.add_typer(run_app, name="run")
app.add_typer(review_app, name="review")


def _settings() -> Settings:
    return Settings.load()


@sources_app.command("list")
def sources_list() -> None:
    """List configured data sources and policy state."""
    catalog = SourceCatalog(_settings().source_dir)
    for source in catalog.load().values():
        state = "enabled" if source.enabled else "disabled"
        typer.echo(
            f"{source.id:24} {state:8} {source.access_mode:8} {source.connector:20} {source.name}"
        )


@sources_app.command("check")
def sources_check() -> None:
    """Validate all source policy files."""
    errors = SourceCatalog(_settings().source_dir).check()
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(1)
    typer.echo("Source catalog is valid.")


@app.command()
def discover(
    source: Annotated[str, typer.Option("--source", help="Source ID")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Run a discovery source and queue leads for independent verification."""
    settings = _settings()
    progress = _progress_reporter(settings, "discover")
    _print_result(
        Pipeline(settings, progress).run_source(
            source, dry_run=dry_run, resume=resume, run_id=run_id, discovery=True
        )
    )


@app.command()
def collect(
    source: Annotated[str, typer.Option("--source", help="Source ID")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Collect and process one configured source."""
    settings = _settings()
    progress = _progress_reporter(settings, "collect")
    _print_result(
        Pipeline(settings, progress).run_source(
            source, dry_run=dry_run, resume=resume, run_id=run_id
        )
    )


@run_app.command("weekly")
def run_weekly(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Run every enabled weekly source; failures are isolated per source."""
    settings = _settings()
    progress = _progress_reporter(settings, "run-weekly")
    try:
        results = Pipeline(settings, progress).run_weekly(dry_run=dry_run, resume=resume)
    except WeeklyRunError as exc:
        for result in exc.results:
            _print_result(result)
        for source_id, error in exc.failures.items():
            typer.echo(f"FAILED {source_id}: {error}", err=True)
        raise typer.Exit(1) from exc
    for result in results:
        _print_result(result)


@app.command("validate")
def validate_command(
    release: Annotated[
        bool, typer.Option("--release", help="Enforce 500-company/2,000-job release gates")
    ] = False,
) -> None:
    """Validate schemas, provenance, deduplication, publication safety, and quality gates."""
    settings = _settings()
    settings.ensure_runtime_dirs()
    progress = _progress_reporter(settings, "validate")
    report_path = settings.data_dir / "reports" / "validation.json"
    progress("validation_started", {"release_gates": release})
    with Database(settings.db_path) as database:
        report = validate_database(database, SourceCatalog(settings.source_dir), release=release)
    write_validation_report(report, report_path)
    progress(
        "validation_completed",
        {
            "ok": report.ok,
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "report": str(report_path),
        },
    )
    typer.echo(report.model_dump_json(indent=2))
    if not report.ok:
        raise typer.Exit(1)


@app.command("export")
def export_command(
    format: Annotated[str, typer.Option("--format", help="csv, jsonl, parquet, or duckdb")] = "csv",
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Export only curated, publishable facts and provenance."""
    if format not in {"csv", "jsonl", "parquet", "duckdb"}:
        raise typer.BadParameter("format must be csv, jsonl, parquet, or duckdb")
    settings = _settings()
    target = output or settings.data_dir / "current"
    progress = _progress_reporter(settings, "export")
    progress("export_started", {"format": format, "output": str(target)})
    with Database(settings.db_path) as database:
        files = export_public_data(database, SourceCatalog(settings.source_dir), target, format)  # type: ignore[arg-type]
    for path in files:
        progress(
            "export_file_written",
            {"file": str(path), "bytes": path.stat().st_size},
        )
        typer.echo(path)
    progress("export_completed", {"format": format, "files": len(files)})


@review_app.command("export")
def review_export(output: Annotated[Path | None, typer.Option("--output")] = None) -> None:
    """Export pending entity-resolution and source-verification work."""
    settings = _settings()
    path = output or settings.data_dir / "reports" / "review_queue.jsonl"
    progress = _progress_reporter(settings, "review-export")
    progress("review_export_started", {"output": str(path)})
    with Database(settings.db_path) as database:
        count = export_review_queue(database, path)
    progress("review_export_completed", {"items": count, "output": str(path)})
    typer.echo(f"Exported {count} pending review items to {path}")


@app.command()
def stats() -> None:
    """Print current dataset and source-run statistics."""
    settings = _settings()
    with Database(settings.db_path) as database:
        row = database.connection.execute(
            """SELECT
            (SELECT count(*) FROM companies WHERE active),
            (SELECT count(*) FROM jobs WHERE status='active' AND eligibility <> 'ineligible'),
            (SELECT count(*) FROM review_queue WHERE status='pending'),
            (SELECT count(*) FROM ingestion_runs WHERE status='failed')"""
        ).fetchone()
    typer.echo(
        json.dumps(
            dict(
                zip(("companies", "active_jobs", "pending_review", "failed_runs"), row, strict=True)
            ),
            indent=2,
        )
    )


def _print_result(result) -> None:  # type: ignore[no-untyped-def]
    typer.echo(
        json.dumps(
            result.__dict__
            if hasattr(result, "__dict__")
            else {
                "run_id": result.run_id,
                "source_id": result.source_id,
                "companies": result.companies,
                "jobs": result.jobs,
                "leads": result.leads,
                "documents": result.documents,
                "skipped_non_tech": result.skipped_non_tech,
                "dry_run": result.dry_run,
            },
            indent=2,
        )
    )


def _progress_reporter(settings: Settings, command: str) -> ProgressReporter:
    reporter = ProgressReporter(settings.data_dir / "logs", command)
    reporter("log_opened", {"path": str(reporter.path)})
    return reporter


if __name__ == "__main__":
    app()
