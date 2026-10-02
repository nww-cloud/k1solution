"""대시보드 캘린더(본인 일정/동료 부재 표시)와 신청 미리보기 API 테스트."""

import json
from datetime import date, timedelta

from conftest import next_monday_on_or_after
from app.models import LeaveRequest

TODAY = date.today()


def test_dashboard_shows_own_leave_on_calendar_cell(make_employee, make_grant, client, login_as):
    employee = make_employee(hire_date=date(2020, 1, 1), name="박도윤", department="개발팀")
    make_grant(
        employee, grant_date=date(TODAY.year, 1, 1), expire_date=date(TODAY.year, 12, 31),
        granted_days=15, used_days=0,
    )
    req_day = next_monday_on_or_after(TODAY + timedelta(days=3))

    login_as(employee)
    client.post(
        "/leave/request",
        data={"start_date": req_day.isoformat(), "end_date": req_day.isoformat()},
        follow_redirects=False,
    )

    resp = client.get(f"/dashboard?year={req_day.year}&month={req_day.month}")
    body = resp.data.decode("utf-8")
    assert resp.status_code == 200
    assert str(req_day.day) in body


def test_dashboard_shows_department_colleague_name_only(
    make_employee, make_grant, client, login_as
):
    viewer = make_employee(hire_date=date(2020, 1, 1), name="조회자", department="개발팀")
    colleague = make_employee(hire_date=date(2020, 1, 1), name="동료김", department="개발팀")
    other_dept = make_employee(hire_date=date(2020, 1, 1), name="타부서박", department="영업팀")
    for emp in (colleague, other_dept):
        make_grant(
            emp, grant_date=date(TODAY.year, 1, 1), expire_date=date(TODAY.year, 12, 31),
            granted_days=15, used_days=0,
        )
    req_day = next_monday_on_or_after(TODAY + timedelta(days=3))

    login_as(colleague)
    client.post(
        "/leave/request",
        data={"start_date": req_day.isoformat(), "end_date": req_day.isoformat()},
        follow_redirects=False,
    )
    login_as(other_dept)
    client.post(
        "/leave/request",
        data={"start_date": req_day.isoformat(), "end_date": req_day.isoformat()},
        follow_redirects=False,
    )

    login_as(viewer)
    resp = client.get(f"/dashboard?year={req_day.year}&month={req_day.month}")
    body = resp.data.decode("utf-8")

    assert "동료김" in body  # 같은 부서 -> 이름 노출
    assert "타부서박" not in body  # 다른 부서 -> 노출 안 됨


def test_dashboard_selected_date_shows_day_panel(make_employee, client, login_as):
    employee = make_employee(hire_date=date(2020, 1, 1), name="조회자2", department="개발팀")
    target = next_monday_on_or_after(TODAY + timedelta(days=10))

    login_as(employee)
    resp = client.get(f"/dashboard?selected={target.isoformat()}")

    assert resp.status_code == 200
    assert str(target.day) in resp.data.decode("utf-8")


def test_leave_request_preview_returns_total_days_without_creating_request(
    make_employee, make_grant, client, login_as
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(TODAY.year, 1, 1), expire_date=date(TODAY.year, 12, 31),
        granted_days=15, used_days=2,
    )
    start = next_monday_on_or_after(TODAY + timedelta(days=3))
    end = start + timedelta(days=4)  # 월~금 5일

    login_as(employee)
    resp = client.post(
        "/leave/request/preview",
        data=json.dumps(
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "kind": "연차", "unit": 1.0}
        ),
        content_type="application/json",
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_days"] == 5
    assert data["remaining_before"] == 13
    assert data["remaining_after"] == 8
    assert data["errors"] == []
    assert LeaveRequest.query.count() == 0


def test_leave_request_preview_reports_errors_for_weekend_only_range(
    make_employee, make_grant, client, login_as
):
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(TODAY.year, 1, 1), expire_date=date(TODAY.year, 12, 31),
        granted_days=15, used_days=0,
    )
    saturday = next_monday_on_or_after(TODAY) + timedelta(days=5)  # 월요일+5 = 토요일
    sunday = saturday + timedelta(days=1)

    login_as(employee)
    resp = client.post(
        "/leave/request/preview",
        data=json.dumps(
            {"start_date": saturday.isoformat(), "end_date": sunday.isoformat(), "kind": "연차", "unit": 1.0}
        ),
        content_type="application/json",
    )

    data = resp.get_json()
    assert data["errors"]


def test_leave_request_with_kind_and_unit_persists_correctly(
    make_employee, make_grant, client, login_as
):
    employee = make_employee(hire_date=date(2018, 1, 1))
    make_grant(
        employee, grant_type="근속특별휴가", grant_date=date(TODAY.year, 1, 1),
        expire_date=date(TODAY.year + 5, 1, 1), granted_days=3, used_days=0,
    )
    req_day = next_monday_on_or_after(TODAY + timedelta(days=3))

    login_as(employee)
    client.post(
        "/leave/request",
        data={
            "start_date": req_day.isoformat(),
            "end_date": req_day.isoformat(),
            "kind": "근속특별휴가",
            "unit": "0.5",
            "unit_label": "오전 반차",
        },
        follow_redirects=False,
    )

    saved = LeaveRequest.query.filter_by(emp_id=employee.emp_id).one()
    assert saved.kind == "근속특별휴가"
    assert saved.unit == 0.5
    assert saved.unit_label == "오전 반차"
    assert saved.days_used == 0.5


def test_leave_request_without_end_date_shows_friendly_error_not_500(
    make_employee, make_grant, client, login_as
):
    """반차 선택 시 JS가 종료일을 채우지만, JS가 실패해 end_date가 통째로 빠져 와도
    500 에러가 아니라 사용자용 에러 메시지로 응답해야 한다."""
    employee = make_employee(hire_date=date(2020, 1, 1))
    make_grant(
        employee, grant_date=date(TODAY.year, 1, 1), expire_date=date(TODAY.year, 12, 31),
        granted_days=15, used_days=0,
    )
    req_day = next_monday_on_or_after(TODAY + timedelta(days=3))

    login_as(employee)
    resp = client.post(
        "/leave/request",
        data={"start_date": req_day.isoformat()},  # end_date 누락
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert "시작일과 종료일".encode("utf-8") in resp.data
    assert LeaveRequest.query.count() == 0
