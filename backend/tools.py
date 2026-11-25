"""Tools the voice agent can call: availability, booking, cancellation."""

import logging
from datetime import datetime

import db

log = logging.getLogger("tools")


# ---------- helpers ----------

def speakable_time(start_time: str) -> str:
    """'2026-11-25 10:30' -> 'Wednesday, 25 November at 10:30 AM'"""
    dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    hour = dt.hour % 12 or 12
    return f"{dt.strftime('%A')}, {dt.day} {dt.strftime('%B')} at {hour}:{dt.minute:02d} {dt.strftime('%p')}"


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


# ---------- core tool logic (plain functions, easy to test) ----------

def check_doctor_availability(doctor_name: str | None = None,
                              date: str | None = None) -> dict:
    doctor_id = None
    doctor = None

    if doctor_name:
        doctor = db.find_doctor(doctor_name)
        if not doctor:
            return {
                "success": False,
                "reason": "doctor_not_found",
                "available_doctors": [d["name"] for d in db.list_doctors()],
            }
        doctor_id = doctor["id"]

    if date and not _valid_date(date):
        return {"success": False, "reason": "invalid_date",
                "hint": "Date must be in YYYY-MM-DD format."}

    slots = db.get_available_slots(doctor_id=doctor_id, date=date)
    if not slots:
        return {"success": True, "slots": [],
                "message": "No open slots for that request."}

    return {
        "success": True,
        "slots": [
            {
                "slot_id": s["slot_id"],
                "doctor": s["doctor"],
                "specialty": s["specialty"],
                "when": speakable_time(s["start_time"]),
            }
            for s in slots
        ],
    }


def book_appointment(slot_id: int, phone_number: str, patient_name: str,
                     number_confirmed_by_caller: bool = False) -> dict:
    # Enforced in code: the model cannot skip the read-back step.
    if number_confirmed_by_caller is not True:
        return {"success": False, "reason": "number_not_confirmed",
                "hint": "Read the number back digit by digit and get a yes first."}
    if not patient_name or not patient_name.strip():
        return {"success": False, "reason": "missing_name"}

    result = db.book_slot(int(slot_id), phone_number, patient_name)
    if result["success"]:
        result["when"] = speakable_time(result["start_time"])
    return result


def cancel_appointment(phone_number: str,
                       number_confirmed_by_caller: bool = False) -> dict:
    if number_confirmed_by_caller is not True:
        return {"success": False, "reason": "number_not_confirmed",
                "hint": "Read the number back digit by digit and get a yes first."}

    result = db.cancel_by_phone(phone_number)
    if result["success"]:
        result["when"] = speakable_time(result["start_time"])
    return result


# ---------- Pipecat wiring ----------

def build_tools_schema():
    """Tool definitions the LLM sees. Imported lazily so tests don't need Pipecat."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    check = FunctionSchema(
        name="check_doctor_availability",
        description=(
            "List open appointment slots. Optionally filter by doctor name "
            "and/or date. Always call this before offering any time to the caller."
        ),
        properties={
            "doctor_name": {"type": "string",
                            "description": "Doctor's name, e.g. 'Sharma'. Optional."},
            "date": {"type": "string",
                     "description": "Date in YYYY-MM-DD format. Optional."},
        },
        required=[],
    )

    book = FunctionSchema(
        name="book_appointment",
        description=(
            "Book a slot for the caller. Only call after the caller has chosen "
            "a slot AND confirmed their phone number after you read it back."
        ),
        properties={
            "slot_id": {"type": "integer",
                        "description": "slot_id from check_doctor_availability."},
            "phone_number": {"type": "string",
                             "description": "Caller's phone number, digits only."},
            "patient_name": {"type": "string",
                             "description": "Caller's name."},
            "number_confirmed_by_caller": {
                "type": "boolean",
                "description": "True ONLY if you read the number back digit by "
                               "digit and the caller said yes."},
        },
        required=["slot_id", "phone_number", "patient_name",
                  "number_confirmed_by_caller"],
    )

    cancel = FunctionSchema(
        name="cancel_appointment",
        description=(
            "Cancel the caller's existing appointment, found by phone number. "
            "Only call after the caller confirmed the number you read back."
        ),
        properties={
            "phone_number": {"type": "string",
                             "description": "Caller's phone number, digits only."},
            "number_confirmed_by_caller": {
                "type": "boolean",
                "description": "True ONLY if you read the number back digit by "
                               "digit and the caller said yes."},
        },
        required=["phone_number", "number_confirmed_by_caller"],
    )

    return ToolsSchema(standard_tools=[check, book, cancel])


async def _check_handler(params):
    args = params.arguments
    result = check_doctor_availability(args.get("doctor_name"), args.get("date"))
    log.info("check_doctor_availability(%s) -> %s", args, result)
    await params.result_callback(result)


async def _book_handler(params):
    args = params.arguments
    try:
        result = book_appointment(
            args.get("slot_id"),
            args.get("phone_number", ""),
            args.get("patient_name", ""),
            args.get("number_confirmed_by_caller", False),
        )
    except (TypeError, ValueError):
        result = {"success": False, "reason": "invalid_slot_id"}
    log.info("book_appointment(%s) -> %s", args, result)
    await params.result_callback(result)


async def _cancel_handler(params):
    args = params.arguments
    result = cancel_appointment(
        args.get("phone_number", ""),
        args.get("number_confirmed_by_caller", False),
    )
    log.info("cancel_appointment(%s) -> %s", args, result)
    await params.result_callback(result)


def register_tools(llm) -> None:
    """Attach the handlers to the LLM service inside the pipeline."""
    llm.register_function("check_doctor_availability", _check_handler)
    llm.register_function("book_appointment", _book_handler)
    llm.register_function("cancel_appointment", _cancel_handler)