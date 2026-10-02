"""휴가 신청/승인 및 leave_grants 차감 로직.

- 신청 시점에는 신청 기간 동안 사용 가능한 leave_grants 기준으로 잔여일수를
  검증한다. 잔여일수를 초과하면 신청 자체를 거부한다 (레코드가 생성되지 않음).
  (만료일이 신청 기간 중 임박했거나 이미 지난 항목은 사용 불가로 제외한다)
- 실제 leave_grants.used_days 차감은 승인 시점에 반영한다.
  승인 시에도 잔여일수를 재검증하여, 대기 중인 다른 신청이 먼저 승인되어
  잔여가 줄어든 경우에는 승인을 거부한다.
- 반려 시에는 차감 없이 상태만 변경한다.
- 여러 leave_grants 항목이 있는 경우 만료일이 빠른 항목부터 우선 차감한다.
- 단일 승인자 구조이므로 신청자 본인은 본인의 신청을 승인/반려할 수 없다.
- 연차/근속특별휴가는 종류(kind)별로 분리해서 차감한다(섞어 쓰지 않는다).
- 신청 기간 중 주말(토/일)은 제외하고 계산한다(공휴일 테이블은 추후 반영).
- 사용 단위는 1(종일)/0.5(반차)/0.25(반반차)/0.75(반차+반반차). 부분 단위는
  하루(시작일=종료일)만 신청 가능하다.
- 같은 날짜에 걸린 모든 미취소 신청(신청+승인)의 단위 합이 1일을 넘으면 거부한다.
- 신청 미리보기(evaluate_leave_request)와 실제 신청(create_leave_request)은
  동일한 계산 함수를 사용해 결과가 어긋나지 않게 한다.
"""

from datetime import date, timedelta

from app.extensions import db
from app.models import LeaveGrant, LeaveRequest

VALID_UNITS = {1.0, 0.5, 0.25, 0.75}
ACTIVE_STATUSES = ("신청", "승인")


class InsufficientLeaveBalanceError(Exception):
    """잔여 휴가 일수를 초과하는 신청/승인을 시도할 때 발생한다."""


def exclude_weekends(start_date, end_date):
    """start_date~end_date 범위에서 토/일을 제외한 날짜 목록."""
    dates = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # 0=월 ... 4=금
            dates.append(current)
        current += timedelta(days=1)
    return dates


def get_usable_grants(emp_id, start_date, end_date, grant_type=None):
    """신청 기간(start_date~end_date) 동안 사용 가능한 leave_grants를 만료일 오름차순으로 반환한다.

    - grant_date <= start_date: 신청 시작일 이전에 이미 부여된 건만 사용
    - expire_date >= end_date: 신청 종료일까지 유효한 건만 사용
      (만료일이 신청 기간 중 임박했거나 이미 지난 항목은 제외)
    - grant_type을 주면 해당 종류(연차/근속특별휴가)만 조회한다.
    """
    query = LeaveGrant.query.filter_by(emp_id=emp_id)
    if grant_type:
        query = query.filter_by(grant_type=grant_type)
    return (
        query.filter(LeaveGrant.grant_date <= start_date)
        .filter(LeaveGrant.expire_date >= end_date)
        .order_by(LeaveGrant.expire_date.asc(), LeaveGrant.grant_id.asc())
        .all()
    )


def get_remaining_days(emp_id, start_date, end_date, grant_type=None):
    """신청 기간 기준 사용 가능한 총 잔여일수."""
    grants = get_usable_grants(emp_id, start_date, end_date, grant_type=grant_type)
    return sum(g.granted_days - g.used_days for g in grants)


