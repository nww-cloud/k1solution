import calendar as calendar_module
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from app.extensions import db
from app.leave_service import (
    InsufficientLeaveBalanceError,
    approve_leave_request,
    create_leave_request,
    evaluate_leave_request,
    get_department_absences,
    get_expiring_grants,
    get_leave_summary,
    reject_leave_request,
)
from app.models import Employee, LeaveRequest
from app.rules_engine import get_next_service_leave_milestone

leave_bp = Blueprint("leave", __name__)

ACTIVE_STATUSES = ("신청", "승인")

UNIT_CHOICES = [
    (1.0, "종일"),
    (0.5, "오전 반차"),
    (0.5, "오후 반차"),
    (0.25, "반반차"),
    (0.75, "반차+반반차"),
]


def _parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_current_employee():
    emp_id = session.get("current_emp_id")
    if not emp_id:
        return None
    return db.session.get(Employee, emp_id)


@leave_bp.before_app_request
def load_current_employee():
    g.current_employee = get_current_employee()


# ---------------------------------------------------------------------------
# 사용자 전환 (임시 - 별도 로그인 기능 도입 전까지 본인 식별용)
# ---------------------------------------------------------------------------


@leave_bp.route("/whoami")
def whoami():
    employees = Employee.query.filter_by(status="재직").order_by(Employee.name).all()
    return render_template("leave/whoami.html", employees=employees)


@leave_bp.route("/switch-user/<int:emp_id>")
def switch_user(emp_id):
    Employee.query.get_or_404(emp_id)
    session["current_emp_id"] = emp_id
    return redirect(url_for("leave.dashboard"))


# ---------------------------------------------------------------------------
# 임직원 화면
# ---------------------------------------------------------------------------


def _month_bounds(year, month):
    start = date(year, month, 1)
    last_day = calendar_module.monthrange(year, month)[1]
    end = date(year, month, last_day)
    return start, end


def _build_calendar_days(year, month, own_requests, colleague_absences, selected_date):
    """달력 셀에 표시할 날짜별 데이터(본인 일정/동료 부재/오늘/선택 여부)를 만든다."""
    cal = calendar_module.Calendar(firstweekday=6)  # 일요일 시작
    today = date.today()

    own_by_date = {}
    for r in own_requests:
        d = r.start_date
        while d <= r.end_date:
            own_by_date.setdefault(d, []).append(r)
            d += timedelta(days=1)

    colleague_by_date = {}
    for item in colleague_absences:
        d = item["start_date"]
        while d <= item["end_date"]:
            colleague_by_date.setdefault(d, []).append(item["name"])
            d += timedelta(days=1)

    weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_days = []
        for d in week:
            week_days.append(
                {
                    "date": d,
                    "in_month": d.month == month,
                    "is_weekend": d.weekday() >= 5,
                    "is_today": d == today,
                    "is_selected": d == selected_date,
                    "own": own_by_date.get(d, []),
                    "colleagues": colleague_by_date.get(d, []),
                }
            )
        weeks.append(week_days)
    return weeks


@leave_bp.route("/dashboard")
def dashboard():
    employee = get_current_employee()
    if not employee:
        return redirect(url_for("leave.whoami"))

    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        date(year, month, 1)
    except ValueError:
        year, month = today.year, today.month

    selected_date = None
    if request.args.get("selected"):
        try:
            selected_date = _parse_date(request.args["selected"])
        except ValueError:
            selected_date = None

    month_start, month_end = _month_bounds(year, month)
    prev_month = month_start - timedelta(days=1)
    next_month = month_end + timedelta(days=1)

    summary = get_leave_summary(employee.emp_id)
    expiring_grants = get_expiring_grants(employee.emp_id, within_days=90)
    next_milestone = get_next_service_leave_milestone(employee)

    own_requests = (
        LeaveRequest.query.filter_by(emp_id=employee.emp_id)
        .filter(LeaveRequest.status.in_(ACTIVE_STATUSES))
        .filter(LeaveRequest.start_date <= month_end, LeaveRequest.end_date >= month_start)
        .all()
    )
    colleague_absences = (
        get_department_absences(
            employee.department, month_start, month_end, exclude_emp_id=employee.emp_id
        )
        if employee.department
        else []
    )
    calendar_weeks = _build_calendar_days(year, month, own_requests, colleague_absences, selected_date)

    upcoming = (
        LeaveRequest.query.filter_by(emp_id=employee.emp_id)
        .filter(LeaveRequest.status.in_(ACTIVE_STATUSES))
        .filter(LeaveRequest.end_date >= today)
        .order_by(LeaveRequest.start_date.asc())
        .limit(3)
        .all()
    )

    selected_day_info = None
    if selected_date:
        selected_day_info = {
            "date": selected_date,
            "own": [r for r in own_requests if r.start_date <= selected_date <= r.end_date],
            "colleagues": [
                item["name"]
                for item in colleague_absences
                if item["start_date"] <= selected_date <= item["end_date"]
            ],
        }

    return render_template(
        "leave/dashboard.html",
        employee=employee,
        summary=summary,
        expiring_grants=expiring_grants,
        next_milestone=next_milestone,
        year=year,
        month=month,
        month_start=month_start,
        prev_year=prev_month.year,
        prev_month=prev_month.month,
        next_year=next_month.year,
        next_month=next_month.month,
        calendar_weeks=calendar_weeks,
        selected_date=selected_date,
        selected_day_info=selected_day_info,
        upcoming=upcoming,
        unit_choices=UNIT_CHOICES,
        today=today,
    )


