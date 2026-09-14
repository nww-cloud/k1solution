from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Employee, LeaveGrant, ResignationSettlement
from app.routes.leave import get_current_employee
from app.settlement_service import process_resignation_settlement

settlement_bp = Blueprint("settlement", __name__)


def _parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


@settlement_bp.route("/admin/settlement")
def settlement_list():
    processor = get_current_employee()
    if not processor:
        return redirect(url_for("leave.whoami"))

    active_employees = Employee.query.filter_by(status="재직").order_by(Employee.name).all()
    return render_template("admin/settlement_list.html", employees=active_employees)


@settlement_bp.route("/admin/settlement/<int:emp_id>", methods=["GET", "POST"])
def settlement_detail(emp_id):
    processor = get_current_employee()
    if not processor:
        return redirect(url_for("leave.whoami"))

    employee = Employee.query.get_or_404(emp_id)
    error = None

    if request.method == "POST":
        if employee.status == "퇴사":
            error = "이미 퇴사 처리된 직원입니다."
        else:
            try:
                resign_date = _parse_date(request.form["resign_date"])
                process_resignation_settlement(employee, resign_date)
                db.session.commit()
                return redirect(url_for("settlement.settlement_detail", emp_id=emp_id))
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)

    settlement = None
    service_leave_remaining = 0
    if employee.status == "퇴사":
        settlement = (
            ResignationSettlement.query.filter_by(emp_id=employee.emp_id)
            .order_by(ResignationSettlement.settlement_id.desc())
            .first()
        )
        service_grants = LeaveGrant.query.filter_by(
            emp_id=employee.emp_id, grant_type="근속특별휴가"
        ).all()
        service_leave_remaining = sum(g.granted_days - g.used_days for g in service_grants)

    return render_template(
        "admin/settlement_detail.html",
        employee=employee,
        settlement=settlement,
        service_leave_remaining=service_leave_remaining,
        error=error,
    )
