import io
import zipfile

from app import certificate


def payload(recipients):
    """Helper: build a valid request body for the given recipients."""
    return {"event_name": "Python Workshop", "recipients": recipients}


GOOD = [{"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "Ben Lee", "email": "ben@example.com"}]


# ---- Creating a job ----
def test_create_job(client):
    """A valid request returns 202, a job_id and the right total."""
    r = client.post("/jobs", json=payload(GOOD))
    assert r.status_code == 202
    assert r.json()["total"] == 2
    assert "job_id" in r.json()


# ---- Input validation ----
def test_empty_recipient_list_rejected(client):
    """An empty recipient list is rejected with 422."""
    assert client.post("/jobs", json=payload([])).status_code == 422


def test_missing_event_name_rejected(client):
    """A request without event_name is rejected with 422."""
    assert client.post("/jobs", json={"recipients": GOOD}).status_code == 422


def test_invalid_recipient_marked_failed_others_succeed(client):
    """Bad recipients are marked failed with an error, while valid ones are still generated."""
    recipients = GOOD + [{"name": "", "email": "x@example.com"},
                         {"name": "No Email"},
                         {"name": "Bad Mail", "email": "not-an-email"}]
    job_id = client.post("/jobs", json=payload(recipients)).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["completed"] == 2
    assert job["failed"] == 3
    assert job["status"] == "completed_with_errors"
    failed = [c for c in job["certificates"] if c["status"] == "failed"]
    assert all(c["error"] for c in failed)


def test_all_invalid_job_fails(client):
    """If every recipient is invalid, the job status is failed."""
    job_id = client.post("/jobs", json=payload([{"name": ""}])).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "failed"


# ---- Certificate generation ----
def test_certificate_is_generated_pdf(client, tmp_path):
    """generate_pdf creates a real PDF file."""
    path = str(tmp_path / "c.pdf")
    certificate.generate_pdf("Asha Rao", "Python Workshop", "2026-01-01", path)
    assert open(path, "rb").read(4) == b"%PDF"


# ---- Job status / progress ----
def test_job_status_and_progress(client):
    """A finished job shows completed status, correct counts and 100% progress."""
    job_id = client.post("/jobs", json=payload(GOOD)).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["total"] == 2 and job["completed"] == 2 and job["failed"] == 0
    assert job["progress_percent"] == 100


def test_unknown_job_404(client):
    """Asking for a job that doesn't exist returns 404."""
    assert client.get("/jobs/9999").status_code == 404


# ---- Individual certificate failure ----
def test_one_generation_failure_does_not_stop_others(client, monkeypatch):
    """Simulate a crash while generating one certificate; the others must still succeed and the error must be recorded."""
    real = certificate.generate_pdf

    def flaky(name, *args):
        if name == "Boom":
            raise RuntimeError("render failed")
        return real(name, *args)

    monkeypatch.setattr(certificate, "generate_pdf", flaky)
    recipients = [{"name": "Ok One", "email": "a@example.com"},
                  {"name": "Boom", "email": "b@example.com"},
                  {"name": "Ok Two", "email": "c@example.com"}]
    job_id = client.post("/jobs", json=payload(recipients)).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed_with_errors"
    assert job["completed"] == 2 and job["failed"] == 1
    bad = next(c for c in job["certificates"] if c["name"] == "Boom")
    assert "render failed" in bad["error"]


# ---- Retrieving certificates ----
def test_download_single_certificate(client):
    """A completed certificate can be downloaded as a PDF."""
    job_id = client.post("/jobs", json=payload(GOOD)).json()["job_id"]
    cert = client.get(f"/jobs/{job_id}").json()["certificates"][0]
    r = client.get(cert["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_download_failed_certificate_conflict(client):
    """Downloading a failed certificate returns 409."""
    job_id = client.post("/jobs", json=payload(GOOD + [{"name": ""}])).json()["job_id"]
    failed = next(c for c in client.get(f"/jobs/{job_id}").json()["certificates"]
                  if c["status"] == "failed")
    assert client.get(f"/jobs/{job_id}/certificates/{failed['id']}").status_code == 409


def test_download_zip(client):
    """The ZIP contains only the successfully generated certificates."""
    job_id = client.post("/jobs", json=payload(GOOD + [{"name": ""}])).json()["job_id"]
    r = client.get(f"/jobs/{job_id}/download")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(z.namelist()) == 2  # only the successful ones


# ---- Frontend ----
def test_frontend_page_served(client):
    """The home page returns the HTML frontend."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Bulk Certificate Generator" in r.text