@leave_bp.route("/leave/request", methods=["GET", "POST"])
def request_leave():
    employee = get_current_employee()
    if not employee:
        return redirect(url_for("leave.whoami"))

    error = None
    default_date = request.args.get("date", "")

    if request.method == "POST":
        try:
            if not request.form.get("start_date") or not request.form.get("end_date"):
                raise ValueError("시작일과 종료일을 입력해주세요.")
            start_date = _parse_date(request.form["start_date"])
            end_date = _parse_date(request.form["end_date"])
            kind = request.form.get("kind", "연차")
            unit = float(request.form.get("unit", 1.0))
            unit_label = request.form.get("unit_label", "종일")
            create_leave_request(
                employee, start_date, end_date, kind=kind, unit=unit, unit_label=unit_label
            )
            db.session.commit()
            return redirect(url_for("leave.history"))
        except (InsufficientLeaveBalanceError, ValueError) as exc:
            db.session.rollback()
            error = str(exc)

    return render_template(
        "leave/request_form.html",
        employee=employee,
        error=error,
        default_date=default_date,
        unit_choices=UNIT_CHOICES,
    )


@leave_bp.route("/leave/request/preview", methods=["POST"])
def request_preview():
    """신청 폼의 실시간 미리보기(AJAX). create_leave_request와 동일한 계산 함수를 사용한다."""
    employee = get_current_employee()
    if not employee:
        return jsonify({"errors": ["로그인이 필요합니다."]}), 401

    payload = request.get_json(silent=True) or request.form
    try:
        start_date = _parse_date(payload["start_date"])
        end_date = _parse_date(payload["end_date"])
        kind = payload.get("kind", "연차")
        unit = float(payload.get("unit", 1.0))
    except (KeyError, ValueError):
        return jsonify({"errors": ["날짜를 확인해주세요."]}), 400

    result = evaluate_leave_request(employee, kind, start_date, end_date, unit)
    return jsonify(
        {
            "valid_dates": [d.isoformat() for d in result["valid_dates"]],
            "total_days": result["total_days"],
            "remaining_before": result["remaining_before"],
            "remaining_after": result["remaining_after"],
            "errors": result["errors"],
        }
    )


@leave_bp.route("/leave/history")
def history():
    employee = get_current_employee()
    if not employee:
        return redirect(url_for("leave.whoami"))

    requests_ = (
        LeaveRequest.query.filter_by(emp_id=employee.emp_id)
        .order_by(LeaveRequest.request_date.desc(), LeaveRequest.request_id.desc())
        .all()
    )
    return render_template("leave/history.html", employee=employee, requests=requests_)


# ---------------------------------------------------------------------------
# 담당자 화면 (단일 승인자 구조)
# ---------------------------------------------------------------------------


@leave_bp.route("/admin/approvals")
def approvals():
    approver = get_current_employee()
    if not approver:
        return redirect(url_for("leave.whoami"))

    pending = (
        LeaveRequest.query.filter_by(status="신청")
        .order_by(LeaveRequest.request_date.asc(), LeaveRequest.request_id.asc())
        .all()
    )
    return render_template("leave/approvals.html", approver=approver, requests=pending)


@leave_bp.route("/admin/approvals/<int:request_id>/approve", methods=["POST"])
def approve(request_id):
    approver = get_current_employee()
    if not approver:
        return redirect(url_for("leave.whoami"))

    leave_request = LeaveRequest.query.get_or_404(request_id)
    try:
        approve_leave_request(leave_request, approver)
        db.session.commit()
    except (InsufficientLeaveBalanceError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("leave.approvals"))


@leave_bp.route("/admin/approvals/<int:request_id>/reject", methods=["POST"])
def reject(request_id):
    approver = get_current_employee()
    if not approver:
        return redirect(url_for("leave.whoami"))

    leave_request = LeaveRequest.query.get_or_404(request_id)
    try:
        reject_leave_request(leave_request, approver)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("leave.approvals"))
