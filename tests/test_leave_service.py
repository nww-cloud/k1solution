"""휴가 신청/승인 및 leave_grants 차감 로직 단위 테스트.

- 신청 시점: 유효한(만료되지 않은) leave_grants 기준 잔여일수 검증, 초과 시 신청 자체 거부
- 승인 시점: 만료일이 빠른 leave_grants부터 우선 차감(used_days 반영)
- 반려 시: 상태만 변경, 차감 없음
"""

from datetime import date

import pytest

from app.leave_service import (
    InsufficientLeaveBalanceError,
    approve_leave_request,
    create_leave_request,
    get_expiring_grants,
    get_remaining_days,
    get_usable_grants,
    reject_leave_request,
)
from app.models import LeaveRequest


# ---------------------------------------------------------------------------
# 사용 가능한 leave_grants 판별 (만료일 임박/경과 항목 제외)
# ---------------------------------------------------------------------------


def test_get_usable_grants_excludes_grant_expiring_before_request_end(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    valid_grant = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31), granted_days=15
    )
    make_grant(
        employee, grant_date=date(2023, 1, 1), expire_date=date(2024, 1, 5), granted_days=10
    )  # 신청 기간 중 만료됨 -> 사용 불가

    usable = get_usable_grants(employee.emp_id, date(2024, 1, 10), date(2024, 1, 14))

    assert usable == [valid_grant]


def test_get_usable_grants_excludes_grant_not_yet_granted_at_request_start(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 6, 1), expire_date=date(2025, 5, 31), granted_days=10
    )  # 신청 시작일 이후에 부여됨 -> 사용 불가

    usable = get_usable_grants(employee.emp_id, date(2024, 1, 10), date(2024, 1, 14))

    assert usable == []


def test_get_usable_grants_includes_grant_expiring_exactly_on_request_end_date(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    grant = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 1, 14), granted_days=5
    )

    usable = get_usable_grants(employee.emp_id, date(2024, 1, 10), date(2024, 1, 14))

    assert usable == [grant]


def test_get_usable_grants_orders_by_expire_date_ascending(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    later = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31), granted_days=10
    )
    sooner = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 6, 30), granted_days=5
    )

    usable = get_usable_grants(employee.emp_id, date(2024, 1, 10), date(2024, 1, 14))

    assert usable == [sooner, later]


def test_get_remaining_days_sums_usable_grants_only(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=3,
    )
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 1, 5),
        granted_days=100, used_days=0,
    )  # 만료되어 제외

    remaining = get_remaining_days(employee.emp_id, date(2024, 1, 10), date(2024, 1, 14))

    assert remaining == 7


# ---------------------------------------------------------------------------
# 휴가 신청 (create_leave_request)
# ---------------------------------------------------------------------------


def test_create_leave_request_succeeds_within_balance(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=2,
    )

    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    assert leave_request.days_used == 5
    assert leave_request.status == "신청"
    assert leave_request.request_date == date.today()
    # 신청 시점에는 아직 차감되지 않는다 (승인 시 반영)
    assert employee.leave_grants[0].used_days == 2


def test_create_leave_request_rejected_when_exceeds_remaining_balance(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=3, used_days=0,
    )

    with pytest.raises(InsufficientLeaveBalanceError):
        create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))  # 5일 신청 > 잔여 3일

    assert LeaveRequest.query.count() == 0  # 신청 자체가 거부되어 레코드가 생기지 않아야 한다


def test_create_leave_request_invalid_date_range_raises(make_employee):
    employee = make_employee(hire_date=date(2020, 1, 1))
    with pytest.raises(ValueError):
        create_leave_request(employee, date(2024, 3, 14), date(2024, 3, 10))


# ---------------------------------------------------------------------------
# 승인 (approve_leave_request) - 만료일 빠른 항목부터 차감
# ---------------------------------------------------------------------------


def test_approve_deducts_from_earliest_expiring_grant_first(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")

    soon_expiring = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 6, 30),
        granted_days=3, used_days=0,
    )
    later_expiring = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )

    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))  # 5일
    session.commit()

    approve_leave_request(leave_request, approver)
    session.commit()

    assert leave_request.status == "승인"
    assert leave_request.approver_id == approver.emp_id
    assert soon_expiring.used_days == 3  # 먼저 만료되는 건 전량 소진
    assert later_expiring.used_days == 2  # 나머지 2일은 다음 건에서 차감


def test_reject_does_not_deduct_and_sets_status(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    grant = make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )

    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    reject_leave_request(leave_request, approver)
    session.commit()

    assert leave_request.status == "반려"
    assert leave_request.approver_id == approver.emp_id
    assert grant.used_days == 0  # 차감 없음


