from __future__ import annotations

from pathlib import Path

from .database import Database
from .models import ValidationIssue, ValidationReport
from .source_catalog import SourceCatalog


def validate_database(
    database: Database, catalog: SourceCatalog, *, release: bool = False
) -> ValidationReport:
    report = ValidationReport()
    connection = database.connection
    company_count = int(
        connection.execute("SELECT count(*) FROM companies WHERE active").fetchone()[0]
    )
    job_count = int(
        connection.execute(
            "SELECT count(*) FROM jobs WHERE status='active' AND eligibility <> 'ineligible'"
        ).fetchone()[0]
    )
    report.metrics.update(active_companies=company_count, active_jobs=job_count)

    sources = catalog.load()
    source_errors = catalog.check()
    report.errors.extend(
        ValidationIssue(severity="error", code="source_catalog", message=error)
        for error in source_errors
    )
    _require_no_rows(
        report,
        connection,
        """SELECT company_id FROM companies
           WHERE canonical_name IS NULL OR primary_source_url IS NULL OR primary_source_id IS NULL""",
        "company_required_fields",
        "Company is missing a required public field.",
        "company",
    )
    _require_no_rows(
        report,
        connection,
        """SELECT job_id FROM jobs WHERE status='active' AND
           (title IS NULL OR company_id IS NULL OR source_url IS NULL OR eligibility_evidence IS NULL)""",
        "job_required_fields",
        "Active job is missing a required public field.",
        "job",
    )
    _require_no_rows(
        report,
        connection,
        """SELECT c.company_id FROM companies c LEFT JOIN evidence e
           ON e.record_type='company' AND e.record_id=c.company_id
           WHERE c.active GROUP BY c.company_id HAVING count(e.evidence_id)=0""",
        "company_provenance",
        "Company has no evidence record.",
        "company",
    )
    _require_no_rows(
        report,
        connection,
        """SELECT j.job_id FROM jobs j LEFT JOIN evidence e
           ON e.record_type='job' AND e.record_id=j.job_id
           WHERE j.status='active' GROUP BY j.job_id HAVING count(e.evidence_id)=0""",
        "job_provenance",
        "Job has no evidence record.",
        "job",
    )
    _require_no_rows(
        report,
        connection,
        "SELECT job_id FROM jobs WHERE eligibility='ineligible' AND status='active'",
        "ineligible_active",
        "An explicitly ineligible job is marked active.",
        "job",
    )
    duplicate_jobs = int(
        connection.execute(
            "SELECT count(*) FROM (SELECT fingerprint FROM jobs WHERE status='active' GROUP BY fingerprint HAVING count(*) > 1)"
        ).fetchone()[0]
    )
    report.metrics["duplicate_job_fingerprints"] = duplicate_jobs
    if duplicate_jobs:
        report.errors.append(
            ValidationIssue(
                severity="error",
                code="duplicate_jobs",
                message=f"{duplicate_jobs} active job fingerprints are duplicated.",
            )
        )

    restricted_ids = {
        source.id
        for source in sources.values()
        if source.redistribution.value in {"restricted", "unknown"}
    }
    if restricted_ids:
        placeholders = ",".join("?" for _ in restricted_ids)
        _require_no_rows(
            report,
            connection,
            f"SELECT company_id FROM companies WHERE primary_source_id IN ({placeholders})",
            "restricted_company_source",
            "A company from a restricted or unreviewed source reached the public dataset.",
            "company",
            sorted(restricted_ids),
        )
        _require_no_rows(
            report,
            connection,
            f"SELECT job_id FROM jobs WHERE source_id IN ({placeholders})",
            "restricted_job_source",
            "A job from a restricted or unreviewed source reached the public dataset.",
            "job",
            sorted(restricted_ids),
        )

    for source_id in sources:
        successful_counts = connection.execute(
            """SELECT job_count FROM ingestion_runs
               WHERE source_id=? AND status='completed' ORDER BY finished_at DESC LIMIT 2""",
            [source_id],
        ).fetchall()
        if len(successful_counts) == 2 and successful_counts[1][0]:
            ratio = successful_counts[0][0] / successful_counts[1][0]
            if ratio < 0.5:
                report.errors.append(
                    ValidationIssue(
                        severity="error",
                        code="unexpected_source_drop",
                        message=(
                            f"{source_id} fell from {successful_counts[1][0]} to "
                            f"{successful_counts[0][0]} jobs."
                        ),
                    )
                )

    company_completeness = _company_completeness(connection)
    job_completeness = _job_completeness(connection)
    report.metrics["company_required_field_completeness"] = company_completeness
    report.metrics["job_required_field_completeness"] = job_completeness
    if company_count and company_completeness < 0.95:
        report.errors.append(_metric_error("company_completeness", company_completeness))
    if job_count and job_completeness < 0.95:
        report.errors.append(_metric_error("job_completeness", job_completeness))

    if release:
        if company_count < 500:
            report.errors.append(
                ValidationIssue(
                    severity="error",
                    code="release_company_count",
                    message=f"Release requires 500 companies; found {company_count}.",
                )
            )
        if job_count < 2000:
            report.errors.append(
                ValidationIssue(
                    severity="error",
                    code="release_job_count",
                    message=f"Release requires 2,000 active jobs; found {job_count}.",
                )
            )
    return report


def write_validation_report(report: ValidationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _require_no_rows(report, connection, query, code, message, record_type, parameters=None):  # type: ignore[no-untyped-def]
    for row in connection.execute(query, parameters or []).fetchall():
        report.errors.append(
            ValidationIssue(
                severity="error",
                code=code,
                message=message,
                record_type=record_type,
                record_id=str(row[0]),
            )
        )


def _company_completeness(connection) -> float:  # type: ignore[no-untyped-def]
    row = connection.execute(
        """SELECT count(*), sum(CASE WHEN canonical_name IS NOT NULL AND primary_source_id IS NOT NULL
           AND primary_source_url IS NOT NULL AND confidence IS NOT NULL THEN 1 ELSE 0 END)
           FROM companies WHERE active"""
    ).fetchone()
    return 1.0 if not row[0] else float(row[1]) / float(row[0])


def _job_completeness(connection) -> float:  # type: ignore[no-untyped-def]
    row = connection.execute(
        """SELECT count(*), sum(CASE WHEN title IS NOT NULL AND company_id IS NOT NULL
           AND role_family IS NOT NULL AND source_url IS NOT NULL AND eligibility IS NOT NULL
           AND last_seen_at IS NOT NULL THEN 1 ELSE 0 END)
           FROM jobs WHERE status='active' AND eligibility <> 'ineligible'"""
    ).fetchone()
    return 1.0 if not row[0] else float(row[1]) / float(row[0])


def _metric_error(code: str, value: float) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=f"Required-field completeness is {value:.1%}; minimum is 95%.",
    )
