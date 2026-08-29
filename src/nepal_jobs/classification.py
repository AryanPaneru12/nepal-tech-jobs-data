from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import normalize_text
from .models import Eligibility, EligibilityAssessment, WorkplaceType

ROLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "ai_data",
        (
            "machine learning",
            "artificial intelligence",
            "data scientist",
            "data engineer",
            "ml engineer",
            "nlp",
            "computer vision",
            "analytics engineer",
            "bi engineer",
        ),
    ),
    (
        "security",
        (
            "cybersecurity",
            "cyber security",
            "security engineer",
            "soc analyst",
            "penetration tester",
            "appsec",
            "infosec",
        ),
    ),
    (
        "devops_cloud",
        (
            "devops",
            "site reliability",
            "sre",
            "cloud engineer",
            "platform engineer",
            "kubernetes",
            "infrastructure engineer",
        ),
    ),
    (
        "quality_assurance",
        (
            "quality assurance",
            "qa engineer",
            "test engineer",
            "sdet",
            "automation tester",
            "software tester",
        ),
    ),
    (
        "it_support",
        (
            "it support",
            "help desk",
            "helpdesk",
            "system administrator",
            "network engineer",
            "database administrator",
            "technical support",
        ),
    ),
    (
        "product",
        (
            "product manager",
            "product owner",
            "business analyst",
            "technical program",
            "technical project",
        ),
    ),
    (
        "technical_design",
        (
            "ux designer",
            "ui designer",
            "product designer",
            "ux researcher",
            "technical writer",
            "game designer",
        ),
    ),
    (
        "technical_management",
        (
            "engineering manager",
            "head of engineering",
            "cto",
            "vp engineering",
            "technical lead",
            "tech lead",
        ),
    ),
    (
        "software_engineering",
        (
            "software",
            "developer",
            "engineer",
            "frontend",
            "front end",
            "backend",
            "back end",
            "fullstack",
            "full stack",
            "mobile",
            "android",
            "ios",
            "web3",
            "blockchain",
            "embedded",
            "firmware",
        ),
    ),
]

SKILL_RULES = {
    "python": ("python",),
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "react": ("react", "reactjs", "react.js"),
    "node.js": ("node", "nodejs", "node.js"),
    "java": ("java",),
    "c#": ("c#", ".net", "dotnet"),
    "go": ("golang", "go developer", "go engineer"),
    "rust": ("rust",),
    "sql": ("sql", "postgres", "postgresql", "mysql", "duckdb"),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure",),
    "gcp": ("gcp", "google cloud"),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "pytorch": ("pytorch",),
    "tensorflow": ("tensorflow",),
    "llm": ("large language model", "llm", "generative ai"),
}

SENIORITY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("intern", ("intern", "internship", "trainee")),
    ("entry", ("entry level", "entry-level", "new grad", "graduate", "junior", "associate")),
    ("executive", ("chief technology", "cto", "vice president", "vp engineering", "head of")),
    ("lead", ("principal", "staff", "lead", "architect")),
    ("senior", ("senior", "sr.", "sr ")),
    ("mid", ("mid level", "mid-level", "intermediate")),
]

INELIGIBLE_COUNTRY_PATTERNS = (
    r"\b(?:us|u\.s\.|united states) only\b",
    r"\bmust (?:be|reside|live) in (?:the )?(?:us|united states|canada|uk|united kingdom|eu|european union)\b",
    r"\bremote (?:within|in) (?:the )?(?:us|united states|canada|uk|united kingdom)\b",
    r"\b(?:us|canada|uk|eu) residents? only\b",
    r"\bnot available in nepal\b",
)
ELIGIBLE_PATTERNS = (
    r"\bnepal\b",
    r"\bworldwide\b",
    r"\banywhere in the world\b",
    r"\bwork from anywhere\b",
    r"\bglobal remote\b",
    r"\basia(?:[- ]pacific| pacific)?\b",
    r"\bsouth asia\b",
)
LIKELY_PATTERNS = (
    r"\banywhere\b",
    r"\bremote\b",
    r"\bdistributed team\b",
    r"\basynchronous\b",
    r"\bcontractor\b",
)


def classify_role(title: str, description: str | None = None) -> str:
    text = normalize_text(f"{title} {description or ''}")
    for family, keywords in ROLE_RULES:
        if any(_has_keyword(text, keyword) for keyword in keywords):
            return family
    return "other"


