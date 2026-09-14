"""전체 기능 통합 시나리오: 인사카드 등록 -> 휴가 신청 -> 승인 -> 잔여 확인 -> 퇴사 정산.

모든 화면/API가 실제 라우트를 통해 하나로 연결되어 정상 동작하는지
처음부터 끝까지 한 번에 확인한다.
"""

from datetime import date, timedelta

from app.models import Employee, LeaveGrant, LeaveRequest, ResignationSettlement
from app.rules_engine import grant_annual_leave

TODAY = date.today()


def test_full_lifecycle_from_hire_to_resignation_settlement(client, login_as, session):
    # ------------------------------------------------------------------
    # 1) 인사카드 등록 (관리자 화면 /employees/new, HTML 폼 제출)
    # ------------------------------------------------------------------
    hire_date = TODAY - timedelta(days=200)  # 근속 1년 미만 (첫해 비례 연차 대상)
    resp = client.post(
        "/employees/new",
        data={
            "name": "김신입",
            "department": "개발팀",
            "position": "사원",
            "hire_date": hire_date.isoformat(),
            "status": "재직",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    employee = Employee.query.filter_by(name="김신입").one()
    assert employee.status == "재직"

    resp = client.post(
        "/employees/new",
        data={
            "name": "이승인",
            "department": "경영지원팀",
            "position": "팀장",
            "hire_date": "2010-01-01",
            "status": "재직",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    approver = Employee.query.filter_by(name="이승인").one()

    # ------------------------------------------------------------------
    # 2) 연차 부여 (연간 배치 성격의 rules_engine 호출 - 아직 스케줄러는 없으므로
    #    관리자가 연초에 1회 실행한다고 가정하고 직접 호출한다)
    # ------------------------------------------------------------------
    grant_annual_leave(employee, TODAY.year)
    session.commit()

    grant = LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="연차").one()
    assert grant.granted_days > 0  # 근속 1년 미만 -> 첫해 비례 연차

    # ------------------------------------------------------------------
    # 3) 휴가 신청 (임직원 화면 /leave/request)
    # ------------------------------------------------------------------
    login_as(employee)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "연차".encode("utf-8") in resp.data

    request_start = TODAY + timedelta(days=5)
    request_end = TODAY + timedelta(days=6)  # 2일
    resp = client.post(
        "/leave/request",
        data={"start_date": request_start.isoformat(), "end_date": request_end.isoformat()},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    leave_request = LeaveRequest.query.filter_by(emp_id=employee.emp_id).one()
    assert leave_request.status == "신청"
    assert leave_request.days_used == 2

    # ------------------------------------------------------------------
    # 4) 승인 (담당자 화면 /admin/approvals)
    # ------------------------------------------------------------------
    login_as(approver)
    resp = client.get("/admin/approvals")
    assert "김신입".encode("utf-8") in resp.data

    resp = client.post(
        f"/admin/approvals/{leave_request.request_id}/approve", follow_redirects=False
    )
    assert resp.status_code == 302

    session.refresh(leave_request)
    session.refresh(grant)
    assert leave_request.status == "승인"
    assert grant.used_days == 2

    # ------------------------------------------------------------------
    # 5) 잔여 확인 (본인 대시보드 + 관리자 전체 현황판 양쪽에서 일치해야 한다)
    # ------------------------------------------------------------------
    expected_remaining = grant.granted_days - 2

    login_as(employee)
    resp = client.get("/dashboard")
    assert f"{expected_remaining}".encode("utf-8") in resp.data

    resp = client.get("/leave/history")
    assert "승인".encode("utf-8") in resp.data

    login_as(approver)
    resp = client.get("/admin/employees")
    body = resp.data.decode("utf-8")
    assert "김신입" in body
    assert str(expected_remaining) in body

    # ------------------------------------------------------------------
    # 6) 퇴사 정산 (담당자 화면 /admin/settlement)
    # ------------------------------------------------------------------
    resign_date = TODAY + timedelta(days=60)
    resp = client.post(
        f"/admin/settlement/{employee.emp_id}",
        data={"resign_date": resign_date.isoformat()},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    session.refresh(employee)
    assert employee.status == "퇴사"
    assert employee.resign_date == resign_date

    settlement = ResignationSettlement.query.filter_by(emp_id=employee.emp_id).one()
    assert settlement.company_basis_days == grant.granted_days
    assert settlement.unused_remaining_days == expected_remaining
    assert settlement.settlement_date == resign_date

    # 퇴사 처리 후에는 전체 현황판/정산 대상자 목록에서 제외되어야 한다
    resp = client.get("/admin/employees")
    assert "김신입".encode("utf-8") not in resp.data

    resp = client.get("/admin/settlement")
    assert "김신입".encode("utf-8") not in resp.data

    # 인사카드 화면에는 퇴사 상태/퇴사일이 반영되어야 한다
    resp = client.get("/employees")
    body = resp.data.decode("utf-8")
    assert "김신입" in body
    assert "퇴사" in body
    assert resign_date.isoformat() in body
