"""휴가 규칙 엔진.

leave_rules 테이블의 설정값을 읽어 아래 항목을 계산/적용한다.
- 연차 부여 (회계연도 기준, rule_type='연차가산')
- 근속특별휴가 부여/소멸 (입사기념일 기준, rule_type='근속특별휴가')
- 법정재정산 (rule_type='법정재정산') - TODO: 규칙 미정, 2단계에서 구현
"""

import json
from datetime import date

from app.extensions import db
from app.models import Employee, LeaveGrant, LeaveRule


def get_rules(rule_type=None):
    """leave_rules 설정값을 조회한다. rule_type을 주면 해당 유형만 반환."""
    query = LeaveRule.query
    if rule_type:
        query = query.filter_by(rule_type=rule_type)
    return query.all()


def get_rule(rule_type):
    """leave_rules에서 해당 유형의 최신 규칙 1건을 조회한다. 없으면 None."""
    return (
        LeaveRule.query.filter_by(rule_type=rule_type)
        .order_by(LeaveRule.rule_id.desc())
        .first()
    )


def _shift_years(d, years):
    """d로부터 years년 후의 날짜. 2/29 등 대상 연도에 없는 날짜는 2/28로 보정한다."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


# ---------------------------------------------------------------------------
# 연차 부여 로직 (회계연도 = 매년 1월 1일 기준)
# ---------------------------------------------------------------------------

BASE_ANNUAL_LEAVE_DAYS = 15  # 근로기준법 제60조 제1항: 1년 이상 근속자 연 15일

# 근로기준법 제60조 제4항: 최초 1년을 초과하는 계속근로연수 매 2년에 대하여
# 1일을 가산(가산휴가 포함 총 휴가일수 25일 한도). 회사가 법정 기준보다
# 유리하게 정책을 바꿀 경우 leave_rules(rule_type='연차가산')에서 조정 가능하도록
# interval_years/days_per_interval/offset_years/max_days를 설정값으로 둔다.
DEFAULT_ADDON_OFFSET_YEARS = 1
DEFAULT_ADDON_INTERVAL_YEARS = 2
DEFAULT_ADDON_DAYS_PER_INTERVAL = 1
DEFAULT_ADDON_MAX_DAYS = 25


def get_annual_leave_addon_config(rule=None):
    """연차가산 설정을 반환한다.

    rule.condition/rule.value가 유효한 JSON이 아니면(예: 시드값 "TODO")
    근로기준법 제60조 제4항 기준 기본값을 사용한다.
    """
    offset_years = DEFAULT_ADDON_OFFSET_YEARS
    interval_years = DEFAULT_ADDON_INTERVAL_YEARS
    days_per_interval = DEFAULT_ADDON_DAYS_PER_INTERVAL
    max_days = DEFAULT_ADDON_MAX_DAYS

    if rule is not None:
        try:
            condition = json.loads(rule.condition)
            offset_years = condition.get("offset_years", offset_years)
            interval_years = condition.get("interval_years", interval_years)
            days_per_interval = condition.get("days_per_interval", days_per_interval)
        except (TypeError, ValueError, AttributeError):
            pass  # condition이 "TODO" 등 미정 상태 -> 기본값 유지

        try:
            value = json.loads(rule.value)
            max_days = value.get("max_days", max_days)
        except (TypeError, ValueError, AttributeError):
            pass

    return {
        "offset_years": offset_years,
        "interval_years": interval_years,
        "days_per_interval": days_per_interval,
        "max_days": max_days,
    }


def calculate_annual_leave_addon_days(years_of_service, rule=None):
    """근속연수에 따른 연차가산 일수 (상한 적용 전).

    근로기준법 제60조 제4항: 최초 offset_years(기본 1년)를 초과하는 근속연수
    매 interval_years(기본 2년)마다 days_per_interval(기본 1일)을 가산한다.
    """
    config = get_annual_leave_addon_config(rule)
    if config["interval_years"] <= 0:
        return 0
    effective_years = years_of_service - config["offset_years"]
    if effective_years <= 0:
        return 0
    return (effective_years // config["interval_years"]) * config["days_per_interval"]


def calculate_first_year_prorated_leave(hire_date, base_days=BASE_ANNUAL_LEAVE_DAYS):
    """입사 첫해 잔여 개월 수 비례 연차 (회계연도=1/1 기준)."""
    remaining_months = 13 - hire_date.month
    return round(base_days * remaining_months / 12, 1)


def calculate_annual_leave_grant(hire_date, grant_year, rule=None):
    """grant_year 회계연도(1/1) 기준 부여할 연차 일수.

    - 입사 첫해(grant_year == hire_date.year): 잔여 개월 수 비례
    - 2년차 이후: 기본 부여일(15일) + 근속연수 가산, leave_rules 상한 적용
    - 이월 없음(미사용분은 연말 소멸) - 부여량 계산에는 영향 없음
    """
    if grant_year < hire_date.year:
        return 0
    if grant_year == hire_date.year:
        return calculate_first_year_prorated_leave(hire_date)

    years_of_service = grant_year - hire_date.year
    addon = calculate_annual_leave_addon_days(years_of_service, rule)
    max_days = get_annual_leave_addon_config(rule)["max_days"]
    return min(BASE_ANNUAL_LEAVE_DAYS + addon, max_days)


def grant_annual_leave(employee, grant_year, rule=None, session=None):
    """employee에 대해 grant_year 회계연도 연차를 leave_grants에 생성한다.

    미사용분은 이월하지 않으므로 만료일은 항상 grant_year 12/31이다.
    """
    session = session or db.session
    granted_days = calculate_annual_leave_grant(employee.hire_date, grant_year, rule)
    grant_date = employee.hire_date if grant_year == employee.hire_date.year else date(grant_year, 1, 1)

    grant = LeaveGrant(
        emp_id=employee.emp_id,
        grant_type="연차",
        grant_date=grant_date,
        expire_date=date(grant_year, 12, 31),
        granted_days=granted_days,
        used_days=0,
        source_rule=f"연차 {grant_year}년도 부여",
    )
    session.add(grant)
    return grant


def run_annual_leave_grant_batch(grant_year=None, rule=None, session=None):
    """재직 중인 전 직원에게 grant_year 연차를 일괄 부여한다 (관리자 수동 실행용 배치).

    아직 스케줄러가 없으므로 연초에 관리자가 한 번 실행한다고 가정한다.
    이미 해당 연도분이 부여된 직원은 건너뛰어 중복 부여를 방지한다(반복 실행 안전).
    반환값: [{"employee", "granted_days", "skipped"}, ...]
    """
    session = session or db.session
    grant_year = grant_year or date.today().year
    rule = rule or get_rule("연차가산")

    results = []
    employees = Employee.query.filter_by(status="재직").order_by(Employee.emp_id).all()
    for employee in employees:
        existing = (
            LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="연차")
            .filter(LeaveGrant.expire_date == date(grant_year, 12, 31))
            .first()
        )
        if existing:
            results.append(
                {"employee": employee, "granted_days": existing.granted_days, "skipped": True}
            )
            continue

        grant = grant_annual_leave(employee, grant_year, rule=rule, session=session)
        results.append(
            {"employee": employee, "granted_days": grant.granted_days, "skipped": False}
        )
    return results


# ---------------------------------------------------------------------------
# 근속 특별휴가 로직 (입사기념일 기준)
# ---------------------------------------------------------------------------

SERVICE_LEAVE_MILESTONES = {5: 3, 10: 5, 15: 8, 20: 10}  # 근속연수 -> 부여일수
SERVICE_LEAVE_VALID_YEARS = 5


def get_service_years(hire_date, as_of_date):
    """입사기념일 기준 만근속연수."""
    years = as_of_date.year - hire_date.year
    anniversary_this_year = _shift_years(hire_date, years)
    if as_of_date < anniversary_this_year:
        years -= 1
    return years


def grant_service_special_leave(employee, milestone_years, session=None):
    """입사기념일 기준 milestone_years(5/10/15/20) 도달 시 근속특별휴가를 생성한다.

    - 유효기간 5년
    - 다음 단계 도달 시 기존 건은 조기 소멸 처리한다
    - 20년차가 마지막 단계이며 25년째(20년차 건의 만료일)에 완전 소멸된다
    - milestone_years가 정의된 단계가 아니면 아무 것도 하지 않고 None 반환
    """
    if milestone_years not in SERVICE_LEAVE_MILESTONES:
        return None

    session = session or db.session
    granted_days = SERVICE_LEAVE_MILESTONES[milestone_years]
    grant_date = _shift_years(employee.hire_date, milestone_years)
    expire_date = _shift_years(grant_date, SERVICE_LEAVE_VALID_YEARS)

    # 다음 단계 도달 시점에 아직 유효한 이전 단계 건은 조기 소멸 처리한다.
    existing_grants = (
        LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="근속특별휴가")
        .filter(LeaveGrant.expire_date > grant_date)
        .all()
    )
    for existing in existing_grants:
        existing.expire_date = grant_date

    new_grant = LeaveGrant(
        emp_id=employee.emp_id,
        grant_type="근속특별휴가",
        grant_date=grant_date,
        expire_date=expire_date,
        granted_days=granted_days,
        used_days=0,
        source_rule=f"근속특별휴가 {milestone_years}년차",
    )
    session.add(new_grant)
    return new_grant


def run_service_leave_grant_batch(as_of_date=None, session=None):
    """재직 중인 전 직원에게 현재 시점 기준 도달한 근속특별휴가를 일괄 부여한다.

    각 직원은 실제 도달한 마일스톤 중 가장 높은 것 하나만 대상으로 삼는다
    (grant_service_special_leave가 이전 단계 건을 자동으로 소멸 처리하므로
    중간 단계를 건너뛰어도 최종 상태는 동일하다). 이미 해당 마일스톤 건이
    있으면 건너뛰어 중복 부여를 방지한다(반복 실행 안전).
    반환값: [{"employee", "milestone_years", "granted_days", "skipped"}, ...]
    """
    session = session or db.session
    as_of_date = as_of_date or date.today()

    results = []
    employees = Employee.query.filter_by(status="재직").order_by(Employee.emp_id).all()
    for employee in employees:
        service_years = get_service_years(employee.hire_date, as_of_date)
        applicable = [m for m in sorted(SERVICE_LEAVE_MILESTONES) if m <= service_years]
        if not applicable:
            results.append(
                {"employee": employee, "milestone_years": None, "granted_days": None, "skipped": True}
            )
            continue

        highest = max(applicable)
        existing = LeaveGrant.query.filter_by(
            emp_id=employee.emp_id,
            grant_type="근속특별휴가",
            source_rule=f"근속특별휴가 {highest}년차",
        ).first()
        if existing:
            results.append(
                {
                    "employee": employee,
                    "milestone_years": highest,
                    "granted_days": existing.granted_days,
                    "skipped": True,
                }
            )
            continue

        grant = grant_service_special_leave(employee, highest, session=session)
        results.append(
            {
                "employee": employee,
                "milestone_years": highest,
                "granted_days": grant.granted_days,
                "skipped": False,
            }
        )
    return results


def get_next_service_leave_milestone(employee, as_of_date=None):
    """as_of_date 시점 기준 다음으로 도래할 근속특별휴가 마일스톤 정보.

    아직 도달하지 않은(입사기념일이 as_of_date 이후인) 단계 중 가장 가까운 것을
    {"milestone_years", "anniversary_date", "granted_days"} 형태로 반환한다.
    마지막 단계(20년차)까지 지났으면 None을 반환한다.
    """
    as_of_date = as_of_date or date.today()
    for milestone_years in sorted(SERVICE_LEAVE_MILESTONES):
        anniversary_date = _shift_years(employee.hire_date, milestone_years)
        if anniversary_date >= as_of_date:
            return {
                "milestone_years": milestone_years,
                "anniversary_date": anniversary_date,
                "granted_days": SERVICE_LEAVE_MILESTONES[milestone_years],
            }
    return None


def is_service_leave_milestone_upcoming(employee, as_of_date=None, within_days=30):
    """다음 근속특별휴가 마일스톤이 within_days일 이내에 도래하는지 여부.

    관리자 현황판에서 "근속특별휴가 발생 예정자"를 사전 안내하는 데 사용한다.
    별도 이메일/알림 발송 인프라는 없으므로 화면 표시로 대체한다.
    """
    as_of_date = as_of_date or date.today()
    milestone = get_next_service_leave_milestone(employee, as_of_date)
    if not milestone:
        return False
    days_until = (milestone["anniversary_date"] - as_of_date).days
    return 0 <= days_until <= within_days


# ---------------------------------------------------------------------------
# 법정재정산 (rule_type='법정재정산') - TODO: 근로기준법 조항 확정 후 구현
# ---------------------------------------------------------------------------


def calculate_legal_basis(employee, resign_date, rule=None):
    """퇴사일(resign_date) 기준 법정 휴가 발생량을 재산출한다.

    근속기간에 따라 계산 방식이 다르므로 두 갈래로 함수를 분리해둔다.
    - 1년 미만: 월차 개념 (근로기준법 제60조 제2항)
    - 1년 이상: 연차 개념 (근로기준법 제60조 제1항/제4항)

    TODO: 법정재정산 조항(leave_rules.rule_type='법정재정산')이 아직 미정이므로
    실제 계산 로직은 구현하지 않고 임시로 더미값(0)을 반환한다.
    조항이 확정되면 아래 두 헬퍼 함수에 실제 계산식을 채워 넣는다.
    """
    service_years = get_service_years(employee.hire_date, resign_date)
    if service_years < 1:
        return _calculate_legal_basis_under_1year(employee, resign_date, rule)
    return _calculate_legal_basis_1year_or_more(employee, resign_date, rule)


def _calculate_legal_basis_under_1year(employee, resign_date, rule=None):
    """근속 1년 미만 - 법정 월차 발생량 (근로기준법 제60조 제2항).

    TODO: 입사월부터 퇴사월까지 개근 개월 수 기준 매월 1일 발생 로직 구현 필요.
    조항 확정 전까지는 더미값 0을 반환한다.
    """
    return 0


def _calculate_legal_basis_1year_or_more(employee, resign_date, rule=None):
    """근속 1년 이상 - 법정 연차 발생량 (근로기준법 제60조 제1항/제4항).

    TODO: 최초 1년 초과 근속연수에 대한 가산(매 2년당 1일, 한도 25일 등)을
    반영한 실제 계산 로직 구현 필요.
    조항 확정 전까지는 더미값 0을 반환한다.
    """
    return 0