def extract_skills(title: str, description: str | None, supplied: list[str]) -> list[str]:
    text = normalize_text(f"{title} {description or ''}")
    found = {normalize_text(skill) for skill in supplied if skill}
    for canonical, keywords in SKILL_RULES.items():
        if any(_has_keyword(text, keyword) for keyword in keywords):
            found.add(canonical)
    return sorted(found)


def classify_seniority(title: str, description: str | None = None) -> str:
    text = normalize_text(f"{title} {description or ''}")
    for seniority, keywords in SENIORITY_RULES:
        if any(_has_keyword(text, keyword) for keyword in keywords):
            return seniority
    return "unspecified"


def extract_experience(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    normalized = normalize_text(text)
    ranges = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\+?\s*years?", normalized)
    if ranges:
        return float(ranges.group(1)), float(ranges.group(2))
    minimum = re.search(r"(?:minimum|min\.?|at least)\s*(\d+(?:\.\d+)?)\+?\s*years?", normalized)
    if minimum:
        return float(minimum.group(1)), None
    plus = re.search(r"(\d+(?:\.\d+)?)\+\s*years?", normalized)
    if plus:
        return float(plus.group(1)), None
    exact = re.search(r"(\d+(?:\.\d+)?)\s*years? (?:of )?experience", normalized)
    return (float(exact.group(1)), float(exact.group(1))) if exact else (None, None)


@dataclass(frozen=True, slots=True)
class Salary:
    minimum: float | None = None
    maximum: float | None = None
    currency: str | None = None
    period: str | None = None


def parse_salary(value: str | None) -> Salary:
    if not value:
        return Salary()
    normalized = value.replace(",", "")
    currency_match = re.search(r"\b(USD|NPR|EUR|GBP|INR|AUD|CAD)\b|([$€£])", normalized, re.I)
    currency = None
    if currency_match:
        currency = (
            currency_match.group(1).upper()
            if currency_match.group(1)
            else {"$": "USD", "€": "EUR", "£": "GBP"}[currency_match.group(2)]
        )
    values = [
        float(number) * (1000 if suffix.lower() == "k" else 1)
        for number, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([kK]?)", normalized)
    ]
    period = next(
        (
            period
            for period in ("hour", "month", "year")
            if re.search(rf"(?:/|per\s+){period}|annual", normalized, re.I)
        ),
        None,
    )
    return Salary(
        values[0] if values else None, values[1] if len(values) > 1 else None, currency, period
    )


def assess_nepal_eligibility(
    *,
    workplace_type: WorkplaceType,
    location_text: str | None,
    candidate_location: str | None,
    description: str | None,
) -> EligibilityAssessment:
    evidence = " | ".join(filter(None, (candidate_location, location_text, description or "")))[
        :1000
    ]
    normalized = normalize_text(evidence)
    for pattern in INELIGIBLE_COUNTRY_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return EligibilityAssessment(
                status=Eligibility.INELIGIBLE,
                confidence=0.98,
                evidence=match.group(0),
                explanation="The posting explicitly restricts applicants to a region that excludes Nepal.",
            )
    for pattern in ELIGIBLE_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return EligibilityAssessment(
                status=Eligibility.ELIGIBLE,
                confidence=0.95,
                evidence=match.group(0),
                explanation="The posting explicitly names Nepal or a geography that includes Nepal.",
            )
    if workplace_type == WorkplaceType.ONSITE:
        return EligibilityAssessment(
            status=Eligibility.INELIGIBLE,
            confidence=0.9,
            evidence=location_text or "onsite",
            explanation="The role is onsite outside the Nepal-relevant employer track.",
        )
    for pattern in LIKELY_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return EligibilityAssessment(
                status=Eligibility.LIKELY,
                confidence=0.65,
                evidence=match.group(0),
                explanation="The posting is remote but does not state a country restriction that excludes Nepal.",
            )
    return EligibilityAssessment(
        status=Eligibility.UNKNOWN,
        confidence=0.35,
        evidence=(candidate_location or location_text or "No geographic evidence")[:300],
        explanation="The posting does not provide enough geographic evidence to determine Nepal eligibility.",
    )


def is_early_career(seniority: str, minimum_years: float | None) -> bool:
    return seniority in {"intern", "entry"} or (minimum_years is not None and minimum_years <= 2)


def _has_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None
