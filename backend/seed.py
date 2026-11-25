"""Seed mock doctors and slots. Safe to run more than once."""

from datetime import date, datetime, timedelta

import db

DOCTORS = [
    ("Dr. Anjali Sharma", "General Physician"),
    ("Dr. Rohan Mehta", "Cardiologist"),
    ("Dr. Priya Nair", "Dermatologist"),
    ("Dr. Vikram Rao", "Orthopedic"),
]

# Clinic hours: 10:00-13:00 and 15:00-17:00, 30-minute slots
MORNING = [(10, 0), (10, 30), (11, 0), (11, 30), (12, 0), (12, 30)]
AFTERNOON = [(15, 0), (15, 30), (16, 0), (16, 30)]
DAYS_AHEAD = 7


def seed(days_ahead: int = DAYS_AHEAD) -> None:
    db.init_db()
    today = date.today()

    with db.get_conn() as conn:
        # Doctors (INSERT OR IGNORE keeps re-runs harmless)
        for name, specialty in DOCTORS:
            conn.execute(
                "INSERT OR IGNORE INTO doctors (name, specialty) VALUES (?, ?)",
                (name, specialty),
            )

        doctor_ids = [r["id"] for r in conn.execute("SELECT id FROM doctors")]

        for offset in range(0, days_ahead + 1):
            day = today + timedelta(days=offset)
            if day.weekday() == 6:  # skip Sundays
                continue
            for doctor_id in doctor_ids:
                for hour, minute in MORNING + AFTERNOON:
                    start = datetime(day.year, day.month, day.day, hour, minute)
                    conn.execute(
                        "INSERT OR IGNORE INTO slots (doctor_id, start_time) VALUES (?, ?)",
                        (doctor_id, start.strftime("%Y-%m-%d %H:%M")),
                    )


def reset() -> None:
    """Wipe everything and reseed. Handy before recording the demo."""
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    seed()


if __name__ == "__main__":
    import sys

    if "--reset" in sys.argv:
        reset()
        print("Database reset and reseeded.")
    else:
        seed()
        print("Database seeded.")

    slots = db.list_all_slots()
    print(f"{len(db.list_doctors())} doctors, {len(slots)} upcoming slots.")