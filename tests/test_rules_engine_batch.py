"""전 직원 대상 휴가 일괄 부여 배치 (관리자 화면의 '일괄 부여 실행' 버튼용).

- 연차: 재직 중인 전 직원에게 해당 연도분을 부여, 이미 부여된 경우 건너뜀
- 근속특별휴가: 각 직원이 실제 도달한 가장 높은 마일스톤을 부여, 이미 부여된 경우 건너뜀
  (반복 실행해도 중복 생성되지 않아야 한다)
"""

from datetime import date

from app.models import LeaveGrant
from app.rules_engine import (
    BASE_ANNUAL_LEAVE_DAYS,
    run_annual_leave_grant_batch,
    run_service_leave_grant_batch,
)


def test_annual_leave_batch_grants_all_active_employees(make_employee, session):
    emp_a = make_employee(hire_date=date(2020, 1, 1), name="직원A")
    emp_b = make_employee(hire_date=date(2015, 1, 1), name="직원B")
    make_employee(hire_date=date(2018, 1, 1), name="퇴사자", status="퇴사")

    results = run_annual_leave_grant_batch(grant_year=2024)
    session.commit()

    granted_emp_ids = {r["employee"].emp_id for r in results if not r["skipped"]}
    assert emp_a.emp_id in granted_emp_ids
    assert emp_b.emp_id in granted_emp_ids
    assert len(results) == 2  # 퇴사자는 대상에서 제외

    saved = LeaveGrant.query.filter_by(emp_id=emp_a.emp_id, grant_type="연차").one()
    assert saved.granted_days >= BASE_ANNUAL_LEAVE_DAYS


def test_annual_leave_batch_skips_employee_already_granted_this_year(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=99, used_days=0,
    )

    results = run_annual_leave_grant_batch(grant_year=2024)
    session.commit()

    assert results[0]["skipped"] is True
    all_grants = LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="연차").all()
    assert len(all_grants) == 1  # 중복 생성되지 않음
    assert all_grants[0].granted_days == 99  # 기존 값 그대로


def test_annual_leave_batch_is_idempotent_when_run_twice(make_employee, session):
    make_employee(hire_date=date(2020, 1, 1))

    run_annual_leave_grant_batch(grant_year=2024)
    session.commit()
    run_annual_leave_grant_batch(grant_year=2024)
    session.commit()

    assert LeaveGrant.query.filter_by(grant_type="연차").count() == 1


def test_service_leave_batch_grants_highest_reached_milestone(make_employee, session):
    # 근속 6년 -> 5년차(3일)까지만 도달, 10년차는 아직
    employee = make_employee(hire_date=date(2018, 1, 1))

    results = run_service_leave_grant_batch(as_of_date=date(2024, 1, 1))
    session.commit()

    assert results[0]["milestone_years"] == 5
    assert results[0]["skipped"] is False
    saved = LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="근속특별휴가").one()
    assert saved.granted_days == 3


def test_service_leave_batch_skips_employee_under_5_years(make_employee, session):
    make_employee(hire_date=date(2022, 1, 1))  # 근속 2년

    results = run_service_leave_grant_batch(as_of_date=date(2024, 1, 1))

    assert results[0]["skipped"] is True
    assert results[0]["milestone_years"] is None
    assert LeaveGrant.query.count() == 0


def test_service_leave_batch_is_idempotent_when_run_twice(make_employee, session):
    make_employee(hire_date=date(2018, 1, 1))  # 근속 6년 -> 5년차 대상

    run_service_leave_grant_batch(as_of_date=date(2024, 1, 1))
    session.commit()
    run_service_leave_grant_batch(as_of_date=date(2024, 1, 1))
    session.commit()

    assert LeaveGrant.query.filter_by(grant_type="근속특별휴가").count() == 1


def test_service_leave_batch_only_excludes_resigned_employees(make_employee, session):
    make_employee(hire_date=date(2018, 1, 1), name="퇴사자", status="퇴사")

    results = run_service_leave_grant_batch(as_of_date=date(2024, 1, 1))

    assert results == []
