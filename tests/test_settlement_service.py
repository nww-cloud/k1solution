"""퇴사 정산 서비스(process_resignation_settlement) 단위 테스트.

- 회사 기준 부여량(연차 leave_grants 합계)과 법정 기준 발생량(calculate_legal_basis,
  현재는 더미 0)을 대조해 초과사용/미사용잔여를 자동 판정한다.
- 근속특별휴가는 법정 재정산 대상이 아니므로 회사 기준 집계에서 제외한다.
- 정산 결과는 resignation_settlements에 저장하고, employees.status/resign_date를
  갱신한다.
"""

from datetime import date

import pytest

from app.models import ResignationSettlement
from app.settlement_service import process_resignation_settlement


def test_process_settlement_updates_employee_status_and_resign_date(make_employee, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    resign_date = date(2024, 6, 30)

    process_resignation_settlement(employee, resign_date)
    session.commit()

    assert employee.status == "퇴사"
    assert employee.resign_date == resign_date


def test_process_settlement_computes_unused_remaining_when_underused(
    make_employee, make_grant, session
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=15, used_days=5,
    )

    settlement = process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    assert settlement.company_basis_days == 15
    assert settlement.legal_basis_days == 0  # TODO: 법정 기준 미구현 -> 더미값
    assert settlement.unused_remaining_days == 10  # 15 - 5 (미사용)
    assert settlement.excess_used_days == 5  # 사용(5) - 법정기준(0) = 5 (더미값 기준)
    assert settlement.settlement_date == date(2024, 6, 30)


def test_process_settlement_sums_multiple_annual_grants(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2018, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2023, 1, 1),
        expire_date=date(2023, 12, 31), granted_days=16, used_days=16,
    )
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=17, used_days=3,
    )

    settlement = process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    assert settlement.company_basis_days == 33  # 16 + 17
    assert settlement.unused_remaining_days == 14  # 33 - 19(=16+3)


def test_process_settlement_excludes_service_special_leave_from_company_basis(
    make_employee, make_grant, session
):
    employee = make_employee(hire_date=date(2015, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=17, used_days=0,
    )
    make_grant(
        employee, grant_type="근속특별휴가", grant_date=date(2024, 1, 1),
        expire_date=date(2029, 1, 1), granted_days=8, used_days=0,
    )

    settlement = process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    assert settlement.company_basis_days == 17  # 근속특별휴가(8일)는 제외


def test_process_settlement_ignores_grants_issued_after_resign_date(
    make_employee, make_grant, session
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=15, used_days=0,
    )
    make_grant(
        employee, grant_type="연차", grant_date=date(2025, 1, 1),  # 퇴사일 이후 부여분
        expire_date=date(2025, 12, 31), granted_days=17, used_days=0,
    )

    settlement = process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    assert settlement.company_basis_days == 15  # 2025년 부여분은 집계 제외


def test_process_settlement_persists_settlement_row(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=15, used_days=2,
    )

    process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    saved = ResignationSettlement.query.filter_by(emp_id=employee.emp_id).one()
    assert saved.company_basis_days == 15
    assert saved.unused_remaining_days == 13


def test_process_settlement_rejects_already_resigned_employee(make_employee, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    process_resignation_settlement(employee, date(2024, 6, 30))
    session.commit()

    with pytest.raises(ValueError):
        process_resignation_settlement(employee, date(2024, 12, 31))
