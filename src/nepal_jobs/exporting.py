from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb

from .database import Database
from .source_catalog import SourceCatalog

ExportFormat = Literal["csv", "jsonl", "parquet", "duckdb"]

PUBLIC_QUERIES = {
    "companies": "SELECT * FROM companies WHERE active ORDER BY canonical_name, company_id",
    "jobs": """SELECT * EXCLUDE (public_description) FROM jobs
               WHERE status='active' AND eligibility <> 'ineligible'
               ORDER BY last_seen_at DESC, job_id""",
    "evidence": """SELECT * FROM evidence WHERE record_id IN
                 (SELECT company_id FROM companies WHERE active UNION ALL
                  SELECT job_id FROM jobs WHERE status='active' AND eligibility <> 'ineligible')
                 ORDER BY record_type, record_id, evidence_id""",
    "runs": """SELECT run_id, source_id, started_at, finished_at, status, full_snapshot,
              fetched_count, company_count, job_count, lead_count, failure_count
              FROM ingestion_runs ORDER BY started_at DESC, run_id""",
}


def export_public_data(
    database: Database,
    catalog: SourceCatalog,
    output_dir: Path,
    export_format: ExportFormat,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    if export_format == "duckdb":
        generated.append(_export_duckdb(database, output_dir / "nepal_jobs_public.duckdb"))
    else:
        for name, query in PUBLIC_QUERIES.items():
            path = output_dir / f"{name}.{export_format}"
            if export_format == "csv":
                database.connection.execute(
                    f"COPY ({query}) TO ? (HEADER, DELIMITER ',', QUOTE '\"', ESCAPE '\"')",
                    [str(path)],
                )
            elif export_format == "parquet":
                database.connection.execute(
                    f"COPY ({query}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)]
                )
            else:
                _write_jsonl(database, query, path)
            generated.append(path)

    generated.extend(_write_metadata(database, catalog, output_dir))
    manifest = _write_manifest(output_dir, generated)
    generated.append(manifest)
    return generated


def export_review_queue(database: Database, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    cursor = database.connection.execute(
        "SELECT * FROM review_queue WHERE status='pending' ORDER BY created_at, review_id"
    )
    columns = [item[0] for item in cursor.description]
    rows = cursor.fetchall()
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(dict(zip(columns, row, strict=True)), default=str, ensure_ascii=False)
                + "\n"
            )
    return len(rows)


def _write_jsonl(database: Database, query: str, path: Path) -> None:
    cursor = database.connection.execute(query)
    columns = [item[0] for item in cursor.description]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in cursor.fetchall():
            handle.write(
                json.dumps(dict(zip(columns, row, strict=True)), default=str, ensure_ascii=False)
                + "\n"
            )


def _export_duckdb(database: Database, path: Path) -> Path:
    path.unlink(missing_ok=True)
    target = duckdb.connect(str(path))
    try:
        for name, query in PUBLIC_QUERIES.items():
            arrow_table = database.connection.execute(query).fetch_arrow_table()
            target.register("export_batch", arrow_table)
            target.execute(f"CREATE TABLE {name} AS SELECT * FROM export_batch")
            target.unregister("export_batch")
    finally:
        target.close()
    return path


def _write_metadata(database: Database, catalog: SourceCatalog, output_dir: Path) -> list[Path]:
    sources_path = output_dir / "sources.json"
    sources_path.write_text(
        json.dumps(
            [source.model_dump(mode="json") for source in catalog.load().values()],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    attribution_path = output_dir / "ATTRIBUTION.md"
    attribution_path.write_text(
        "# Source attribution\n\n"
        + "\n".join(
            f"- **{source.name}:** {source.attribution} ({source.terms_url or source.base_url or 'manual source'})"
            for source in catalog.load().values()
        )
        + "\n",
        encoding="utf-8",
    )
    counts = {
        "companies": int(
            database.connection.execute("SELECT count(*) FROM companies WHERE active").fetchone()[0]
        ),
        "active_jobs": int(
            database.connection.execute(
                "SELECT count(*) FROM jobs WHERE status='active' AND eligibility <> 'ineligible'"
            ).fetchone()[0]
        ),
        "pending_review": int(
            database.connection.execute(
                "SELECT count(*) FROM review_queue WHERE status='pending'"
            ).fetchone()[0]
        ),
    }
    coverage_path = output_dir / "COVERAGE.md"
    coverage_path.write_text(
        "# Coverage report\n\n"
        f"Generated: {datetime.now(UTC).isoformat()}\n\n"
        f"- Verified/relevant companies: {counts['companies']}\n"
        f"- Active publishable jobs: {counts['active_jobs']}\n"
        f"- Pending review items: {counts['pending_review']}\n\n"
        "Counts describe observed public sources, not the entire labor market. Disabled and blocked "
        "sources remain visible in `sources.json`.\n",
        encoding="utf-8",
    )
    dictionary_path = output_dir / "DATA_DICTIONARY.md"
    dictionary_path.write_text(_data_dictionary(), encoding="utf-8")
    return [sources_path, attribution_path, coverage_path, dictionary_path]


def _write_manifest(output_dir: Path, files: list[Path]) -> Path:
    manifest_path = output_dir / "manifest.json"
    all_files = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path != manifest_path
    )
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "license": "ODC-BY-1.0 with source-specific restrictions",
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in all_files
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _data_dictionary() -> str:
    return """# Data dictionary

## companies

Canonical employer identity, Nepal relationship, verified organization channels, confidence, and provenance.
JSON-valued fields such as aliases and sectors are serialized as JSON strings in CSV exports.

## jobs

Active technology and adjacent jobs. `eligibility` is `eligible`, `likely`, or `unknown`; explicitly
ineligible jobs are excluded. Evidence and rule version explain the classification. Full descriptions
are intentionally excluded from public exports.

## evidence

Record-level provenance with source URL, observation timestamp, short permitted snippet, parser version,
content hash where available, confidence, and attribution.

## runs

Public ingestion-run summaries used to audit freshness and source failures. Private error details and raw
storage pointers are excluded.
"""