def get_leave_summary(emp_id, as_of_date=None):
    """대시보드용 잔여일수 요약. grant_type(연차/근속특별휴가)별로 부여/사용/잔여를 합산한다."""
    as_of_date = as_of_date or date.today()
    grants = (
        LeaveGrant.query.filter_by(emp_id=emp_id)
        .filter(LeaveGrant.expire_date >= as_of_date)
        .order_by(LeaveGrant.expire_date.asc())
        .all()
    )

    summary = {}
    for grant in grants:
        bucket = summary.setdefault(
            grant.grant_type, {"granted": 0, "used": 0, "remaining": 0, "grants": []}
        )
        bucket["granted"] += grant.granted_days
        bucket["used"] += grant.used_days
        bucket["remaining"] += grant.granted_days - grant.used_days
        bucket["grants"].append(grant)
    return summary


def get_expiring_grants(emp_id, as_of_date=None, within_days=30, grant_type=None):
    """as_of_date 기준 within_days일 이내에 만료되면서 아직 잔여가 남아있는 leave_grants.

    관리자 현황판에서 "만료 예정" 항목을 강조 표시하는 데 사용한다.
    """
    as_of_date = as_of_date or date.today()
    horizon = as_of_date + timedelta(days=within_days)

    query = LeaveGrant.query.filter_by(emp_id=emp_id)
    if grant_type:
        query = query.filter_by(grant_type=grant_type)

    grants = (
        query.filter(LeaveGrant.expire_date >= as_of_date)
        .filter(LeaveGrant.expire_date <= horizon)
        .order_by(LeaveGrant.expire_date.asc())
        .all()
    )
    return [g for g in grants if (g.granted_days - g.used_days) > 0]


def get_daily_committed_units(emp_id, target_date, exclude_request_id=None):
    """target_date에 이미 걸려있는(취소/반려 제외) 신청들의 단위 합."""
    query = (
        LeaveRequest.query.filter_by(emp_id=emp_id)
        .filter(LeaveRequest.status.in_(ACTIVE_STATUSES))
        .filter(LeaveRequest.start_date <= target_date)
        .filter(LeaveRequest.end_date >= target_date)
    )
    if exclude_request_id is not None:
        query = query.filter(LeaveRequest.request_id != exclude_request_id)
    return sum(r.unit for r in query.all())


def evaluate_leave_request(employee, kind, start_date, end_date, unit, exclude_request_id=None):
    """신청 내용을 검증하고 미리보기 정보를 계산한다. 아무것도 저장하지 않는다.

    create_leave_request와 동일한 함수를 사용해, 미리보기와 실제 제출 결과가
    어긋나지 않도록 한다. 반환값의 errors가 비어있어야 실제로 신청 가능하다.
    """
    errors = []

    if end_date < start_date:
        errors.append("종료일은 시작일보다 빠를 수 없습니다.")
        return {
            "valid_dates": [],
            "total_days": 0,
            "remaining_before": 0,
            "remaining_after": 0,
            "errors": errors,
        }

    if unit not in VALID_UNITS:
        errors.append("유효하지 않은 사용 단위입니다.")

    if unit != 1.0 and start_date != end_date:
        errors.append("반차·반반차는 하루 단위로만 신청할 수 있습니다 (시작일=종료일).")
        valid_dates = []
    elif unit != 1.0:
        valid_dates = [start_date] if start_date.weekday() < 5 else []
    else:
        valid_dates = exclude_weekends(start_date, end_date)

    if not valid_dates and not errors:
        errors.append("신청 가능한 날짜가 없습니다 (주말 제외).")

    conflict_dates = []
    for d in valid_dates:
        committed = get_daily_committed_units(
            employee.emp_id, d, exclude_request_id=exclude_request_id
        )
        if committed + unit > 1.0 + 1e-9:
            conflict_dates.append(d)
    if conflict_dates:
        errors.append(
            "이미 해당 날짜에 신청이 있어 하루 한도를 초과합니다: "
            + ", ".join(d.isoformat() for d in conflict_dates)
        )

    total_days = round(len(valid_dates) * unit, 2)
    remaining_before = get_remaining_days(employee.emp_id, start_date, end_date, grant_type=kind)
    if total_days > remaining_before:
        errors.append(
            f"잔여일수({remaining_before}일)를 초과하는 신청입니다 (신청일수: {total_days}일)."
        )

    return {
        "valid_dates": valid_dates,
        "total_days": total_days,
        "remaining_before": remaining_before,
        "remaining_after": remaining_before - total_days,
        "errors": errors,
    }


