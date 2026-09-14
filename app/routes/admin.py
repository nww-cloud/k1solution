import json

from flask import Blueprint, redirect, render_template, request, url_for

from app.extensions import db
from app.leave_service import get_expiring_grants, get_leave_summary
from app.models import Employee, LeaveRule
from app.routes.leave import get_current_employee
from app.rules_engine import get_next_service_leave_milestone, is_service_leave_milestone_upcoming

admin_bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# 전 사원 잔여일수 현황판
# ---------------------------------------------------------------------------


@admin_bp.route("/admin/employees")
def employees_overview():
    processor = get_current_employee()
    if not processor:
        return redirect(url_for("leave.whoami"))

    department = request.args.get("department") or ""
    position = request.args.get("position") or ""

    query = Employee.query.filter_by(status="재직")
    if department:
        query = query.filter_by(department=department)
    if position:
        query = query.filter_by(position=position)
    employees = query.order_by(Employee.department, Employee.name).all()

    rows = []
    upcoming_milestones = []
    for employee in employees:
        summary = get_leave_summary(employee.emp_id)
        expiring_service_grants = get_expiring_grants(
            employee.emp_id, grant_type="근속특별휴가", within_days=30
        )
        row = {
            "employee": employee,
            "annual_remaining": summary.get("연차", {}).get("remaining", 0),
            "service_remaining": summary.get("근속특별휴가", {}).get("remaining", 0),
            "expiring_service_grants": expiring_service_grants,
        }
        rows.append(row)

        if is_service_leave_milestone_upcoming(employee, within_days=30):
            milestone = get_next_service_leave_milestone(employee)
            upcoming_milestones.append({"employee": employee, **milestone})

    departments = [
        d[0]
        for d in db.session.query(Employee.department)
        .filter(Employee.department.isnot(None))
        .distinct()
        .order_by(Employee.department)
        .all()
    ]
    positions = [
        p[0]
        for p in db.session.query(Employee.position)
        .filter(Employee.position.isnot(None))
        .distinct()
        .order_by(Employee.position)
        .all()
    ]

    return render_template(
        "admin/employees_overview.html",
        rows=rows,
        upcoming_milestones=upcoming_milestones,
        departments=departments,
        positions=positions,
        selected_department=department,
        selected_position=position,
    )


# ---------------------------------------------------------------------------
# leave_rules 조회/수정
# ---------------------------------------------------------------------------


def _is_valid_optional_json(text):
    """비어있거나 "TODO"(미정 표시)거나, 유효한 JSON이면 통과."""
    if not text or text == "TODO":
        return True
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


@admin_bp.route("/admin/rules")
def rules_list():
    processor = get_current_employee()
    if not processor:
        return redirect(url_for("leave.whoami"))

    rules = LeaveRule.query.order_by(LeaveRule.rule_id).all()
    return render_template("admin/rules_list.html", rules=rules)


@admin_bp.route("/admin/rules/<int:rule_id>/edit", methods=["GET", "POST"])
def rules_edit(rule_id):
    processor = get_current_employee()
    if not processor:
        return redirect(url_for("leave.whoami"))

    rule = LeaveRule.query.get_or_404(rule_id)
    error = None

    if request.method == "POST":
        condition = request.form.get("condition", "").strip()
        value = request.form.get("value", "").strip()

        if not _is_valid_optional_json(condition):
            error = "조건(condition)은 비어있거나 유효한 JSON 형식이어야 합니다."
        elif not _is_valid_optional_json(value):
            error = "값(value)은 비어있거나 유효한 JSON 형식이어야 합니다."
        else:
            rule.condition = condition
            rule.value = value
            db.session.commit()
            return redirect(url_for("admin.rules_list"))

    return render_template("admin/rules_edit.html", rule=rule, error=error)
