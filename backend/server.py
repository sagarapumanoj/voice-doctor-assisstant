"""Read-only REST routes for the dashboard. Attached to the Pipecat runner's app."""

from fastapi import APIRouter

import db

router = APIRouter(tags=["clinic"])


@router.get("/doctors")
def get_doctors():
    """Doctors with a count of their open upcoming slots."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT d.id, d.name, d.specialty, COUNT(s.id) AS open_slots
               FROM doctors d
               LEFT JOIN slots s
                 ON s.doctor_id = d.id AND s.is_booked = 0 AND s.start_time >= ?
               GROUP BY d.id
               ORDER BY d.name""",
            (db._now(),),
        )
        return [dict(r) for r in rows]


@router.get("/slots")
def get_slots(doctor_id: int | None = None, date: str | None = None):
    """Upcoming slots, booked and open. Optional filters: doctor_id, date=YYYY-MM-DD."""
    slots = db.list_all_slots()
    if doctor_id is not None:
        slots = [s for s in slots if s["doctor_id"] == doctor_id]
    if date:
        slots = [s for s in slots if s["start_time"].startswith(date)]
    return slots


@router.get("/appointments")
def get_appointments():
    """All appointments, newest first, including cancelled ones."""
    return db.list_appointments()