# Bulk Certificate Generator

Backend API (FastAPI + SQLAlchemy + SQLite) that takes a list of recipients in **one request**,
generates a PDF certificate for each valid one from a single fixed template, and lets you track
progress and download the results.

## Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn app.main:app --reload
```
Interactive docs: http://127.0.0.1:8000/docs  
Config via env vars: `DATABASE_URL` (default `sqlite:///./certs.db`), `CERT_DIR` (default `./generated`).

## Test
```bash
pytest
```

## Frontend
Open http://127.0.0.1:8000/ after starting the server. Paste recipients as `name, email` lines (or load a CSV),
click **Generate certificates**, watch the progress bar, then download each PDF or the whole ZIP.
Failed rows show the reason. It is one plain HTML/JS file (`app/static/index.html`) that calls the same API below -
no build step, no framework.

## Usage (API)

**1. Submit a job** (returns immediately with `202`)
```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "event_name": "Python Workshop",
  "issued_on": "2026-10-01",
  "recipients": [
    {"name": "Asha Rao", "email": "asha@example.com"},
    {"name": "Ben Lee",  "email": "ben@example.com"},
    {"name": "",         "email": "bad"}
  ]
}'
# {"job_id": 1, "status": "pending", "total": 3}
```
`issued_on` is optional (defaults to today). Max 1000 recipients per request.

**2. Check status / progress**
```bash
curl http://127.0.0.1:8000/jobs/1
```
Returns job `status`, counts (`total`, `completed`, `failed`, `pending`), `progress_percent`, and
a per-recipient list with `status`, `error` (why it failed) and `download_url`.

Job status: `pending` → `processing` → `completed` | `completed_with_errors` | `failed`.

**3. Retrieve certificates**
```bash
curl -O -J http://127.0.0.1:8000/jobs/1/certificates/1   # one PDF
curl -O -J http://127.0.0.1:8000/jobs/1/download          # all successful ones as a ZIP
```
Downloading a failed/pending certificate returns `409`; the ZIP returns `409` while the job is still running.

## Design decisions

- **Background processing (FastAPI `BackgroundTasks`)**: a job may have up to 1000 recipients, so the
  POST just validates, stores rows and returns `202` + `job_id`. The client polls `GET /jobs/{id}`.
  I chose this over Celery/Redis to keep the project simple with no extra services. Trade-off: if the
  server restarts mid-job, the job is left unfinished (pending certs stay `pending`). For production I'd
  move `process_job` to a real queue (Celery/RQ) – only that one function would need to change.
- **Two levels of validation**:
  1. *Request level* (Pydantic): `event_name` required, 1–1000 recipients → `422` for the whole request.
  2. *Recipient level*: each recipient is validated individually (name not blank, email format). Invalid
     ones are saved as `failed` with an error message; valid ones still get generated. A request
     with only invalid recipients gives a job with status `failed`.
- **Failure isolation**: each certificate is generated in its own `try/except` and committed
  separately. One failure never stops the rest, and progress is visible while the job runs.
- **Data model**: `jobs` (1) → `certificates` (many). Each certificate stores status, error and file path.
  Counts are computed from the certificates table, so they can't get out of sync.
- **Template**: one hard-coded PDF layout drawn with `reportlab` (`app/certificate.py`). Name, event
  and date are the recipient-specific fields.
- **Storage**: PDFs saved on local disk at `generated/<job_id>/<certificate_id>.pdf`. Swappable for S3 later.

## Project layout
```
app/database.py     DB engine/session, config
app/models.py       Job, Certificate tables
app/certificate.py  PDF template
app/static/index.html  Frontend (plain HTML + JS)
app/main.py         API endpoints, validation, background processing
tests/              pytest tests (creation, validation, generation, status, failures, downloads)
```
