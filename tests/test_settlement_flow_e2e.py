"""퇴사 정산 화면 시나리오 테스트 (HTTP 라우트 기준).

/admin/settlement에서 재직자를 선택 -> 퇴사일 입력 -> 정산 처리까지의
전체 흐름과, employees.status/resign_date 갱신 및 resignation_settlements
저장 결과를 검증한다.
"""

from datetime import date

from app.models import Employee, ResignationSettlement


def test_settlement_flow_processes_resignation_and_persists_result(
    make_employee, make_grant, client, login_as, session
):
    processor = make_employee(hire_date=date(2015, 1, 1), name="인사담당자")
    target = make_employee(hire_date=date(2020, 1, 1), name="퇴사대상자")
    make_grant(
        target, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=15, used_days=5,
    )
    make_grant(
        target, grant_type="근속특별휴가", grant_date=date(2024, 1, 1),
        expire_date=date(2029, 1, 1), granted_days=5, used_days=2,
    )

    login_as(processor)

    # 1) 대상자 목록에 재직자로 표시됨
    resp = client.get("/admin/settlement")
    assert resp.status_code == 200
    assert "퇴사대상자".encode("utf-8") in resp.data

    # 2) 상세 페이지 - 아직 미처리 상태 -> 신청 폼 노출
    resp = client.get(f"/admin/settlement/{target.emp_id}")
    assert resp.status_code == 200
    assert "퇴사일".encode("utf-8") in resp.data

    # 3) 퇴사일 입력 후 정산 처리
    resp = client.post(
        f"/admin/settlement/{target.emp_id}",
        data={"resign_date": "2024-06-30"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # 4) employees.status / resign_date 갱신 확인
    session.refresh(target)
    assert target.status == "퇴사"
    assert target.resign_date == date(2024, 6, 30)

    # 5) resignation_settlements 저장 결과 확인
    settlement = ResignationSettlement.query.filter_by(emp_id=target.emp_id).one()
    assert settlement.company_basis_days == 15  # 근속특별휴가(5일)는 제외
    assert settlement.legal_basis_days == 0  # TODO: 법정 기준 미구현 -> 더미값
    assert settlement.excess_used_days == 5  # 사용(5) - 법정기준(0)
    assert settlement.unused_remaining_days == 10  # 15 - 5
    assert settlement.settlement_date == date(2024, 6, 30)

    # 6) 상세 페이지 재방문 시 결과 요약이 표시되어야 한다 (폼 대신)
    resp = client.get(f"/admin/settlement/{target.emp_id}")
    body = resp.data.decode("utf-8")
    assert "정산 결과" in body
    assert "퇴사" in body

    # 7) 목록에서는 더 이상 재직자로 노출되지 않아야 한다
    resp = client.get("/admin/settlement")
    assert "퇴사대상자".encode("utf-8") not in resp.data


def test_settlement_cannot_be_processed_twice_for_same_employee(
    make_employee, make_grant, client, login_as, session
):
    processor = make_employee(hire_date=date(2015, 1, 1), name="인사담당자2")
    target = make_employee(hire_date=date(2020, 1, 1), name="이중정산대상자")
    make_grant(
        target, grant_type="연차", grant_date=date(2024, 1, 1),
        expire_date=date(2024, 12, 31), granted_days=10, used_days=0,
    )

    login_as(processor)
    client.post(
        f"/admin/settlement/{target.emp_id}",
        data={"resign_date": "2024-06-30"},
        follow_redirects=False,
    )

    # 이미 퇴사 처리된 직원에게 다시 POST를 시도해도 새 정산 레코드가 생기지 않아야 한다
    resp = client.post(
        f"/admin/settlement/{target.emp_id}",
        data={"resign_date": "2024-12-31"},
        follow_redirects=False,
    )
    assert resp.status_code == 200  # 에러와 함께 같은 페이지 재표시 (리다이렉트 없음)
    assert "이미 퇴사 처리된 직원입니다".encode("utf-8") in resp.data

    settlements = ResignationSettlement.query.filter_by(emp_id=target.emp_id).all()
    assert len(settlements) == 1  # 중복 생성되지 않음

    session.refresh(target)
    assert target.resign_date == date(2024, 6, 30)  # 최초 처리된 날짜 유지
