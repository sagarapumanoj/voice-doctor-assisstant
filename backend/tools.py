
"""Tools the voice agent can call: availability, booking, cancellation."""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import db

log = logging.getLogger("tools")

CLINIC_TIMEZONE = ZoneInfo("Asia/Kolkata")


# --------------------------------------------------
# 1. Helpers
# --------------------------------------------------

def normalize_phone(phone_number: str) -> str | None:
    """Normalize and validate an Indian 10-digit phone number."""

    if not isinstance(phone_number, str):
        return None

    digits = re.sub(r"\D", "", phone_number)

    # Accept either 10 digits or 91 + 10 digits.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]

    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return None

    return digits


def speakable_time(start_time: str) -> str:
    """Convert database time into natural spoken time."""

    dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")

    hour = dt.hour % 12 or 12

    return (
        f"{dt.strftime('%A')}, "
        f"{dt.day} {dt.strftime('%B')} "
        f"at {hour}:{dt.minute:02d} "
        f"{dt.strftime('%p')}"
    )


def valid_date(value: str) -> bool:
    """Validate YYYY-MM-DD and reject past dates."""

    if not isinstance(value, str):
        return False

    try:
        requested = datetime.strptime(value, "%Y-%m-%d").date()
        today = datetime.now(CLINIC_TIMEZONE).date()

        return requested >= today

    except ValueError:
        return False


def valid_name(name: str) -> bool:
    if not isinstance(name, str):
        return False

    name = name.strip()

    return (
        1 <= len(name) <= 100
        and any(char.isalpha() for char in name)
    )


# --------------------------------------------------
# 2. Check doctor availability
# --------------------------------------------------

def check_doctor_availability(
    doctor_name: str | None = None,
    date: str | None = None,
) -> dict:

    doctor_id = None

    if doctor_name is not None:
        if not isinstance(doctor_name, str) or not doctor_name.strip():
            return {
                "success": False,
                "reason": "invalid_doctor_name",
            }

        doctor = db.find_doctor(doctor_name.strip())

        if not doctor:
            return {
                "success": False,
                "reason": "doctor_not_found",
                "available_doctors": [
                    d["name"] for d in db.list_doctors()
                ],
            }

        doctor_id = doctor["id"]

    if date is not None and not valid_date(date):
        return {
            "success": False,
            "reason": "invalid_or_past_date",
            "hint": "Provide a current or future date in YYYY-MM-DD format.",
        }

    slots = db.get_available_slots(
        doctor_id=doctor_id,
        date=date,
    )

    if not slots:
        return {
            "success": True,
            "slots": [],
            "message": "No open slots for that request.",
        }

    available_slots = []

    for slot in slots:
        available_slots.append({
            "slot_id": slot["slot_id"],
            "doctor": slot["doctor"],
            "specialty": slot["specialty"],
            "when": speakable_time(slot["start_time"]),
        })

    return {
        "success": True,
        "slots": available_slots,
    }


# --------------------------------------------------
# 3. Book appointment
# --------------------------------------------------

def book_appointment(
    slot_id: int,
    phone_number: str,
    patient_name: str,
    number_confirmed_by_caller: bool = False,
) -> dict:

    # Validate confirmation.
    if number_confirmed_by_caller is not True:
        return {
            "success": False,
            "reason": "number_not_confirmed",
        }

    # Validate phone.
    phone = normalize_phone(phone_number)

    if not phone:
        return {
            "success": False,
            "reason": "invalid_phone_number",
            "hint": "A valid 10-digit Indian mobile number is required.",
        }

    # Validate patient name.
    if not valid_name(patient_name):
        return {
            "success": False,
            "reason": "invalid_patient_name",
        }

    # Validate slot ID.
    if isinstance(slot_id, bool):
        return {
            "success": False,
            "reason": "invalid_slot_id",
        }

    try:
        slot_id = int(slot_id)

        if slot_id <= 0:
            raise ValueError("Invalid slot ID")

    except (TypeError, ValueError):
        return {
            "success": False,
            "reason": "invalid_slot_id",
        }

    # Perform database booking.
    result = db.book_slot(
        slot_id,
        phone,
        patient_name.strip(),
    )

    if result.get("success"):
        result["when"] = speakable_time(result["start_time"])

    return result


