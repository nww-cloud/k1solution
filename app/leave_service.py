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
"""

from datetime import date, timedelta

from app.extensions import db
from app.models import LeaveGrant, LeaveRequest


class InsufficientLeaveBalanceError(Exception):
    """잔여 휴가 일수를 초과하는 신청/승인을 시도할 때 발생한다."""


def get_usable_grants(emp_id, start_date, end_date):
    """신청 기간(start_date~end_date) 동안 사용 가능한 leave_grants를 만료일 오름차순으로 반환한다.

    - grant_date <= start_date: 신청 시작일 이전에 이미 부여된 건만 사용
    - expire_date >= end_date: 신청 종료일까지 유효한 건만 사용
      (만료일이 신청 기간 중 임박했거나 이미 지난 항목은 제외)
    """
    return (
        LeaveGrant.query.filter_by(emp_id=emp_id)
        .filter(LeaveGrant.grant_date <= start_date)
        .filter(LeaveGrant.expire_date >= end_date)
        .order_by(LeaveGrant.expire_date.asc(), LeaveGrant.grant_id.asc())
        .all()
    )


def get_remaining_days(emp_id, start_date, end_date):
    """신청 기간 기준 사용 가능한 총 잔여일수."""
    grants = get_usable_grants(emp_id, start_date, end_date)
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


def create_leave_request(employee, start_date, end_date, session=None):
    """휴가를 신청한다.

    신청 기간 동안 사용 가능한 leave_grants의 잔여일수를 초과하면
    InsufficientLeaveBalanceError를 발생시키고, 이 경우 신청 레코드는 생성되지 않는다.
    """
    session = session or db.session

    if end_date < start_date:
        raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")

    days_used = (end_date - start_date).days + 1
    remaining = get_remaining_days(employee.emp_id, start_date, end_date)
    if days_used > remaining:
        raise InsufficientLeaveBalanceError(
            f"잔여일수({remaining}일)를 초과하는 신청입니다 (신청일수: {days_used}일)."
        )

    leave_request = LeaveRequest(
        emp_id=employee.emp_id,
        request_date=date.today(),
        start_date=start_date,
        end_date=end_date,
        days_used=days_used,
        status="신청",
    )
    session.add(leave_request)
    return leave_request


def approve_leave_request(leave_request, approver, session=None):
    """휴가 신청을 승인하고, 만료일이 빠른 leave_grants부터 순서대로 used_days를 차감한다."""
    session = session or db.session

    if leave_request.status != "신청":
        raise ValueError("이미 처리된 신청입니다.")
    if leave_request.emp_id == approver.emp_id:
        raise ValueError("본인이 신청한 휴가는 본인이 승인할 수 없습니다.")

    grants = get_usable_grants(
        leave_request.emp_id, leave_request.start_date, leave_request.end_date
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