def create_leave_request(
    employee, start_date, end_date, kind="연차", unit=1.0, unit_label="종일", session=None
):
    """휴가를 신청한다.

    평가 결과에 오류가 있으면(잔여 초과, 당일 한도 초과, 유효한 날짜 없음 등)
    예외를 발생시키고, 이 경우 신청 레코드는 생성되지 않는다.
    """
    session = session or db.session

    result = evaluate_leave_request(employee, kind, start_date, end_date, unit)
    if result["errors"]:
        message = result["errors"][0]
        if "잔여일수" in message:
            raise InsufficientLeaveBalanceError(message)
        raise ValueError(message)

    leave_request = LeaveRequest(
        emp_id=employee.emp_id,
        request_date=date.today(),
        start_date=start_date,
        end_date=end_date,
        days_used=result["total_days"],
        status="신청",
        kind=kind,
        unit=unit,
        unit_label=unit_label,
    )
    session.add(leave_request)
    return leave_request


def approve_leave_request(leave_request, approver, session=None):
    """휴가 신청을 승인하고, 같은 종류(kind)의 leave_grants 중 만료일이 빠른 것부터 차감한다."""
    session = session or db.session

    if leave_request.status != "신청":
        raise ValueError("이미 처리된 신청입니다.")
    if leave_request.emp_id == approver.emp_id:
        raise ValueError("본인이 신청한 휴가는 본인이 승인할 수 없습니다.")

    grants = get_usable_grants(
        leave_request.emp_id,
        leave_request.start_date,
        leave_request.end_date,
        grant_type=leave_request.kind,
    )
    total_available = sum(g.granted_days - g.used_days for g in grants)
    if total_available < leave_request.days_used:
        raise InsufficientLeaveBalanceError(
            "승인 시점 기준 잔여일수가 부족하여 승인할 수 없습니다."
        )

    remaining_to_deduct = leave_request.days_used
    for grant in grants:
        if remaining_to_deduct <= 0:
            break
        available = grant.granted_days - grant.used_days
        if available <= 0:
            continue
        deduct = min(available, remaining_to_deduct)
        grant.used_days += deduct
        remaining_to_deduct -= deduct

    leave_request.status = "승인"
    leave_request.approver_id = approver.emp_id
    return leave_request


def reject_leave_request(leave_request, approver, session=None):
    """휴가 신청을 반려한다. leave_grants 차감은 발생하지 않는다."""
    session = session or db.session

    if leave_request.status != "신청":
        raise ValueError("이미 처리된 신청입니다.")
    if leave_request.emp_id == approver.emp_id:
        raise ValueError("본인이 신청한 휴가는 본인이 반려할 수 없습니다.")

    leave_request.status = "반려"
    leave_request.approver_id = approver.emp_id
    return leave_request


def get_department_absences(department, start_date, end_date, exclude_emp_id=None):
    """같은 부서 동료의 부재 일정(이름만). 휴가 종류/사유는 포함하지 않는다."""
    from app.models import Employee  # 순환 임포트 방지

    query = (
        LeaveRequest.query.join(Employee, LeaveRequest.emp_id == Employee.emp_id)
        .filter(Employee.department == department)
        .filter(LeaveRequest.status.in_(ACTIVE_STATUSES))
        .filter(LeaveRequest.start_date <= end_date)
        .filter(LeaveRequest.end_date >= start_date)
    )
    if exclude_emp_id is not None:
        query = query.filter(LeaveRequest.emp_id != exclude_emp_id)

    results = []
    for req in query.all():
        results.append(
            {
                "name": req.employee.name,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "status": req.status,
            }
        )
    return results
