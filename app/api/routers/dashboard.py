"""Read-only staff dashboard, server-rendered with Jinja2.

Thin like every other router: parses query params, calls the service layer, renders a
template. No SQL here. Auth is HTTP Basic (DASHBOARD_USERNAME/PASSWORD); security
headers (strict CSP, no-store, noindex) are added by SecurityHeadersMiddleware for every
/dashboard path. See docs/adr/0009-server-rendered-dashboard.md.
"""

from __future__ import annotations

import math
import secrets
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.api.deps import get_appointment_service, get_call_log_service, get_patient_service
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models.call_log import OUTCOMES
from app.services.appointment_service import AppointmentService
from app.services.call_log_service import CallLogService
from app.services.patient_service import PatientService
from app.validation.dates import parse_calendar_date
from app.validation.phone import normalize_us_phone

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
PAGE_SIZE = 25

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",), default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)

_basic = HTTPBasic(auto_error=False)


class DashboardAuthError(Exception):
    """Raised by the auth dependency; rendered as an HTML 401 with WWW-Authenticate."""


def require_dashboard_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
) -> str:
    settings = get_settings()
    if credentials is None:
        raise DashboardAuthError
    # Compare both fields, always, so response time doesn't reveal which one was wrong.
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.DASHBOARD_USERNAME.encode()
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode(), settings.DASHBOARD_PASSWORD.get_secret_value().encode()
    )
    if not (user_ok and pass_ok):
        raise DashboardAuthError
    return credentials.username


router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    include_in_schema=False,
    dependencies=[Depends(require_dashboard_auth)],
)


# --- Formatting helpers (exposed to templates as filters) --------------------------------


def _clinic_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().CLINIC_TIMEZONE)


def format_phone(value: str | None) -> str:
    if not value or len(value) != 10:
        return value or "—"
    return f"({value[:3]}) {value[3:6]}-{value[6:]}"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = value.astimezone(_clinic_tz())
    return local.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") + " ET"


def format_date(value: date | None) -> str:
    return value.strftime("%b %d, %Y").replace(" 0", " ") if value else "—"


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


_env.filters["phone"] = format_phone
_env.filters["dt"] = format_datetime
_env.filters["d"] = format_date
_env.filters["duration"] = format_duration


def render(template: str, *, status_code: int = 200, **context: Any) -> HTMLResponse:
    html = _env.get_template(template).render(**context)
    return HTMLResponse(html, status_code=status_code)


def _start_of_today() -> datetime:
    now_local = datetime.now(_clinic_tz())
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0)


# --- Pages --------------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def dashboard_home(
    patients: Annotated[PatientService, Depends(get_patient_service)],
    calls: Annotated[CallLogService, Depends(get_call_log_service)],
    appointments: Annotated[AppointmentService, Depends(get_appointment_service)],
    q_last_name: Annotated[str | None, Query(alias="last_name")] = None,
    q_phone: Annotated[str | None, Query(alias="phone")] = None,
    q_dob: Annotated[str | None, Query(alias="dob")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    last_name = (q_last_name or "").strip() or None
    phone_raw = (q_phone or "").strip() or None
    dob_raw = (q_dob or "").strip() or None

    errors: list[str] = []
    phone: str | None = None
    dob: date | None = None
    if phone_raw:
        try:
            phone = normalize_us_phone(phone_raw)
        except ValueError as exc:
            errors.append(str(exc))
    if dob_raw:
        try:
            dob = parse_calendar_date(dob_raw, field_name="Date of birth")
        except ValueError as exc:
            errors.append(str(exc))

    rows: list[Any] = []
    total = 0
    if not errors:
        rows, total = await patients.list_patients(
            last_name=last_name,
            date_of_birth=dob,
            phone_number=phone,
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
        )

    today = _start_of_today()
    stats = {
        "total_patients": await patients.count_active(),
        "registered_today": await patients.count_active(created_since=today),
        "calls_today": await calls.count_since(today),
        "upcoming_appointments": await appointments.count_upcoming(),
    }
    searching = any([last_name, phone_raw, dob_raw])
    return render(
        "dashboard/home.html",
        active="patients",
        stats=stats,
        patients=rows,
        total=total,
        page=page,
        pages=max(1, math.ceil(total / PAGE_SIZE)),
        search={"last_name": last_name or "", "phone": phone_raw or "", "dob": dob_raw or ""},
        searching=searching,
        errors=errors,
    )


@router.get("/patients/{patient_id}", response_class=HTMLResponse)
async def dashboard_patient(
    patient_id: str,
    patients: Annotated[PatientService, Depends(get_patient_service)],
    calls: Annotated[CallLogService, Depends(get_call_log_service)],
    appointments: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> HTMLResponse:
    try:
        patient = await patients.get_patient(uuid.UUID(patient_id))
    except (ValueError, NotFoundError):
        return render_not_found("That patient doesn't exist, or their record was removed.")

    providers = {p.provider_id: p.full_name for p in await appointments.list_providers()}
    return render(
        "dashboard/patient.html",
        active="patients",
        patient=patient,
        appointments=await appointments.list_for_patient(patient.patient_id),
        providers=providers,
        call_logs=await calls.list_for_patient(patient.patient_id),
        now=datetime.now(_clinic_tz()),
    )


@router.get("/calls", response_class=HTMLResponse)
async def dashboard_calls(
    calls: Annotated[CallLogService, Depends(get_call_log_service)],
    patients: Annotated[PatientService, Depends(get_patient_service)],
    outcome: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    selected = outcome if outcome in OUTCOMES else None
    rows, total = await calls.list_recent(
        outcome=selected, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )

    names: dict[uuid.UUID, str] = {}
    for call in rows:
        if call.patient_id and call.patient_id not in names:
            try:
                p = await patients.get_patient(call.patient_id)
                names[call.patient_id] = f"{p.first_name} {p.last_name}"
            except NotFoundError:
                names[call.patient_id] = "(removed)"

    return render(
        "dashboard/calls.html",
        active="calls",
        calls=rows,
        names=names,
        total=total,
        page=page,
        pages=max(1, math.ceil(total / PAGE_SIZE)),
        outcomes=OUTCOMES,
        selected=selected,
    )


# --- Error pages ---------------------------------------------------------------------------


@router.get("/{unknown:path}", response_class=HTMLResponse)
async def dashboard_unknown(unknown: str) -> HTMLResponse:
    """Styled 404 for any other /dashboard/... path (registered last, so it never shadows
    the real pages above)."""
    return render_not_found("There's no dashboard page at that address.")


def render_not_found(message: str) -> HTMLResponse:
    return render(
        "dashboard/error.html",
        status_code=404,
        title="Not found",
        message=message,
        active=None,
    )


def register_dashboard(app: FastAPI) -> None:
    """Wire the router and its HTML-rendering 401 handler onto the app."""

    async def _auth_error_handler(request: Request, exc: DashboardAuthError) -> HTMLResponse:
        response = render(
            "dashboard/error.html",
            status_code=401,
            title="Sign in required",
            message="Enter the dashboard username and password to continue.",
            active=None,
            hide_nav=True,
        )
        response.headers["WWW-Authenticate"] = 'Basic realm="Patient dashboard", charset="UTF-8"'
        return response

    app.add_exception_handler(DashboardAuthError, _auth_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
