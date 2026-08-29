from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class NepalRelationship(StrEnum):
    BASED = "based"
    OPERATES = "operates"
    HIRES = "hires"
    UNKNOWN = "unknown"


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    INELIGIBLE = "ineligible"


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class Redistribution(StrEnum):
    FACTS_ONLY = "facts_only"
    ATTRIBUTED = "attributed"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    name: str
    owner: str
    kind: str
    connector: str
    base_url: HttpUrl | None = None
    terms_url: HttpUrl | None = None
    access_mode: Literal["api", "feed", "html", "search", "manual", "blocked"]
    enabled: bool = True
    blocked_reason: str | None = None
    obey_robots: bool = True
    requests_per_minute: int = Field(default=30, ge=1, le=600)
    attribution: str
    redistribution: Redistribution = Redistribution.FACTS_ONLY
    raw_retention_days: int = Field(default=90, ge=0, le=3650)
    refresh: Literal["weekly", "daily", "manual"] = "weekly"
    full_snapshot: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("blocked_reason")
    @classmethod
    def blocked_sources_need_reason(cls, value: str | None, info: Any) -> str | None:
        if info.data.get("access_mode") == "blocked" and not value:
            raise ValueError("blocked sources require blocked_reason")
        return value


class CompanyCandidate(BaseModel):
    source_id: str
    source_url: str
    external_id: str | None = None
    name: str
    legal_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    website: str | None = None
    careers_url: str | None = None
    sectors: list[str] = Field(default_factory=list)
    country: str | None = None
    locality: str | None = None
    address: str | None = None
    nepal_relationship: NepalRelationship = NepalRelationship.UNKNOWN
    email: str | None = None
    phone: str | None = None
    profile: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    confidence: float = Field(default=0.6, ge=0, le=1)


class JobCandidate(BaseModel):
    source_id: str
    source_url: str
    external_id: str | None = None
    company_name: str
    company_website: str | None = None
    title: str
    description: str | None = None
    apply_url: str | None = None
    location_text: str | None = None
    candidate_location: str | None = None
    employment_type: str | None = None
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    salary_text: str | None = None
    skills: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    explicitly_closed: bool = False
    description_public: bool = False
    attribution: str | None = None


class DiscoveryLead(BaseModel):
    source_id: str
    source_url: str
    external_id: str | None = None
    title: str | None = None
    candidate_url: str | None = None
    query: str
    observed_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class CollectionBatch(BaseModel):
    companies: list[CompanyCandidate] = Field(default_factory=list)
    jobs: list[JobCandidate] = Field(default_factory=list)
    leads: list[DiscoveryLead] = Field(default_factory=list)
    documents: list[FetchedDocument] = Field(default_factory=list)
    full_snapshot: bool = True


class FetchedDocument(BaseModel):
    source_id: str
    url: str
    fetched_at: datetime
    status_code: int
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content: bytes = Field(exclude=True)


class Company(BaseModel):
    company_id: str
    canonical_name: str
    legal_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    website: str | None = None
    careers_url: str | None = None
    sectors: list[str] = Field(default_factory=list)
    nepal_relationship: NepalRelationship
    country: str | None = None
    locality: str | None = None
    address: str | None = None
    official_email: str | None = None
    official_phone: str | None = None
    profile: str | None = None
    active: bool = True
    confidence: float = Field(ge=0, le=1)
    first_seen_at: datetime
    last_seen_at: datetime
    primary_source_id: str
    primary_source_url: str


class EligibilityAssessment(BaseModel):
    status: Eligibility
    confidence: float = Field(ge=0, le=1)
    evidence: str
    explanation: str
    rule_version: str = "eligibility-v1"


class Job(BaseModel):
    job_id: str
    company_id: str
    title: str
    role_family: str
    seniority: str
    employment_type: str | None = None
    workplace_type: WorkplaceType
    location_text: str | None = None
    candidate_location: str | None = None
    eligibility: Eligibility
    eligibility_confidence: float = Field(ge=0, le=1)
    eligibility_evidence: str
    eligibility_explanation: str
    eligibility_rule_version: str
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    skills: list[str] = Field(default_factory=list)
    min_years_experience: float | None = None
    max_years_experience: float | None = None
    early_career_fit: bool = False
    source_id: str
    source_url: str
    apply_url: str | None = None
    public_description: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    status: Literal["active", "closed"] = "active"
    missing_runs: int = 0
    fingerprint: str
    attribution: str | None = None


class Evidence(BaseModel):
    evidence_id: str
    record_type: Literal["company", "job"]
    record_id: str
    field_name: str
    source_id: str
    source_url: str
    observed_at: datetime
    snippet: str | None = Field(default=None, max_length=500)
    selector: str | None = None
    confidence: float = Field(ge=0, le=1)
    content_sha256: str | None = None
    parser_version: str = "0.1.0"
    attribution: str | None = None


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    record_type: str | None = None
    record_id: str | None = None


class ValidationReport(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, int | float | str] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors
