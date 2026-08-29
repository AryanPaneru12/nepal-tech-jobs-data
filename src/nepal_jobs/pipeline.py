from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from .archive import ArchiveStore, LocalArchiveStore, S3ArchiveStore
from .classification import (
    assess_nepal_eligibility,
    classify_role,
    classify_seniority,
    extract_experience,
    extract_skills,
    is_early_career,
    parse_salary,
)
from .collectors import create_collector
from .database import Database
from .ids import canonical_url, normalize_text, stable_id
from .models import (
    CollectionBatch,
    CompanyCandidate,
    Eligibility,
    Evidence,
    Job,
    JobCandidate,
    NepalRelationship,
    SourceDefinition,
)
from .normalization import clean_text, normalize_employment_type
from .progress import ProgressCallback
from .resolution import CompanyResolver
from .settings import Settings
from .source_catalog import SourceCatalog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    source_id: str
    companies: int
    jobs: int
    leads: int
    documents: int
    skipped_non_tech: int = 0
    dry_run: bool = False


class WeeklyRunError(RuntimeError):
    def __init__(self, results: list[RunResult], failures: dict[str, str]):
        self.results = results
        self.failures = failures
        super().__init__(f"{len(failures)} weekly source(s) failed: {', '.join(failures)}")


class Pipeline:
    def __init__(self, settings: Settings, progress: ProgressCallback | None = None):
        self.settings = settings
        self.progress = progress
        self.settings.ensure_runtime_dirs()
        self.catalog = SourceCatalog(settings.source_dir)

    def run_source(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
        resume: bool = False,
        run_id: str | None = None,
        discovery: bool = False,
    ) -> RunResult:
        source = self.catalog.get(source_id)
        if not source.enabled:
            reason = (
                source.blocked_reason or "source is disabled pending configuration or policy review"
            )
            raise RuntimeError(f"source {source.id!r} is disabled: {reason}")
        deterministic_run_id = run_id or weekly_run_id(source.id)
        self._emit(
            "source_started",
            source=source.id,
            run_id=deterministic_run_id,
            connector=source.connector,
            dry_run=dry_run,
        )
        if dry_run:
            batch = self._collect_batch(source, discovery)
            self._emit(
                "dry_run_completed",
                source=source.id,
                documents=len(batch.documents),
                companies=len(batch.companies),
                jobs=len(batch.jobs),
                leads=len(batch.leads),
            )
            return RunResult(
                deterministic_run_id,
                source.id,
                len(batch.companies),
                len(batch.jobs),
                len(batch.leads),
                len(batch.documents),
                dry_run=True,
            )
        with Database(self.settings.db_path) as database:
            database.bootstrap_from_public_exports(self.settings.data_dir / "current")
            if resume and self._completed(database, deterministic_run_id):
                self._emit("source_resumed", source=source.id, run_id=deterministic_run_id)
                return self._existing_result(database, deterministic_run_id, source.id)
            self._start_run(database, deterministic_run_id, source)
            try:
                batch = self._collect_batch(source, discovery)
                result = self._persist(database, source, deterministic_run_id, batch)
                self._finish_run(database, result, "completed")
                self._emit(
                    "source_completed",
                    source=source.id,
                    run_id=deterministic_run_id,
                    companies=result.companies,
                    jobs=result.jobs,
                    skipped_non_tech=result.skipped_non_tech,
                )
                return result
            except BaseException as exc:
                self._fail_run(database, deterministic_run_id, exc)
                self._emit(
                    "source_failed",
                    source=source.id,
                    run_id=deterministic_run_id,
                    error=type(exc).__name__,
                    message=str(exc)[:500],
                )
                raise

    def _collect_batch(self, source: SourceDefinition, discovery: bool) -> CollectionBatch:
        collector = create_collector(source, self.settings)
        from .http import SafeHttpClient

        self._emit("collection_started", source=source.id, connector=source.connector)
        with SafeHttpClient(user_agent=self.settings.user_agent, progress=self.progress) as client:
            batch = (
                collector.discover(client, source)
                if discovery
                else collector.collect(client, source)
            )
        self._emit(
            "collection_completed",
            source=source.id,
            documents=len(batch.documents),
            companies=len(batch.companies),
            jobs=len(batch.jobs),
            leads=len(batch.leads),
        )
        return batch

    def run_weekly(self, *, dry_run: bool = False, resume: bool = True) -> list[RunResult]:
        results: list[RunResult] = []
        failures: dict[str, str] = {}
        enabled_sources = [
            source
            for source in self.catalog.load().values()
            if source.enabled and source.refresh in {"weekly", "daily"}
        ]
        self._emit("weekly_started", sources=len(enabled_sources), dry_run=dry_run)
        for index, source in enumerate(enabled_sources, start=1):
            self._emit(
                "weekly_source_started",
                source=source.id,
                position=index,
                total=len(enabled_sources),
            )
            try:
                results.append(self.run_source(source.id, dry_run=dry_run, resume=resume))
            except Exception as exc:
                failures[source.id] = str(exc)
                logger.exception("source_failed", source_id=source.id)
        if failures:
            self._emit("weekly_failed", completed=len(results), failed=len(failures))
            raise WeeklyRunError(results, failures)
        self._emit("weekly_completed", completed=len(results), failed=0)
        return results

    def _persist(
        self,
        database: Database,
        source: SourceDefinition,
        run_id: str,
        batch: CollectionBatch,
    ) -> RunResult:
        archive = self._archive_store()
        content_hashes: dict[str, str] = {}
        resolver = CompanyResolver(database)
        skipped_non_tech = 0
        observed_job_ids: set[str] = set()

        with database.transaction() as connection:
            self._emit("archive_started", source=source.id, total=len(batch.documents))
            for index, document in enumerate(batch.documents, start=1):
                archived = archive.put(document, source, run_id)
                document_id = stable_id(
                    "document", source.id, document.url, archived.content_sha256
                )
                connection.execute(
                    """INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'parsed')
                       ON CONFLICT(document_id) DO UPDATE SET fetched_at=excluded.fetched_at,
                       storage_pointer=excluded.storage_pointer""",
                    [
                        document_id,
                        run_id,
                        source.id,
                        document.url,
                        document.fetched_at,
                        document.status_code,
                        document.content_type,
                        document.etag,
                        document.last_modified,
                        archived.content_sha256,
                        archived.pointer,
                        source.redistribution.value,
                        source.raw_retention_days,
                    ],
                )
                content_hashes[document.url] = archived.content_sha256
                if _report_progress(index, len(batch.documents), 10):
                    self._emit(
                        "archive_progress",
                        source=source.id,
                        completed=index,
                        total=len(batch.documents),
                    )

            self._emit("companies_started", source=source.id, total=len(batch.companies))
            for index, candidate in enumerate(batch.companies, start=1):
                company, needs_review = resolver.resolve(candidate)
                database.upsert_company(company)
                database.upsert_evidence(
                    _company_evidence(company, candidate, source, content_hashes)
                )
                if needs_review:
                    self._enqueue_review(
                        database,
                        "company_merge",
                        source.id,
                        candidate.model_dump(mode="json"),
                        "A similarly named company exists but the safe auto-merge threshold was not met.",
                    )
                if _report_progress(index, len(batch.companies), 100):
                    self._emit(
                        "companies_progress",
                        source=source.id,
                        completed=index,
                        total=len(batch.companies),
                    )

            self._emit("jobs_started", source=source.id, total=len(batch.jobs))
            for index, candidate in enumerate(batch.jobs, start=1):
                role_family = classify_role(candidate.title, candidate.description)
                if role_family == "other":
                    skipped_non_tech += 1
                    if _report_progress(index, len(batch.jobs), 100):
                        self._emit(
                            "jobs_progress",
                            source=source.id,
                            processed=index,
                            total=len(batch.jobs),
                            retained=len(observed_job_ids),
                            skipped_non_tech=skipped_non_tech,
                        )
                    continue
                job = self._normalize_job(database, resolver, candidate, role_family, source)
                if job.eligibility == Eligibility.INELIGIBLE:
                    self._enqueue_review(
                        database,
                        "ineligible_job_audit",
                        source.id,
                        candidate.model_dump(mode="json", exclude={"description"}),
                        job.eligibility_explanation,
                    )
                    if _report_progress(index, len(batch.jobs), 100):
                        self._emit(
                            "jobs_progress",
                            source=source.id,
                            processed=index,
                            total=len(batch.jobs),
                            retained=len(observed_job_ids),
                            skipped_non_tech=skipped_non_tech,
                        )
                    continue
                database.upsert_job(job)
                observed_job_ids.add(job.job_id)
                database.upsert_evidence(_job_evidence(job, candidate, source, content_hashes))
                if _report_progress(index, len(batch.jobs), 100):
                    self._emit(
                        "jobs_progress",
                        source=source.id,
                        processed=index,
                        total=len(batch.jobs),
                        retained=len(observed_job_ids),
                        skipped_non_tech=skipped_non_tech,
                    )

            self._emit("leads_started", source=source.id, total=len(batch.leads))
            for lead in batch.leads:
                self._enqueue_review(
                    database,
                    "discovery_lead",
                    source.id,
                    lead.model_dump(mode="json"),
                    "Discovery results require independent first-party verification.",
                )

            if batch.full_snapshot:
                self._emit(
                    "lifecycle_started",
                    source=source.id,
                    observed_jobs=len(observed_job_ids),
                )
                self._apply_missing_job_lifecycle(database, source.id, observed_job_ids)

        self._emit(
            "persistence_completed",
            source=source.id,
            retained_jobs=len(observed_job_ids),
            skipped_non_tech=skipped_non_tech,
        )

        return RunResult(
            run_id,
            source.id,
            len(batch.companies),
            len(observed_job_ids),
            len(batch.leads),
            len(batch.documents),
            skipped_non_tech,
        )

    def _normalize_job(
        self,
        database: Database,
        resolver: CompanyResolver,
        candidate: JobCandidate,
        role_family: str,
        source: SourceDefinition,
    ) -> Job:
        eligibility = assess_nepal_eligibility(
            workplace_type=candidate.workplace_type,
            location_text=candidate.location_text,
            candidate_location=candidate.candidate_location,
            description=candidate.description,
        )
        company_candidate = CompanyCandidate(
            source_id=candidate.source_id,
            source_url=candidate.source_url,
            name=candidate.company_name,
            website=candidate.company_website,
            sectors=["technology_employer"],
            nepal_relationship=NepalRelationship.HIRES
            if eligibility.status in {Eligibility.ELIGIBLE, Eligibility.LIKELY}
            else NepalRelationship.UNKNOWN,
            confidence=0.75,
            observed_at=candidate.observed_at,
        )
        company, needs_review = resolver.resolve(company_candidate)
        database.upsert_company(company)
        database.upsert_evidence(_company_evidence(company, company_candidate, source, {}))
        if needs_review:
            self._enqueue_review(
                database,
                "company_merge",
                source.id,
                company_candidate.model_dump(mode="json"),
                "Job employer may duplicate an existing company.",
            )

        title = clean_text(candidate.title, max_length=300) or candidate.title
        source_url = canonical_url(candidate.source_url) or candidate.source_url
        apply_url = canonical_url(candidate.apply_url)
        fingerprint = stable_id(
            "job-fingerprint",
            company.company_id,
            normalize_text(title),
            normalize_text(candidate.location_text),
        )
        duplicate = database.find_job_by_fingerprint(fingerprint)
        job_id = (
            str(duplicate["job_id"])
            if duplicate
            else stable_id("job", source.id, candidate.external_id or apply_url or source_url)
        )
        first_seen = duplicate["first_seen_at"] if duplicate else candidate.observed_at
        chosen_source = source.id
        chosen_url = source_url
        chosen_attribution = candidate.attribution
        if duplicate and _source_priority(str(duplicate["source_id"])) > _source_priority(
            source.id
        ):
            chosen_source = str(duplicate["source_id"])
            chosen_url = str(duplicate["source_url"])
            chosen_attribution = (
                str(duplicate["attribution"]) if duplicate.get("attribution") else None
            )

        seniority = classify_seniority(title, candidate.description)
        min_years, max_years = extract_experience(candidate.description)
        salary = parse_salary(candidate.salary_text)
        public_description = (
            clean_text(candidate.description, max_length=2000)
            if candidate.description_public
            else None
        )
        return Job(
            job_id=job_id,
            company_id=company.company_id,
            title=title,
            role_family=role_family,
            seniority=seniority,
            employment_type=normalize_employment_type(candidate.employment_type),
            workplace_type=candidate.workplace_type,
            location_text=clean_text(candidate.location_text, max_length=300),
            candidate_location=clean_text(candidate.candidate_location, max_length=300),
            eligibility=eligibility.status,
            eligibility_confidence=eligibility.confidence,
            eligibility_evidence=clean_text(eligibility.evidence, max_length=500)
            or "No geographic evidence",
            eligibility_explanation=eligibility.explanation,
            eligibility_rule_version=eligibility.rule_version,
            salary_text=clean_text(candidate.salary_text, max_length=300),
            salary_min=salary.minimum,
            salary_max=salary.maximum,
            salary_currency=salary.currency,
            salary_period=salary.period,
            skills=extract_skills(title, candidate.description, candidate.skills),
            min_years_experience=min_years,
            max_years_experience=max_years,
            early_career_fit=is_early_career(seniority, min_years),
            source_id=chosen_source,
            source_url=chosen_url,
            apply_url=apply_url,
            public_description=public_description,
            posted_at=candidate.posted_at,
            expires_at=candidate.expires_at,
            first_seen_at=first_seen,
            last_seen_at=candidate.observed_at,
            status="closed" if candidate.explicitly_closed else "active",
            missing_runs=0,
            fingerprint=fingerprint,
            attribution=chosen_attribution,
        )

    def _archive_store(self) -> ArchiveStore:
        s = self.settings
        if all((s.r2_endpoint_url, s.r2_bucket, s.r2_access_key_id, s.r2_secret_access_key)):
            return S3ArchiveStore(
                endpoint_url=s.r2_endpoint_url or "",
                bucket=s.r2_bucket or "",
                access_key_id=s.r2_access_key_id or "",
                secret_access_key=s.r2_secret_access_key or "",
            )
        return LocalArchiveStore(s.raw_dir)

    @staticmethod
    def _apply_missing_job_lifecycle(
        database: Database, source_id: str, observed: set[str]
    ) -> None:
        if observed:
            placeholders = ",".join("?" for _ in observed)
            database.connection.execute(
                f"""UPDATE jobs SET missing_runs=missing_runs+1,
                    status=CASE WHEN missing_runs+1 >= 2 THEN 'closed' ELSE status END
                    WHERE source_id=? AND status='active' AND job_id NOT IN ({placeholders})""",
                [source_id, *sorted(observed)],
            )
        else:
            # An empty result is anomalous and must not silently close every job.
            return

    @staticmethod
    def _enqueue_review(
        database: Database, kind: str, source_id: str, payload: dict[str, object], reason: str
    ) -> None:
        review_id = stable_id("review", kind, source_id, json.dumps(payload, sort_keys=True))
        database.connection.execute(
            """INSERT INTO review_queue(review_id, kind, source_id, payload_json, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(review_id) DO NOTHING""",
            [
                review_id,
                kind,
                source_id,
                json.dumps(payload, ensure_ascii=False),
                reason,
                datetime.now(UTC),
            ],
        )

    @staticmethod
    def _completed(database: Database, run_id: str) -> bool:
        return bool(
            database.connection.execute(
                "SELECT 1 FROM ingestion_runs WHERE run_id=? AND status='completed'", [run_id]
            ).fetchone()
        )

    @staticmethod
    def _existing_result(database: Database, run_id: str, source_id: str) -> RunResult:
        row = database.connection.execute(
            "SELECT company_count, job_count, lead_count, fetched_count FROM ingestion_runs WHERE run_id=?",
            [run_id],
        ).fetchone()
        return RunResult(run_id, source_id, *map(int, row))

    @staticmethod
    def _start_run(database: Database, run_id: str, source: SourceDefinition) -> None:
        database.connection.execute(
            """INSERT INTO ingestion_runs(run_id, source_id, started_at, status, full_snapshot)
               VALUES (?, ?, ?, 'running', ?)
               ON CONFLICT(run_id) DO UPDATE SET started_at=excluded.started_at, status='running',
               failure_count=0""",
            [run_id, source.id, datetime.now(UTC), source.full_snapshot],
        )

    @staticmethod
    def _finish_run(database: Database, result: RunResult, status: str) -> None:
        database.connection.execute(
            """UPDATE ingestion_runs SET finished_at=?, status=?, fetched_count=?, company_count=?,
               job_count=?, lead_count=?, metrics_json=? WHERE run_id=?""",
            [
                datetime.now(UTC),
                status,
                result.documents,
                result.companies,
                result.jobs,
                result.leads,
                json.dumps({"skipped_non_tech": result.skipped_non_tech}),
                result.run_id,
            ],
        )

    @staticmethod
    def _fail_run(database: Database, run_id: str, exc: BaseException) -> None:
        database.connection.execute(
            """UPDATE ingestion_runs SET finished_at=?, status='failed', failure_count=1,
               metrics_json=? WHERE run_id=?""",
            [datetime.now(UTC), json.dumps({"error": str(exc)[:1000]}), run_id],
        )

    def _emit(self, event: str, **fields: object) -> None:
        if self.progress:
            self.progress(event, fields)


