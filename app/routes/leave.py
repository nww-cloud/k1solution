from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from app.extensions import db
from app.leave_service import (
    InsufficientLeaveBalanceError,
    approve_leave_request,
    create_leave_request,
    get_leave_summary,
    reject_leave_request,
)
from app.models import Employee, LeaveRequest

leave_bp = Blueprint("leave", __name__)


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


@leave_bp.route("/dashboard")
def dashboard():
    employee = get_current_employee()
    if not employee:
        return redirect(url_for("leave.whoami"))

    summary = get_leave_summary(employee.emp_id)
    return render_template("leave/dashboard.html", employee=employee, summary=summary)


@leave_bp.route("/leave/request", methods=["GET", "POST"])
def request_leave():
    employee = get_current_employee()
    if not employee:
        return redirect(url_for("leave.whoami"))

    error = None
    if request.method == "POST":
        try:
            start_date = _parse_date(request.form["start_date"])
            end_date = _parse_date(request.form["end_date"])
            create_leave_request(employee, start_date, end_date)
            db.session.commit()
            return redirect(url_for("leave.history"))
        except (InsufficientLeaveBalanceError, ValueError) as exc:
            db.session.rollback()
            error = str(exc)

    return render_template("leave/request_form.html", employee=employee, error=error)


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