def test_approve_already_processed_request_raises(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )
    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    approve_leave_request(leave_request, approver)
    session.commit()

    with pytest.raises(ValueError):
        approve_leave_request(leave_request, approver)


def test_reject_already_processed_request_raises(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )
    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    reject_leave_request(leave_request, approver)
    session.commit()

    with pytest.raises(ValueError):
        reject_leave_request(leave_request, approver)


def test_approve_guards_against_double_booking_by_concurrent_pending_requests(
    make_employee, make_grant, session
):
    """신청 시점 검증은 통과했더라도, 승인 시점에 잔여가 부족하면 승인은 거부되어야 한다."""
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=5, used_days=0,
    )

    # 신청 시점에는 둘 다 잔여 5일 기준으로 검증되어 통과한다 (아직 차감 전이므로)
    request_a = create_leave_request(employee, date(2024, 3, 1), date(2024, 3, 3))  # 3일
    request_b = create_leave_request(employee, date(2024, 4, 1), date(2024, 4, 3))  # 3일
    session.commit()

    approve_leave_request(request_a, approver)
    session.commit()
    assert request_a.status == "승인"

    with pytest.raises(InsufficientLeaveBalanceError):
        approve_leave_request(request_b, approver)  # 이미 3일 차감되어 잔여 2일뿐 -> 승인 불가


# ---------------------------------------------------------------------------
# 만료 예정 leave_grants 조회 (관리자 현황판 강조 표시용)
# ---------------------------------------------------------------------------


def test_get_expiring_grants_includes_grant_within_window_with_remaining_days(
    make_employee, make_grant
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    grant = make_grant(
        employee, grant_type="근속특별휴가",
        grant_date=date(2020, 1, 1), expire_date=date(2024, 1, 20),
        granted_days=3, used_days=1,
    )

    expiring = get_expiring_grants(employee.emp_id, as_of_date=date(2024, 1, 1), within_days=30)

    assert expiring == [grant]


def test_get_expiring_grants_excludes_fully_used_grant(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="근속특별휴가",
        grant_date=date(2020, 1, 1), expire_date=date(2024, 1, 20),
        granted_days=3, used_days=3,  # 전량 사용 -> 잔여 없음
    )

    expiring = get_expiring_grants(employee.emp_id, as_of_date=date(2024, 1, 1), within_days=30)

    assert expiring == []


def test_get_expiring_grants_excludes_grant_outside_window(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="근속특별휴가",
        grant_date=date(2020, 1, 1), expire_date=date(2024, 6, 1),  # 30일보다 훨씬 뒤
        granted_days=3, used_days=0,
    )

    expiring = get_expiring_grants(employee.emp_id, as_of_date=date(2024, 1, 1), within_days=30)

    assert expiring == []


def test_get_expiring_grants_can_filter_by_grant_type(make_employee, make_grant):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_type="연차",
        grant_date=date(2024, 1, 1), expire_date=date(2024, 1, 20),
        granted_days=15, used_days=0,
    )
    service_grant = make_grant(
        employee, grant_type="근속특별휴가",
        grant_date=date(2020, 1, 1), expire_date=date(2024, 1, 20),
        granted_days=3, used_days=0,
    )

    expiring = get_expiring_grants(
        employee.emp_id, as_of_date=date(2024, 1, 1), within_days=30, grant_type="근속특별휴가"
    )

    assert expiring == [service_grant]


# ---------------------------------------------------------------------------
# 자기 승인/반려 방지 (단일 승인자 구조 - 신청자 본인은 승인자가 될 수 없음)
# ---------------------------------------------------------------------------


def test_approve_leave_request_rejects_self_approval(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )
    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    with pytest.raises(ValueError):
        approve_leave_request(leave_request, employee)  # 신청자 본인이 승인 시도

    assert leave_request.status == "신청"  # 상태 변경/차감 없어야 함
    assert leave_request.approver_id is None


def test_reject_leave_request_rejects_self_rejection(make_employee, make_grant, session):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )
    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    with pytest.raises(ValueError):
        reject_leave_request(leave_request, employee)  # 신청자 본인이 반려 시도

    assert leave_request.status == "신청"
    assert leave_request.approver_id is None


def test_approve_leave_request_succeeds_when_approver_differs_from_requester(
    make_employee, make_grant, session
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    make_grant(
        employee, grant_date=date(2024, 1, 1), expire_date=date(2024, 12, 31),
        granted_days=10, used_days=0,
    )
    leave_request = create_leave_request(employee, date(2024, 3, 10), date(2024, 3, 14))
    session.commit()

    approve_leave_request(leave_request, approver)  # 다른 사람이 승인하면 정상 처리

    assert leave_request.status == "승인"
    assert leave_request.approver_id == approver.emp_id
