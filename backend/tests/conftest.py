"""Shared fixtures: every test gets a fresh, seeded temporary database."""

import sys
from pathlib import Path

import pytest

# Make `import db`, `import tools` work from the tests folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    seed.seed()
    yield


@pytest.fixture
def open_slots():
    """A few upcoming open slots, soonest first."""
    return db.get_available_slots(limit=5)