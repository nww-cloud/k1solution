"""근속 특별휴가 로직 단위 테스트.

- 입사기념일 기준 운영
- 5/10/15/20년차 도달 시 각각 3/5/8/10일을 leave_grants에 자동 생성
- 유효기간 5년, 다음 단계 도달 시 기존 건은 소멸 처리
- 20년차가 마지막 단계이며 25년째에 완전 소멸
"""

from datetime import date, timedelta

from app.models import LeaveGrant
from app.rules_engine import (
    SERVICE_LEAVE_MILESTONES,
    get_next_service_leave_milestone,
    get_service_years,
    grant_service_special_leave,
    is_service_leave_milestone_upcoming,
)


def test_service_leave_milestones_table():
    assert SERVICE_LEAVE_MILESTONES == {5: 3, 10: 5, 15: 8, 20: 10}


def test_grant_service_special_leave_at_5_years_creates_3_days(make_employee, session):
    employee = make_employee(hire_date=date(2019, 3, 15))

    grant = grant_service_special_leave(employee, 5, session=session)
    session.commit()

    assert grant.grant_type == "근속특별휴가"
    assert grant.granted_days == 3
    assert grant.grant_date == date(2024, 3, 15)
    assert grant.expire_date == date(2029, 3, 15)  # 유효기간 5년

    all_grants = LeaveGrant.query.filter_by(
        emp_id=employee.emp_id, grant_type="근속특별휴가"
    ).all()
    assert len(all_grants) == 1


def test_grant_service_special_leave_at_10_years_creates_5_days_and_retires_5year_grant(
    make_employee, session
):
    employee = make_employee(hire_date=date(2019, 3, 15))

    first = grant_service_special_leave(employee, 5, session=session)
    session.commit()

    second = grant_service_special_leave(employee, 10, session=session)
    session.commit()

    assert second.granted_days == 5
    assert second.grant_date == date(2029, 3, 15)

    session.refresh(first)
    # 10년차 도달 시점부터는 5년차 건이 더 이상 유효하지 않아야 한다
    assert first.expire_date <= second.grant_date

    all_grants = LeaveGrant.query.filter_by(
        emp_id=employee.emp_id, grant_type="근속특별휴가"
    ).all()
    assert len(all_grants) == 2


def test_grant_service_special_leave_retires_stale_grant_early_if_still_valid(
    make_employee, session
):
    """5년 유효기간보다 더 길게 남아있는 예외적인 기존 건도 다음 단계 도달 시 조기 소멸되어야 한다."""
    employee = make_employee(hire_date=date(2019, 3, 15))
    stale_grant = LeaveGrant(
        emp_id=employee.emp_id,
        grant_type="근속특별휴가",
        grant_date=date(2024, 3, 15),
        expire_date=date(2035, 3, 15),  # 실제보다 훨씬 긴 유효기간(예외 상황 가정)
        granted_days=3,
        used_days=0,
        source_rule="근속특별휴가 5년차",
    )
    session.add(stale_grant)
    session.commit()

    grant_service_special_leave(employee, 10, session=session)
    session.commit()

    session.refresh(stale_grant)
    assert stale_grant.expire_date == date(2029, 3, 15)  # 10년차 grant_date로 조기 소멸


def test_grant_service_special_leave_final_stage_at_20_years_expires_completely_at_25_years(
    make_employee, session
):
    employee = make_employee(hire_date=date(2000, 1, 10))

    grant = grant_service_special_leave(employee, 20, session=session)
    session.commit()

    assert grant.granted_days == 10
    assert grant.grant_date == date(2020, 1, 10)
    assert grant.expire_date == date(2025, 1, 10)  # 입사 25년째 완전 소멸


def test_grant_service_special_leave_returns_none_for_non_milestone_year(make_employee, session):
    employee = make_employee(hire_date=date(2019, 3, 15))
    assert grant_service_special_leave(employee, 7, session=session) is None


def test_get_service_years_before_and_on_anniversary():
    hire_date = date(2020, 6, 15)
    assert get_service_years(hire_date, date(2025, 6, 14)) == 4  # 기념일 하루 전
    assert get_service_years(hire_date, date(2025, 6, 15)) == 5  # 기념일 당일


# ---------------------------------------------------------------------------
# 근속특별휴가 발생 예정자 사전 안내 (다음 마일스톤 도래 30일 전 강조 표시용)
# ---------------------------------------------------------------------------


def test_get_next_service_leave_milestone_returns_nearest_upcoming_stage(make_employee):
    employee = make_employee(hire_date=date(2020, 6, 15))
    milestone = get_next_service_leave_milestone(employee, as_of_date=date(2024, 1, 1))

    assert milestone["milestone_years"] == 5
    assert milestone["anniversary_date"] == date(2025, 6, 15)
    assert milestone["granted_days"] == 3


def test_get_next_service_leave_milestone_advances_after_anniversary_passes(make_employee):
    employee = make_employee(hire_date=date(2020, 6, 15))
    milestone = get_next_service_leave_milestone(employee, as_of_date=date(2025, 6, 16))

    assert milestone["milestone_years"] == 10
    assert milestone["anniversary_date"] == date(2030, 6, 15)


def test_get_next_service_leave_milestone_returns_none_after_final_stage(make_employee):
    employee = make_employee(hire_date=date(2000, 1, 10))
    milestone = get_next_service_leave_milestone(employee, as_of_date=date(2021, 1, 1))

    assert milestone is None  # 20년차(2020) 이후에는 더 이상 예정된 단계가 없음


def test_is_service_leave_milestone_upcoming_true_within_30_days(make_employee):
    hire_date = date(2020, 6, 15)
    employee = make_employee(hire_date=hire_date)
    anniversary = date(2025, 6, 15)  # 5년차

    assert is_service_leave_milestone_upcoming(
        employee, as_of_date=anniversary - timedelta(days=30)
    )
    assert is_service_leave_milestone_upcoming(employee, as_of_date=anniversary)


def test_is_service_leave_milestone_upcoming_false_when_far_away(make_employee):
    hire_date = date(2020, 6, 15)
    employee = make_employee(hire_date=hire_date)
    anniversary = date(2025, 6, 15)

    assert not is_service_leave_milestone_upcoming(
        employee, as_of_date=anniversary - timedelta(days=31)
    )
