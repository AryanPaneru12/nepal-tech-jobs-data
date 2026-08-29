from __future__ import annotations

import json

from rapidfuzz.fuzz import token_set_ratio

from .database import Database
from .ids import canonical_url, domain_from_url, normalize_text, stable_id
from .models import Company, CompanyCandidate
from .normalization import clean_text


class CompanyResolver:
    AUTO_MERGE_NAME_SCORE = 96
    REVIEW_NAME_SCORE = 84

    def __init__(self, database: Database):
        self.database = database

    def resolve(self, candidate: CompanyCandidate) -> tuple[Company, bool]:
        website = canonical_url(candidate.website)
        domain = domain_from_url(website)
        existing = self.database.find_company_by_domain(domain)
        if existing:
            return self._merge(existing, candidate, website, domain), False

        best: tuple[float, dict[str, object]] | None = None
        for row in self.database.find_company_candidates(candidate.name):
            score = token_set_ratio(
                normalize_text(candidate.name), normalize_text(str(row["canonical_name"]))
            )
            if best is None or score > best[0]:
                best = (score, row)
        if best and best[0] >= self.AUTO_MERGE_NAME_SCORE:
            return self._merge(best[1], candidate, website, domain), False

        needs_review = bool(best and best[0] >= self.REVIEW_NAME_SCORE)
        company_id = stable_id(
            "company", domain or candidate.external_id or candidate.name, candidate.country or ""
        )
        return Company(
            company_id=company_id,
            canonical_name=clean_text(candidate.name, max_length=300) or candidate.name,
            legal_name=clean_text(candidate.legal_name, max_length=300),
            aliases=sorted({alias for alias in candidate.aliases if alias}),
            domain=domain,
            website=website,
            careers_url=canonical_url(candidate.careers_url),
            sectors=sorted(set(candidate.sectors)),
            nepal_relationship=candidate.nepal_relationship,
            country=clean_text(candidate.country, max_length=100),
            locality=clean_text(candidate.locality, max_length=200),
            address=clean_text(candidate.address, max_length=500),
            official_email=_organization_email(candidate.email, domain),
            official_phone=clean_text(candidate.phone, max_length=100),
            profile=clean_text(candidate.profile, max_length=1000),
            confidence=candidate.confidence,
            first_seen_at=candidate.observed_at,
            last_seen_at=candidate.observed_at,
            primary_source_id=candidate.source_id,
            primary_source_url=candidate.source_url,
        ), needs_review

    def _merge(
        self,
        existing: dict[str, object],
        candidate: CompanyCandidate,
        website: str | None,
        domain: str | None,
    ) -> Company:
        aliases = set(json.loads(str(existing["aliases_json"])))
        if normalize_text(str(existing["canonical_name"])) != normalize_text(candidate.name):
            aliases.add(candidate.name)
        aliases.update(candidate.aliases)
        sectors = set(json.loads(str(existing["sectors_json"]))) | set(candidate.sectors)
        return Company(
            company_id=str(existing["company_id"]),
            canonical_name=str(existing["canonical_name"]),
            legal_name=candidate.legal_name or _optional_str(existing.get("legal_name")),
            aliases=sorted(alias for alias in aliases if alias),
            domain=domain or _optional_str(existing.get("domain")),
            website=website or _optional_str(existing.get("website")),
            careers_url=canonical_url(candidate.careers_url)
            or _optional_str(existing.get("careers_url")),
            sectors=sorted(sectors),
            nepal_relationship=candidate.nepal_relationship
            if candidate.nepal_relationship.value != "unknown"
            else str(existing["nepal_relationship"]),
            country=candidate.country or _optional_str(existing.get("country")),
            locality=candidate.locality or _optional_str(existing.get("locality")),
            address=candidate.address or _optional_str(existing.get("address")),
            official_email=_organization_email(candidate.email, domain)
            or _optional_str(existing.get("official_email")),
            official_phone=candidate.phone or _optional_str(existing.get("official_phone")),
            profile=clean_text(candidate.profile, max_length=1000)
            or _optional_str(existing.get("profile")),
            active=True,
            confidence=max(float(existing["confidence"]), candidate.confidence),
            first_seen_at=existing["first_seen_at"],
            last_seen_at=max(existing["last_seen_at"], candidate.observed_at),
            primary_source_id=str(existing["primary_source_id"]),
            primary_source_url=str(existing["primary_source_url"]),
        )


def _organization_email(value: str | None, domain: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    local, email_domain = value.strip().casefold().rsplit("@", 1)
    personal_markers = {"recruiter", "firstname", "lastname"}
    if any(marker in local for marker in personal_markers):
        return None
    if domain and not (email_domain == domain or email_domain.endswith(f".{domain}")):
        return None
    return f"{local}@{email_domain}"


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None
