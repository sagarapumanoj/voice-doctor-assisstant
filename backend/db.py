"""SQLite data layer for the doctor appointment assistant."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "clinic.db"  # tests can override this

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    specialty TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id  INTEGER NOT NULL REFERENCES doctors(id),
    start_time TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM' (clinic local time)
    is_booked  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (doctor_id, start_time)
);

CREATE TABLE IF NOT EXISTS appointments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id      INTEGER NOT NULL REFERENCES slots(id),
    patient_name TEXT NOT NULL,
    phone        TEXT NOT NULL,            -- normalized 10 digits
    status       TEXT NOT NULL DEFAULT 'booked',   -- 'booked' | 'cancelled'
    created_at   TEXT NOT NULL,
    cancelled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_slots_start ON slots(start_time);
CREATE INDEX IF NOT EXISTS idx_appt_phone ON appointments(phone, status);
"""


@contextmanager
def get_conn():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------- phone handling ----------

def normalize_phone(raw: str) -> str | None:
    """Return a 10-digit Indian number, or None if it can't be one.

    '+91 98765 43210', '098765-43210', '9876543210' -> '9876543210'
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


# ---------- reads ----------

def list_doctors() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, specialty FROM doctors ORDER BY name")
        return [dict(r) for r in rows]


def find_doctor(name: str) -> dict | None:
    """Case-insensitive partial match, so 'dr sharma' or 'sharma' both work."""
    cleaned = re.sub(r"^\s*dr\.?\s+", "", name.strip(), flags=re.I)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, specialty FROM doctors WHERE name LIKE ? LIMIT 1",
            (f"%{cleaned}%",),
        ).fetchone()
        return dict(row) if row else None


def get_available_slots(doctor_id: int | None = None,
                        date: str | None = None,
                        limit: int = 8) -> list[dict]:
    """Future, unbooked slots. Optionally filter by doctor and/or 'YYYY-MM-DD'."""
    sql = """
        SELECT s.id AS slot_id, d.name AS doctor, d.specialty, s.start_time
        FROM slots s JOIN doctors d ON d.id = s.doctor_id
        WHERE s.is_booked = 0 AND s.start_time >= ?
    """
    params: list = [_now()]
    if doctor_id is not None:
        sql += " AND s.doctor_id = ?"
        params.append(doctor_id)
    if date:
        sql += " AND substr(s.start_time, 1, 10) = ?"
        params.append(date)
    sql += " ORDER BY s.start_time LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def list_all_slots() -> list[dict]:
    """Every upcoming slot, booked or not (for the dashboard)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.id AS slot_id, d.id AS doctor_id, d.name AS doctor,
                      s.start_time, s.is_booked
               FROM slots s JOIN doctors d ON d.id = s.doctor_id
               WHERE s.start_time >= ?
               ORDER BY d.name, s.start_time""",
            (_now(),),
        )
        return [dict(r) for r in rows]


def list_appointments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.id, a.patient_name, a.phone, a.status, a.created_at,
                      a.cancelled_at, d.name AS doctor, d.specialty, s.start_time
               FROM appointments a
               JOIN slots s ON s.id = a.slot_id
               JOIN doctors d ON d.id = s.doctor_id
               ORDER BY a.id DESC"""
        )
        return [dict(r) for r in rows]


def get_active_appointment(phone: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT a.id, a.patient_name, a.phone, d.name AS doctor,
                      d.specialty, s.start_time, s.id AS slot_id
               FROM appointments a
               JOIN slots s ON s.id = a.slot_id
               JOIN doctors d ON d.id = s.doctor_id
               WHERE a.phone = ? AND a.status = 'booked'
               ORDER BY a.id DESC LIMIT 1""",
            (phone,),
        ).fetchone()
        return dict(row) if row else None


# ---------- writes ----------

def book_slot(slot_id: int, phone: str, patient_name: str) -> dict:
    """Book a slot atomically. Never double-books.

    Rule: one active appointment per phone number, so cancelling by phone
    is always unambiguous.
    """
    normalized = normalize_phone(phone)
    if normalized is None:
        return {"success": False, "reason": "invalid_phone"}

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM appointments WHERE phone = ? AND status = 'booked'",
            (normalized,),
        ).fetchone()
        if existing:
            return {"success": False, "reason": "already_has_appointment"}

        # The atomic guard: only one caller can flip is_booked from 0 to 1.
        cur = conn.execute(
            "UPDATE slots SET is_booked = 1 WHERE id = ? AND is_booked = 0",
            (slot_id,),
        )
        if cur.rowcount != 1:
            exists = conn.execute(
                "SELECT 1 FROM slots WHERE id = ?", (slot_id,)
            ).fetchone()
            return {"success": False,
                    "reason": "slot_taken" if exists else "slot_not_found"}

        conn.execute(
            """INSERT INTO appointments (slot_id, patient_name, phone, status, created_at)
               VALUES (?, ?, ?, 'booked', ?)""",
            (slot_id, patient_name.strip(), normalized, _now()),
        )

        info = conn.execute(
            """SELECT d.name AS doctor, d.specialty, s.start_time
               FROM slots s JOIN doctors d ON d.id = s.doctor_id
               WHERE s.id = ?""",
            (slot_id,),
        ).fetchone()

    return {"success": True, "phone": normalized,
            "patient_name": patient_name.strip(), **dict(info)}


def cancel_by_phone(phone: str) -> dict:
    """Cancel the caller's active appointment and free its slot."""
    normalized = normalize_phone(phone)
    if normalized is None:
        return {"success": False, "reason": "invalid_phone"}

    with get_conn() as conn:
        appt = conn.execute(
            """SELECT a.id, a.slot_id, a.patient_name, d.name AS doctor, s.start_time
               FROM appointments a
               JOIN slots s ON s.id = a.slot_id
               JOIN doctors d ON d.id = s.doctor_id
               WHERE a.phone = ? AND a.status = 'booked'
               ORDER BY a.id DESC LIMIT 1""",
            (normalized,),
        ).fetchone()
        if not appt:
            return {"success": False, "reason": "no_appointment_found"}

        conn.execute(
            "UPDATE appointments SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (_now(), appt["id"]),
        )
        conn.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (appt["slot_id"],))

    return {"success": True, "phone": normalized, "doctor": appt["doctor"],
            "start_time": appt["start_time"], "patient_name": appt["patient_name"]}