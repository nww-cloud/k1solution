"""신청 -> 승인 -> 잔여차감 전체 흐름 시나리오 테스트 (HTTP 라우트 기준).

실제 화면에서 임직원이 신청하고 담당자가 승인/반려하는 흐름을 재현한다.
날짜는 테스트 실행 시점(오늘) 기준 상대값을 사용해, 대시보드의
"만료되지 않은 항목만 집계" 로직과 항상 맞물리도록 한다.
"""

from datetime import date, timedelta

from app.leave_service import get_leave_summary
from app.models import LeaveGrant, LeaveRequest

TODAY = date.today()
GRANT_DATE = TODAY - timedelta(days=30)
EXPIRE_DATE = TODAY + timedelta(days=300)


def test_whoami_switch_user_sets_session_and_redirects_to_dashboard(make_employee, client):
    employee = make_employee(hire_date=date(2020, 1, 1), name="사용자전환테스트")

    resp = client.get(f"/switch-user/{employee.emp_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess["current_emp_id"] == employee.emp_id


def test_full_scenario_request_approve_reject_and_balance_deduction(
    make_employee, make_grant, client, login_as, session
):
    applicant = make_employee(hire_date=date(2020, 1, 1), name="신청자")
    approver = make_employee(hire_date=date(2015, 1, 1), name="승인자")
    make_grant(
        applicant,
        grant_type="연차",
        grant_date=GRANT_DATE,
        expire_date=EXPIRE_DATE,
        granted_days=10,
        used_days=0,
    )

    # 1) 신청자 로그인 후 신청 폼 접근
    login_as(applicant)
    resp = client.get("/leave/request")
    assert resp.status_code == 200
    assert "휴가 신청".encode("utf-8") in resp.data

    # 2) 5일 신청 -> 신청 성공, 내역 페이지로 리다이렉트
    req1_start = TODAY + timedelta(days=5)
    req1_end = TODAY + timedelta(days=9)  # 5일
    resp = client.post(
        "/leave/request",
        data={"start_date": req1_start.isoformat(), "end_date": req1_end.isoformat()},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/leave/history")

    pending = LeaveRequest.query.filter_by(emp_id=applicant.emp_id, status="신청").one()
    assert pending.days_used == 5

    # 3) 신청 직후에는 아직 차감되지 않아야 한다 (승인 시 반영)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "연차".encode("utf-8") in resp.data

    grant = LeaveGrant.query.filter_by(emp_id=applicant.emp_id).one()
    assert grant.used_days == 0
    summary = get_leave_summary(applicant.emp_id)
    assert summary["연차"]["granted"] == 10
    assert summary["연차"]["used"] == 0
    assert summary["연차"]["remaining"] == 10

    # 4) 담당자 로그인 후 대기 목록 확인
    login_as(approver)
    resp = client.get("/admin/approvals")
    assert resp.status_code == 200
    assert "신청자".encode("utf-8") in resp.data

    # 5) 승인 처리
    resp = client.post(
        f"/admin/approvals/{pending.request_id}/approve", follow_redirects=False
    )
    assert resp.status_code == 302

    session.refresh(pending)
    session.refresh(grant)
    assert pending.status == "승인"
    assert pending.approver_id == approver.emp_id
    assert grant.used_days == 5  # 잔여차감 반영 확인

    # 6) 신청자 대시보드에 잔여일수 감소가 반영되어야 한다
    login_as(applicant)
    summary = get_leave_summary(applicant.emp_id)
    assert summary["연차"]["used"] == 5
    assert summary["연차"]["remaining"] == 5

    resp = client.get("/leave/history")
    assert "승인".encode("utf-8") in resp.data

    # 7) 두 번째 신청(2일) 후 담당자가 반려 -> 차감 없어야 한다
    req2_start = TODAY + timedelta(days=20)
    req2_end = TODAY + timedelta(days=21)  # 2일
    resp = client.post(
        "/leave/request",
        data={"start_date": req2_start.isoformat(), "end_date": req2_end.isoformat()},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    second = LeaveRequest.query.filter_by(emp_id=applicant.emp_id, status="신청").one()

    login_as(approver)
    resp = client.post(
        f"/admin/approvals/{second.request_id}/reject", follow_redirects=False
    )
    assert resp.status_code == 302

    session.refresh(second)
    session.refresh(grant)
    assert second.status == "반려"
    assert second.approver_id == approver.emp_id
    assert grant.used_days == 5  # 반려 시 차감 없음, 승인분(5일)에서 변화 없어야 함

    resp = client.get("/admin/approvals")
    assert "대기 중인 신청이 없습니다".encode("utf-8") in resp.data


def test_request_exceeding_balance_is_rejected_at_submission_with_no_record_created(
    make_employee, make_grant, client, login_as
):
    applicant = make_employee(hire_date=date(2020, 1, 1), name="초과신청자")
    make_grant(
        applicant,
        grant_type="연차",
        grant_date=GRANT_DATE,
        expire_date=EXPIRE_DATE,
        granted_days=5,
        used_days=0,
    )

    login_as(applicant)
    resp = client.post(
        "/leave/request",
        data={
            "start_date": (TODAY + timedelta(days=1)).isoformat(),
            "end_date": (TODAY + timedelta(days=10)).isoformat(),  # 10일 > 잔여 5일
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200  # 리다이렉트 없이 폼에 에러 표시
    assert "초과".encode("utf-8") in resp.data
    assert LeaveRequest.query.filter_by(emp_id=applicant.emp_id).count() == 0


def test_self_approval_is_blocked_with_flash_message_and_ui_hides_buttons(
    make_employee, make_grant, client, login_as
):
    applicant = make_employee(hire_date=date(2020, 1, 1), name="셀프승인시도자")
    make_grant(
        applicant, grant_type="연차", grant_date=GRANT_DATE,
        expire_date=EXPIRE_DATE, granted_days=10, used_days=0,
    )

    login_as(applicant)
    req_start = TODAY + timedelta(days=5)
    req_end = TODAY + timedelta(days=6)
    client.post(
        "/leave/request",
        data={"start_date": req_start.isoformat(), "end_date": req_end.isoformat()},
        follow_redirects=False,
    )
    pending = LeaveRequest.query.filter_by(emp_id=applicant.emp_id, status="신청").one()

    # 승인 목록 화면에는 본인 신청에 대해 승인/반려 버튼이 아닌 안내문이 보여야 한다
    resp = client.get("/admin/approvals")
    body = resp.data.decode("utf-8")
    assert "본인 신청 건은 승인/반려할 수 없습니다" in body

    # 버튼을 우회해 직접 승인 요청을 보내도 서버에서 차단되어야 한다
    resp = client.post(f"/admin/approvals/{pending.request_id}/approve", follow_redirects=True)
    assert "본인이 신청한 휴가는 본인이 승인할 수 없습니다".encode("utf-8") in resp.data

    session_pending = LeaveRequest.query.get(pending.request_id)
    assert session_pending.status == "신청"
    assert session_pending.approver_id is None