# --------------------------------------------------
# 4. Cancel appointment
# --------------------------------------------------

def cancel_appointment(
    phone_number: str,
    number_confirmed_by_caller: bool = False,
) -> dict:

    if number_confirmed_by_caller is not True:
        return {
            "success": False,
            "reason": "number_not_confirmed",
        }

    phone = normalize_phone(phone_number)

    if not phone:
        return {
            "success": False,
            "reason": "invalid_phone_number",
        }

    result = db.cancel_by_phone(phone)

    if result.get("success"):
        result["when"] = speakable_time(result["start_time"])

    return result


# --------------------------------------------------
# 5. Pipecat tool schemas
# --------------------------------------------------

def build_tools_schema():

    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    check = FunctionSchema(
        name="check_doctor_availability",
        description=(
            "Check actual doctor appointment availability. "
            "Always call before suggesting appointment times. "
            "Never invent slot IDs or availability."
        ),
        properties={
            "doctor_name": {
                "type": "string",
                "description": "Doctor name. Optional.",
            },
            "date": {
                "type": "string",
                "description": "Appointment date in YYYY-MM-DD format. Optional.",
            },
        },
        required=[],
    )

    book = FunctionSchema(
        name="book_appointment",
        description=(
            "Book an available appointment slot. "
            "Only call after the caller has selected the slot, "
            "provided their name, and confirmed their phone number."
        ),
        properties={
            "slot_id": {
                "type": "integer",
                "description": "Exact slot_id from availability results.",
            },
            "phone_number": {
                "type": "string",
                "description": "Confirmed 10-digit caller phone number.",
            },
            "patient_name": {
                "type": "string",
                "description": "Patient's full name.",
            },
            "number_confirmed_by_caller": {
                "type": "boolean",
                "description": "True only after explicit caller confirmation.",
            },
        },
        required=[
            "slot_id",
            "phone_number",
            "patient_name",
            "number_confirmed_by_caller",
        ],
    )

    cancel = FunctionSchema(
        name="cancel_appointment",
        description=(
            "Cancel an existing appointment associated with "
            "the caller's confirmed phone number."
        ),
        properties={
            "phone_number": {
                "type": "string",
                "description": "Confirmed 10-digit phone number.",
            },
            "number_confirmed_by_caller": {
                "type": "boolean",
                "description": "True only after explicit confirmation.",
            },
        },
        required=[
            "phone_number",
            "number_confirmed_by_caller",
        ],
    )

    return ToolsSchema(
        standard_tools=[
            check,
            book,
            cancel,
        ]
    )


# --------------------------------------------------
# 6. Tool handlers
# --------------------------------------------------

async def _check_handler(params):

    args = params.arguments

    try:
        result = check_doctor_availability(
            args.get("doctor_name"),
            args.get("date"),
        )

    except Exception:
        log.exception("Availability check failed")
        result = {
            "success": False,
            "reason": "internal_error",
        }

    log.info("Availability check completed: success=%s",
             result.get("success"))

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

    except Exception:
        log.exception("Appointment booking failed")
        result = {
            "success": False,
            "reason": "internal_error",
        }

    log.info(
        "Booking operation completed: success=%s",
        result.get("success"),
    )

    await params.result_callback(result)


async def _cancel_handler(params):

    args = params.arguments

    try:
        result = cancel_appointment(
            args.get("phone_number", ""),
            args.get("number_confirmed_by_caller", False),
        )

    except Exception:
        log.exception("Appointment cancellation failed")
        result = {
            "success": False,
            "reason": "internal_error",
        }

    log.info(
        "Cancellation operation completed: success=%s",
        result.get("success"),
    )

    await params.result_callback(result)


# --------------------------------------------------
# 7. Register tools with LLM
# --------------------------------------------------

def register_tools(llm):

    llm.register_function(
        "check_doctor_availability",
        _check_handler,
    )

    llm.register_function(
        "book_appointment",
        _book_handler,
    )

    llm.register_function(
        "cancel_appointment",
        _cancel_handler,
    )

    log.info("Appointment tools registered successfully.")
