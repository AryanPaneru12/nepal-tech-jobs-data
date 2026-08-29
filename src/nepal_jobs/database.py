from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from .models import Company, Evidence, Job

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id VARCHAR PRIMARY KEY,
  source_id VARCHAR,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status VARCHAR NOT NULL,
  full_snapshot BOOLEAN NOT NULL,
  fetched_count INTEGER DEFAULT 0,
  company_count INTEGER DEFAULT 0,
  job_count INTEGER DEFAULT 0,
  lead_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,
  metrics_json VARCHAR DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS source_documents (
  document_id VARCHAR PRIMARY KEY,
  run_id VARCHAR NOT NULL,
  source_id VARCHAR NOT NULL,
  url VARCHAR NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL,
  status_code INTEGER NOT NULL,
  content_type VARCHAR,
  etag VARCHAR,
  last_modified VARCHAR,
  content_sha256 VARCHAR NOT NULL,
  storage_pointer VARCHAR NOT NULL,
  redistribution VARCHAR NOT NULL,
  raw_retention_days INTEGER NOT NULL,
  parse_status VARCHAR NOT NULL DEFAULT 'parsed'
);
CREATE TABLE IF NOT EXISTS companies (
  company_id VARCHAR PRIMARY KEY,
  canonical_name VARCHAR NOT NULL,
  legal_name VARCHAR,
  aliases_json VARCHAR NOT NULL,
  domain VARCHAR,
  website VARCHAR,
  careers_url VARCHAR,
  sectors_json VARCHAR NOT NULL,
  nepal_relationship VARCHAR NOT NULL,
  country VARCHAR,
  locality VARCHAR,
  address VARCHAR,
  official_email VARCHAR,
  official_phone VARCHAR,
  profile VARCHAR,
  active BOOLEAN NOT NULL,
  confidence DOUBLE NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  primary_source_id VARCHAR NOT NULL,
  primary_source_url VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS companies_domain_idx ON companies(domain);
CREATE TABLE IF NOT EXISTS jobs (
  job_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  title VARCHAR NOT NULL,
  role_family VARCHAR NOT NULL,
  seniority VARCHAR NOT NULL,
  employment_type VARCHAR,
  workplace_type VARCHAR NOT NULL,
  location_text VARCHAR,
  candidate_location VARCHAR,
  eligibility VARCHAR NOT NULL,
  eligibility_confidence DOUBLE NOT NULL,
  eligibility_evidence VARCHAR NOT NULL,
  eligibility_explanation VARCHAR NOT NULL,
  eligibility_rule_version VARCHAR NOT NULL,
  salary_text VARCHAR,
  salary_min DOUBLE,
  salary_max DOUBLE,
  salary_currency VARCHAR,
  salary_period VARCHAR,
  skills_json VARCHAR NOT NULL,
  min_years_experience DOUBLE,
  max_years_experience DOUBLE,
  early_career_fit BOOLEAN NOT NULL,
  source_id VARCHAR NOT NULL,
  source_url VARCHAR NOT NULL,
  apply_url VARCHAR,
  public_description VARCHAR,
  posted_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  status VARCHAR NOT NULL,
  missing_runs INTEGER NOT NULL,
  fingerprint VARCHAR NOT NULL,
  attribution VARCHAR
);
CREATE INDEX IF NOT EXISTS jobs_fingerprint_idx ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id VARCHAR PRIMARY KEY,
  record_type VARCHAR NOT NULL,
  record_id VARCHAR NOT NULL,
  field_name VARCHAR NOT NULL,
  source_id VARCHAR NOT NULL,
  source_url VARCHAR NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  snippet VARCHAR,
  selector VARCHAR,
  confidence DOUBLE NOT NULL,
  content_sha256 VARCHAR,
  parser_version VARCHAR NOT NULL,
  attribution VARCHAR
);
CREATE TABLE IF NOT EXISTS review_queue (
  review_id VARCHAR PRIMARY KEY,
  kind VARCHAR NOT NULL,
  source_id VARCHAR NOT NULL,
  payload_json VARCHAR NOT NULL,
  reason VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  status VARCHAR NOT NULL DEFAULT 'pending'
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(path))
        self.connection.execute(SCHEMA_SQL)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        self.connection.execute("BEGIN")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def upsert_company(self, company: Company) -> None:
        data = company.model_dump(mode="python")
        data["aliases_json"] = json.dumps(data.pop("aliases"), ensure_ascii=False)
        data["sectors_json"] = json.dumps(data.pop("sectors"), ensure_ascii=False)
        columns = list(data)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "company_id")
        self.connection.execute(
            f"INSERT INTO companies ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(company_id) DO UPDATE SET {updates}",
            list(data.values()),
        )

    def upsert_job(self, job: Job) -> None:
        data = job.model_dump(mode="python")
        data["skills_json"] = json.dumps(data.pop("skills"), ensure_ascii=False)
        columns = list(data)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "job_id")
        self.connection.execute(
            f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(job_id) DO UPDATE SET {updates}",
            list(data.values()),
        )

    def upsert_evidence(self, evidence: Evidence) -> None:
        data = evidence.model_dump(mode="python")
        columns = list(data)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "evidence_id")
        self.connection.execute(
            f"INSERT INTO evidence ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(evidence_id) DO UPDATE SET {updates}",
            list(data.values()),
        )

    def find_company_by_domain(self, domain: str | None) -> dict[str, object] | None:
        if not domain:
            return None
        cursor = self.connection.execute("SELECT * FROM companies WHERE domain = ?", [domain])
        row = cursor.fetchone()
        return (
            dict(zip([item[0] for item in cursor.description], row, strict=True)) if row else None
        )

    def find_company_candidates(self, name: str) -> list[dict[str, object]]:
        first_token = name.casefold().split()[0][:50] if name.strip() else ""
        cursor = self.connection.execute(
            "SELECT * FROM companies WHERE lower(canonical_name) LIKE ? LIMIT 50",
            [f"%{first_token}%"],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def get_company(self, company_id: str) -> dict[str, object] | None:
        cursor = self.connection.execute(
            "SELECT * FROM companies WHERE company_id = ?", [company_id]
        )
        row = cursor.fetchone()
        return (
            dict(zip([item[0] for item in cursor.description], row, strict=True)) if row else None
        )

    def find_job_by_fingerprint(self, fingerprint: str) -> dict[str, object] | None:
        cursor = self.connection.execute(
            "SELECT * FROM jobs WHERE fingerprint = ? ORDER BY first_seen_at LIMIT 1", [fingerprint]
        )
        row = cursor.fetchone()
        return (
            dict(zip([item[0] for item in cursor.description], row, strict=True)) if row else None
        )

    def bootstrap_from_public_exports(self, current_dir: Path) -> bool:
        """Restore safe lifecycle state when CI starts without the private working database."""
        if self.connection.execute("SELECT count(*) FROM companies").fetchone()[0]:
            return False
        required = {name: current_dir / f"{name}.csv" for name in ("companies", "jobs", "evidence")}
        if not all(path.exists() for path in required.values()):
            return False
        with self.transaction():
            for table, path in required.items():
                escaped = str(path.resolve()).replace("'", "''")
                self.connection.execute(
                    f"INSERT INTO {table} BY NAME "
                    f"SELECT * FROM read_csv('{escaped}', header=true, all_varchar=true)"
                )
        return True
