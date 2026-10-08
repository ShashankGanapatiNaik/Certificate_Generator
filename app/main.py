import io
import os
import re
import zipfile
from datetime import date
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import certificate
from .database import CERT_DIR, Base, SessionLocal, engine, get_db
from .models import Certificate, Job

Base.metadata.create_all(engine)
app = FastAPI(title="Bulk Certificate Generator")

# Allow the frontend file to call the API even when opened from disk or another port.
# (For production, replace "*" with your real frontend URL.)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Schemas ----------
class Recipient(BaseModel):
    """Validated one by one, so one bad recipient doesn't reject the whole request."""
    name: str = Field(min_length=1, max_length=100)
    email: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v):
        """Remove extra spaces and reject names that are empty after trimming."""
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v):
        """Reject emails that don't look like name@domain.tld."""
        if not EMAIL_RE.match(v.strip()):
            raise ValueError("invalid email")
        return v.strip()


class JobCreate(BaseModel):
    event_name: str = Field(min_length=1, max_length=200)
    issued_on: Optional[date] = None
    # kept as raw dicts on purpose (see Recipient above)
    recipients: list[dict] = Field(min_length=1, max_length=1000)


# ---------- Background processing ----------
def process_job(job_id: int):
    """Background task: generate every pending certificate of a job one by one. A failure on one certificate is saved on that certificate and the loop continues. Uses its own DB session because the request session is already closed."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.status = "processing"
        db.commit()

        pending = db.query(Certificate).filter_by(job_id=job_id, status="pending").all()
        for cert in pending:
            try:
                path = os.path.join(CERT_DIR, str(job_id), f"{cert.id}.pdf")
                certificate.generate_pdf(cert.name, job.event_name, job.issued_on, path)
                cert.status, cert.file_path = "completed", path
            except Exception as e:  # one failure must not stop the others
                cert.status, cert.error = "failed", f"generation error: {e}"
            db.commit()  # commit per certificate so progress is visible

        job.status = final_status(db, job_id)
        db.commit()
    finally:
        db.close()


def count_by_status(db: Session, job_id: int) -> dict:
    """Return how many certificates of a job are in each status, e.g. {'completed': 5, 'failed': 1}."""
    rows = (db.query(Certificate.status, func.count())
            .filter_by(job_id=job_id).group_by(Certificate.status).all())
    return dict(rows)


def final_status(db: Session, job_id: int) -> str:
    """Decide the final job status from the certificate counts: failed (none succeeded), completed_with_errors (some failed) or completed (all succeeded)."""
    counts = count_by_status(db, job_id)
    if not counts.get("completed"):
        return "failed"
    return "completed_with_errors" if counts.get("failed") else "completed"


# ---------- Endpoints ----------
@app.get("/", include_in_schema=False)
def home():
    """Serve the single-page frontend."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/jobs", status_code=202)
def create_job(body: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    """POST /jobs. Validate the request, save the job and one row per recipient (invalid recipients are saved as failed with the reason), then start background generation and return immediately with 202."""
    job = Job(event_name=body.event_name.strip(),
              issued_on=(body.issued_on or date.today()).isoformat())
    db.add(job)
    db.flush()

    for i, raw in enumerate(body.recipients):
        cert = Certificate(job_id=job.id, index=i,
                           name=str(raw.get("name", ""))[:100], email=str(raw.get("email", "")))
        try:
            r = Recipient(**raw)
            cert.name, cert.email = r.name, r.email
        except ValidationError as e:
            cert.status = "failed"
            cert.error = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
        db.add(cert)
    db.flush()

    if count_by_status(db, job.id).get("pending"):
        background.add_task(process_job, job.id)
    else:  # nothing valid to generate
        job.status = "failed"
    db.commit()
    return {"job_id": job.id, "status": job.status, "total": len(body.recipients)}


@app.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    """GET /jobs/{id}. Return job status, counts, progress percent and the per-recipient result (including errors and download links)."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    counts = count_by_status(db, job_id)
    total = sum(counts.values())
    done = counts.get("completed", 0) + counts.get("failed", 0)
    certs = db.query(Certificate).filter_by(job_id=job_id).order_by(Certificate.index).all()
    return {
        "job_id": job.id,
        "event_name": job.event_name,
        "status": job.status,
        "total": total,
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0),
        "progress_percent": round(done / total * 100, 1) if total else 0,
        "certificates": [
            {"id": c.id, "index": c.index, "name": c.name, "email": c.email,
             "status": c.status, "error": c.error,
             "download_url": f"/jobs/{job_id}/certificates/{c.id}" if c.status == "completed" else None}
            for c in certs
        ],
    }


@app.get("/jobs/{job_id}/certificates/{cert_id}")
def download_certificate(job_id: int, cert_id: int, db: Session = Depends(get_db)):
    """GET /jobs/{id}/certificates/{cert_id}. Return one certificate PDF. 404 if it doesn't exist, 409 if it isn't completed."""
    cert = db.query(Certificate).filter_by(id=cert_id, job_id=job_id).first()
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if cert.status != "completed":
        raise HTTPException(409, f"Certificate is {cert.status}")
    return FileResponse(cert.file_path, media_type="application/pdf",
                        filename=f"certificate_{cert.id}.pdf")


@app.get("/jobs/{job_id}/download")
def download_all(job_id: int, db: Session = Depends(get_db)):
    """GET /jobs/{id}/download. Return all successfully generated certificates of a finished job as a ZIP file."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("pending", "processing"):
        raise HTTPException(409, "Job is still running")
    certs = db.query(Certificate).filter_by(job_id=job_id, status="completed").all()
    if not certs:
        raise HTTPException(404, "No certificates were generated")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for c in certs:
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", c.name)
            z.write(c.file_path, f"{c.index:04d}_{safe}.pdf")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=job_{job_id}.zip"})