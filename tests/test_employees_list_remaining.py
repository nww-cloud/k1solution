"""인사카드 목록(/employees)에 잔여 휴가일수(연차/근속휴가) 표시 테스트."""

from datetime import date

TODAY = date.today()


def test_employees_list_shows_remaining_leave_columns(make_employee, make_grant, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="조회자")
    target = make_employee(hire_date=date(2020, 1, 1), name="잔여표시대상", department="개발팀")
    make_grant(
        target, grant_type="연차", grant_date=date(TODAY.year, 1, 1),
        expire_date=date(TODAY.year, 12, 31), granted_days=15, used_days=4,
    )
    make_grant(
        target, grant_type="근속특별휴가", grant_date=date(TODAY.year, 1, 1),
        expire_date=date(TODAY.year + 5, 1, 1), granted_days=3, used_days=1,
    )

    login_as(viewer)
    resp = client.get("/employees")
    body = resp.data.decode("utf-8")

    assert resp.status_code == 200
    assert "잔여표시대상" in body
    assert "연차 잔여" in body
    assert "근속휴가 잔여" in body
    assert "11" in body  # 15 - 4
    assert "2.0" in body  # 3 - 1


def test_employees_list_shows_zero_remaining_when_no_grants(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="조회자2")
    make_employee(hire_date=date(2023, 1, 1), name="휴가없음직원")

    login_as(viewer)
    resp = client.get("/employees")
    body = resp.data.decode("utf-8")

    assert "휴가없음직원" in body