def weekly_run_id(source_id: str, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    iso = current.isocalendar()
    return stable_id("run", source_id, iso.year, iso.week)


def _company_evidence(
    company, candidate, source: SourceDefinition, hashes: dict[str, str]
) -> Evidence:  # type: ignore[no-untyped-def]
    return Evidence(
        evidence_id=stable_id(
            "evidence", "company", company.company_id, source.id, candidate.source_url
        ),
        record_type="company",
        record_id=company.company_id,
        field_name="record",
        source_id=source.id,
        source_url=candidate.source_url,
        observed_at=candidate.observed_at,
        snippet=clean_text(candidate.profile or candidate.name, max_length=500),
        confidence=candidate.confidence,
        content_sha256=hashes.get(candidate.source_url),
        attribution=source.attribution,
    )


def _job_evidence(
    job: Job, candidate: JobCandidate, source: SourceDefinition, hashes: dict[str, str]
) -> Evidence:
    return Evidence(
        evidence_id=stable_id("evidence", "job", job.job_id, source.id, candidate.source_url),
        record_type="job",
        record_id=job.job_id,
        field_name="record",
        source_id=source.id,
        source_url=candidate.source_url,
        observed_at=candidate.observed_at,
        snippet=clean_text(f"{candidate.title} | {candidate.location_text or ''}", max_length=500),
        confidence=job.eligibility_confidence,
        content_sha256=hashes.get(candidate.source_url),
        attribution=source.attribution,
    )


def _source_priority(source_id: str) -> int:
    if source_id in {"greenhouse", "lever", "ashby"}:
        return 100
    if source_id in {"himalayas", "remoteok", "remotive"}:
        return 50
    return 75


def _report_progress(index: int, total: int, interval: int) -> bool:
    return index == total or index == 1 or index % interval == 0
