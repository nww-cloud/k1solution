from datetime import date, datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from app.extensions import db
from app.leave_service import get_leave_summary
from app.models import Employee

employees_bp = Blueprint("employees", __name__)


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# 관리자 화면 (HTML)
# ---------------------------------------------------------------------------


@employees_bp.route("/employees")
def list_employees():
    employees = Employee.query.order_by(Employee.emp_id).all()
    leave_summaries = {e.emp_id: get_leave_summary(e.emp_id) for e in employees}
    return render_template(
        "employees/list.html", employees=employees, leave_summaries=leave_summaries
    )


@employees_bp.route("/employees/new", methods=["GET", "POST"])
def new_employee():
    if request.method == "POST":
        employee = Employee(
            name=request.form["name"],
            department=request.form.get("department"),
            position=request.form.get("position"),
            hire_date=_parse_date(request.form["hire_date"]),
            resign_date=_parse_date(request.form.get("resign_date")),
            status=request.form.get("status", "재직"),
        )
        db.session.add(employee)
        db.session.commit()
        return redirect(url_for("employees.list_employees"))

    return render_template("employees/form.html", employee=None)


@employees_bp.route("/employees/<int:emp_id>/edit", methods=["GET", "POST"])
def edit_employee(emp_id):
    employee = Employee.query.get_or_404(emp_id)

    if request.method == "POST":
        employee.name = request.form["name"]
        employee.department = request.form.get("department")
        employee.position = request.form.get("position")
        employee.hire_date = _parse_date(request.form["hire_date"])
        employee.resign_date = _parse_date(request.form.get("resign_date"))
        employee.status = request.form.get("status", "재직")
        db.session.commit()
        return redirect(url_for("employees.list_employees"))

    return render_template("employees/form.html", employee=employee)


@employees_bp.route("/employees/<int:emp_id>/delete", methods=["POST"])
def delete_employee(emp_id):
    employee = Employee.query.get_or_404(emp_id)
    db.session.delete(employee)
    db.session.commit()
    return redirect(url_for("employees.list_employees"))


# ---------------------------------------------------------------------------
# REST API (JSON)
# ---------------------------------------------------------------------------


@employees_bp.route("/api/employees", methods=["GET"])
def api_list_employees():
    employees = Employee.query.order_by(Employee.emp_id).all()
    return jsonify([e.to_dict() for e in employees])


@employees_bp.route("/api/employees/<int:emp_id>", methods=["GET"])
def api_get_employee(emp_id):
    employee = Employee.query.get_or_404(emp_id)
    return jsonify(employee.to_dict())


@employees_bp.route("/api/employees", methods=["POST"])
def api_create_employee():
    data = request.get_json(force=True)
    if not data.get("name") or not data.get("hire_date"):
        return jsonify({"error": "name, hire_date는 필수입니다."}), 400

    employee = Employee(
        name=data["name"],
        department=data.get("department"),
        position=data.get("position"),
        hire_date=_parse_date(data["hire_date"]),
        resign_date=_parse_date(data.get("resign_date")),
        status=data.get("status", "재직"),
    )
    db.session.add(employee)
    db.session.commit()
    return jsonify(employee.to_dict()), 201


@employees_bp.route("/api/employees/<int:emp_id>", methods=["PUT", "PATCH"])
def api_update_employee(emp_id):
    employee = Employee.query.get_or_404(emp_id)
    data = request.get_json(force=True)

    if "name" in data:
        employee.name = data["name"]
    if "department" in data:
        employee.department = data["department"]
    if "position" in data:
        employee.position = data["position"]
    if "hire_date" in data:
        employee.hire_date = _parse_date(data["hire_date"])
    if "resign_date" in data:
        employee.resign_date = _parse_date(data["resign_date"])
    if "status" in data:
        employee.status = data["status"]

    db.session.commit()
    return jsonify(employee.to_dict())


@employees_bp.route("/api/employees/<int:emp_id>", methods=["DELETE"])
def api_delete_employee(emp_id):
    employee = Employee.query.get_or_404(emp_id)
    db.session.delete(employee)
    db.session.commit()
    return "", 204
