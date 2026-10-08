import os
import tempfile

# Must be set before the app is imported
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["CERT_DIR"] = f"{_tmp}/certs"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Start every test with empty tables so tests don't affect each other."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def client():
    """Test client for the API. It runs background tasks before returning, so jobs are already finished when we check them."""
    # TestClient runs background tasks before returning, so jobs are finished
    return TestClient(app)
