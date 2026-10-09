import os
import tempfile

# use a throwaway database file for tests (must be set BEFORE importing the app)
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def make_user(client, email):
    client.post("/auth/signup", json={"email": email, "password": "pass1234"})
    tokens = client.post("/auth/login", json={"email": email, "password": "pass1234"}).json()
    return tokens


def auth_header(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}
