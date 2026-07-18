from pathlib import Path

import pytest

from djinni_scraper.parser import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "listing_fullstack.html"


@pytest.fixture(scope="module")
def postings():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_listing(html, base_url="https://djinni.co")


def by_id(postings, job_id):
    return next(p for p in postings if p.id == job_id)


def test_parses_all_fifteen_postings(postings):
    assert len(postings) == 15


def test_jsonld_core_fields(postings):
    p = by_id(postings, 837890)
    assert p.title == "Senior full-stack or integration engineer (Go, React) for PropTech"
    assert p.company == "Upstaff"
    assert p.salary == "$3000–5000/mo"
    assert p.experience == "5 years"
    assert p.domain == "proptech"
    assert p.posted == "2026-07-17"
    assert p.url == (
        "https://djinni.co/jobs/837890-senior-full-stack-or-integration-engineer-go-/"
    )


def test_full_description_from_jsonld(postings):
    p = by_id(postings, 837890)
    assert p.description.startswith("We are looking for experienced software")
    assert "SAP" in p.description
    assert len(p.description) > 2000


def test_missing_salary_is_none(postings):
    # id 827322 has no baseSalary in the JSON-LD
    p = by_id(postings, 827322)
    assert p.salary is None
