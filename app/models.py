from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from .database import Base


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    event_name = Column(String, nullable=False)
    issued_on = Column(String, nullable=False)
    # pending -> processing -> completed | completed_with_errors | failed
    status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    certificates = relationship("Certificate", back_populates="job")


class Certificate(Base):
    __tablename__ = "certificates"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), index=True, nullable=False)
    index = Column(Integer, nullable=False)       # position in the request (0-based)
    name = Column(String)
    email = Column(String)
    status = Column(String, default="pending", nullable=False)  # pending|completed|failed
    error = Column(String)
    file_path = Column(String)
    job = relationship("Job", back_populates="certificates")
