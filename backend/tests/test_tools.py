import pytest

import db
import tools

PHONE = "98765 43210"
OTHER_PHONE = "+91 91234 56789"


# ---------- phone normalization ----------

@pytest.mark.parametrize("raw, expected", [
    ("9876543210", "9876543210"),
    ("98765 43210", "9876543210"),
    ("+91 98765 43210", "9876543210"),
    ("098765-43210", "9876543210"),
    ("12345", None),
    ("", None),
    ("abcdefghij", None),
])
def test_normalize_phone(raw, expected):
    assert db.normalize_phone(raw) == expected


# ---------- check_doctor_availability ----------

def test_availability_all_doctors():
    result = tools.check_doctor_availability()
    assert result["success"] is True
    assert len(result["slots"]) > 0
    assert {"slot_id", "doctor", "specialty", "when"} <= set(result["slots"][0])


def test_availability_by_doctor_partial_name():
    result = tools.check_doctor_availability("dr sharma")
    assert result["success"] is True
    assert all("Sharma" in s["doctor"] for s in result["slots"])


def test_availability_unknown_doctor():
    result = tools.check_doctor_availability("Dr. Nobody")
    assert result["success"] is False
    assert result["reason"] == "doctor_not_found"
    assert len(result["available_doctors"]) == 4


def test_availability_invalid_date():
    result = tools.check_doctor_availability(date="25th November")
    assert result["success"] is False
    assert result["reason"] == "invalid_date"


def test_availability_filters_by_date(open_slots):
    day = open_slots[0]["start_time"][:10]
    result = tools.check_doctor_availability(date=day)
    assert result["success"] is True
    assert len(result["slots"]) > 0


def test_availability_no_slots_on_far_date():
    result = tools.check_doctor_availability(date="2099-01-01")
    assert result["success"] is True
    assert result["slots"] == []


# ---------- book_appointment ----------

def test_book_requires_number_confirmation(open_slots):
    result = tools.book_appointment(open_slots[0]["slot_id"], PHONE, "Asha", False)
    assert result == {
        "success": False,
        "reason": "number_not_confirmed",
        "hint": result["hint"],
    }
    # nothing was written
    assert db.list_appointments() == []


def test_book_happy_path(open_slots):
    slot_id = open_slots[0]["slot_id"]
    result = tools.book_appointment(slot_id, PHONE, "Asha", True)
    assert result["success"] is True
    assert result["phone"] == "9876543210"
    assert "when" in result

    appts = db.list_appointments()
    assert len(appts) == 1
    assert appts[0]["status"] == "booked"

    # slot is no longer offered
    remaining = {s["slot_id"] for s in db.get_available_slots(limit=500)}
    assert slot_id not in remaining


def test_book_rejects_invalid_phone(open_slots):
    result = tools.book_appointment(open_slots[0]["slot_id"], "12345", "Asha", True)
    assert result["reason"] == "invalid_phone"


def test_book_rejects_missing_name(open_slots):
    result = tools.book_appointment(open_slots[0]["slot_id"], PHONE, "  ", True)
    assert result["reason"] == "missing_name"


def test_book_slot_not_found():
    result = tools.book_appointment(999999, PHONE, "Asha", True)
    assert result["reason"] == "slot_not_found"


def test_double_booking_same_slot_blocked(open_slots):
    slot_id = open_slots[0]["slot_id"]
    first = tools.book_appointment(slot_id, PHONE, "Asha", True)
    second = tools.book_appointment(slot_id, OTHER_PHONE, "Ravi", True)
    assert first["success"] is True
    assert second["success"] is False
    assert second["reason"] == "slot_taken"
    assert len(db.list_appointments()) == 1


def test_one_active_appointment_per_phone(open_slots):
    tools.book_appointment(open_slots[0]["slot_id"], PHONE, "Asha", True)
    result = tools.book_appointment(open_slots[1]["slot_id"], PHONE, "Asha", True)
    assert result["reason"] == "already_has_appointment"
    # the second slot must stay free
    free = {s["slot_id"] for s in db.get_available_slots(limit=500)}
    assert open_slots[1]["slot_id"] in free


def test_same_number_in_different_formats_is_same_caller(open_slots):
    tools.book_appointment(open_slots[0]["slot_id"], "9876543210", "Asha", True)
    result = tools.book_appointment(open_slots[1]["slot_id"], "+91 98765 43210", "Asha", True)
    assert result["reason"] == "already_has_appointment"


# ---------- cancel_appointment ----------

def test_cancel_requires_number_confirmation():
    result = tools.cancel_appointment(PHONE, False)
    assert result["reason"] == "number_not_confirmed"


def test_cancel_no_appointment():
    result = tools.cancel_appointment(PHONE, True)
    assert result["success"] is False
    assert result["reason"] == "no_appointment_found"


def test_cancel_invalid_phone():
    result = tools.cancel_appointment("123", True)
    assert result["reason"] == "invalid_phone"


def test_cancel_happy_path_frees_slot(open_slots):
    slot_id = open_slots[0]["slot_id"]
    tools.book_appointment(slot_id, PHONE, "Asha", True)

    result = tools.cancel_appointment("+91 98765 43210", True)
    assert result["success"] is True
    assert result["patient_name"] == "Asha"

    assert db.list_appointments()[0]["status"] == "cancelled"
    free = {s["slot_id"] for s in db.get_available_slots(limit=500)}
    assert slot_id in free


def test_cancel_twice_fails_second_time(open_slots):
    tools.book_appointment(open_slots[0]["slot_id"], PHONE, "Asha", True)
    assert tools.cancel_appointment(PHONE, True)["success"] is True
    assert tools.cancel_appointment(PHONE, True)["reason"] == "no_appointment_found"


def test_can_rebook_after_cancel(open_slots):
    tools.book_appointment(open_slots[0]["slot_id"], PHONE, "Asha", True)
    tools.cancel_appointment(PHONE, True)
    result = tools.book_appointment(open_slots[1]["slot_id"], PHONE, "Asha", True)
    assert result["success"] is True


# ---------- full conversation flow ----------

def test_check_book_cancel_in_one_flow():
    slots = tools.check_doctor_availability("Mehta")["slots"]
    booked = tools.book_appointment(slots[0]["slot_id"], PHONE, "Asha", True)
    assert booked["success"] is True
    cancelled = tools.cancel_appointment(PHONE, True)
    assert cancelled["success"] is True
    assert cancelled["doctor"] == "Dr. Rohan Mehta"