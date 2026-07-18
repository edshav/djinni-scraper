from djinni_scraper.models import JobPosting, job_id_from_url


def test_job_id_from_url_extracts_integer():
    url = "https://djinni.co/jobs/837890-senior-full-stack-or-integration-engineer-go-/"
    assert job_id_from_url(url) == 837890


def test_job_id_from_url_returns_none_without_id():
    assert job_id_from_url("https://djinni.co/jobs/") is None
    assert job_id_from_url("") is None


def test_job_posting_optional_fields_default_none():
    p = JobPosting(url="https://djinni.co/jobs/1-x/", id=1)
    assert p.title is None
    assert p.salary is None
    assert p.description is None
