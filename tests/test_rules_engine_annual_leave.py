"""연차 부여 로직 단위 테스트.

- 회계연도(1/1) 기준 운영
- 입사 첫해: 잔여 개월 수 비례
- 2년차 이후: 기본 부여일(15일) + 근속연수 가산(leave_rules 설정, 상한 적용)
- 가산 기준: 근로기준법 제60조 제4항 - 최초 1년을 초과하는 계속근로연수
  매 2년마다 1일 가산, 총 휴가일수 25일 한도 (leave_rules.condition으로 교체 가능)
"""

from datetime import date

from app.models import LeaveGrant
from app.rules_engine import (
    BASE_ANNUAL_LEAVE_DAYS,
    calculate_annual_leave_addon_days,
    calculate_annual_leave_grant,
    calculate_first_year_prorated_leave,
    get_annual_leave_addon_config,
    get_rule,
    grant_annual_leave,
)


class FakeRule:
    """leave_rules 로우를 흉내내는 테스트용 더블."""

    def __init__(self, condition=None, value=None):
        self.condition = condition
        self.value = value


# ---------------------------------------------------------------------------
# 입사 첫해 비례 연차
# ---------------------------------------------------------------------------


def test_first_year_prorated_leave_for_employee_with_1year_6month_tenure():
    # 2024-07-01 입사 (as-of 2026-01-01 기준 1년 6개월차) -> 첫해(2024년) 잔여 7~12월 = 6개월
    hire_date = date(2024, 7, 1)
    assert calculate_first_year_prorated_leave(hire_date) == 7.5


def test_first_year_prorated_leave_hired_in_january_gets_full_base_days():
    hire_date = date(2024, 1, 1)
    assert calculate_first_year_prorated_leave(hire_date) == BASE_ANNUAL_LEAVE_DAYS


def test_first_year_prorated_leave_hired_in_december_gets_one_month_worth():
    hire_date = date(2024, 12, 1)
    assert calculate_first_year_prorated_leave(hire_date) == round(BASE_ANNUAL_LEAVE_DAYS * 1 / 12, 1)


# ---------------------------------------------------------------------------
# 연차가산 (2년차 이후)
# ---------------------------------------------------------------------------


def test_addon_days_uses_default_rule_per_labor_standards_act():
    # 근로기준법 제60조 제4항: 최초 1년 초과 근속연수 매 2년마다 1일 가산
    assert calculate_annual_leave_addon_days(1) == 0
    assert calculate_annual_leave_addon_days(2) == 0
    assert calculate_annual_leave_addon_days(3) == 1
    assert calculate_annual_leave_addon_days(4) == 1
    assert calculate_annual_leave_addon_days(5) == 2
    assert calculate_annual_leave_addon_days(6) == 2
    assert calculate_annual_leave_addon_days(7) == 3


def test_addon_config_falls_back_to_default_when_condition_is_todo():
    rule = FakeRule(condition="TODO", value='{"max_days": 25}')
    config = get_annual_leave_addon_config(rule)
    assert config == {
        "offset_years": 1,
        "interval_years": 2,
        "days_per_interval": 1,
        "max_days": 25,
    }


def test_addon_config_uses_leave_rules_condition_when_defined():
    rule = FakeRule(
        condition='{"interval_years": 2, "days_per_interval": 1}',
        value='{"max_days": 20}',
    )
    assert calculate_annual_leave_addon_days(4, rule) == 1  # (4 - offset 1) // 2
    assert get_annual_leave_addon_config(rule)["max_days"] == 20


def test_annual_leave_grant_for_3rd_and_6th_year_of_service():
    hire_date = date(2020, 1, 1)
    assert calculate_annual_leave_grant(hire_date, 2023) == BASE_ANNUAL_LEAVE_DAYS + 1  # 3년차
    assert calculate_annual_leave_grant(hire_date, 2026) == BASE_ANNUAL_LEAVE_DAYS + 2  # 6년차


def test_annual_leave_grant_is_capped_at_configured_max_days():
    rule = FakeRule(
        condition='{"interval_years": 1, "days_per_interval": 5}',
        value='{"max_days": 20}',
    )
    hire_date = date(2000, 1, 1)
    # 근속 10년 -> 가산만 50일이지만 상한 20일로 제한되어야 한다
    assert calculate_annual_leave_grant(hire_date, 2010, rule) == 20


def test_annual_leave_grant_before_hire_year_is_zero():
    hire_date = date(2024, 1, 1)
    assert calculate_annual_leave_grant(hire_date, 2023) == 0


# ---------------------------------------------------------------------------
# leave_grants 반영 (DB 연동)
# ---------------------------------------------------------------------------


def test_grant_annual_leave_persists_prorated_first_year_grant(make_employee, session):
    employee = make_employee(hire_date=date(2024, 7, 1))

    grant_annual_leave(employee, 2024, session=session)
    session.commit()

    saved = LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="연차").one()
    assert saved.granted_days == 7.5
    assert saved.used_days == 0
    assert saved.grant_date == date(2024, 7, 1)
    assert saved.expire_date == date(2024, 12, 31)  # 연말 소멸, 이월 없음


def test_grant_annual_leave_uses_leave_rules_seed_data(app_ctx, make_employee, session):
    rule = get_rule("연차가산")
    assert rule is not None  # app 생성 시 시드된 데이터

    employee = make_employee(hire_date=date(2018, 1, 1))
    grant = grant_annual_leave(employee, 2024, rule=rule, session=session)  # 근속 6년차
    session.commit()

    assert grant.granted_days == BASE_ANNUAL_LEAVE_DAYS + 2
    assert grant.grant_date == date(2024, 1, 1)
    assert grant.expire_date == date(2024, 12, 31)
