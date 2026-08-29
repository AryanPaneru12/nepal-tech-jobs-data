from nepal_jobs.classification import (
    assess_nepal_eligibility,
    classify_role,
    classify_seniority,
    extract_experience,
    extract_skills,
    parse_salary,
)
from nepal_jobs.models import Eligibility, WorkplaceType


def test_role_and_skills() -> None:
    assert classify_role("Machine Learning Engineer") == "ai_data"
    assert extract_skills("Python Engineer", "Use AWS, Docker and PostgreSQL", []) == [
        "aws",
        "docker",
        "python",
        "sql",
    ]


def test_seniority_and_experience() -> None:
    assert classify_seniority("Junior Software Developer") == "entry"
    assert extract_experience("Requires 1-2 years experience") == (1.0, 2.0)


def test_salary_parser() -> None:
    salary = parse_salary("USD 40k - 60k per year")
    assert (salary.minimum, salary.maximum, salary.currency, salary.period) == (
        40_000,
        60_000,
        "USD",
        "year",
    )


def test_eligibility_prefers_explicit_restriction() -> None:
    assessment = assess_nepal_eligibility(
        workplace_type=WorkplaceType.REMOTE,
        location_text="Remote",
        candidate_location="US only",
        description="Distributed team",
    )
    assert assessment.status == Eligibility.INELIGIBLE


def test_worldwide_is_eligible_and_remote_only_is_likely() -> None:
    worldwide = assess_nepal_eligibility(
        workplace_type=WorkplaceType.REMOTE,
        location_text="Worldwide",
        candidate_location=None,
        description=None,
    )
    remote = assess_nepal_eligibility(
        workplace_type=WorkplaceType.REMOTE,
        location_text="Remote",
        candidate_location=None,
        description=None,
    )
    assert worldwide.status == Eligibility.ELIGIBLE
    assert remote.status == Eligibility.LIKELY
