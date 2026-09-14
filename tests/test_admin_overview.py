"""관리자 전체 현황판(/admin/employees)과 규칙 설정(/admin/rules) 화면 테스트."""

from datetime import date, timedelta

from app.rules_engine import calculate_annual_leave_addon_days, get_rule

TODAY = date.today()


def test_employees_overview_lists_active_employees_with_remaining_summary(
    make_employee, make_grant, client, login_as
):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="관리자")
    target = make_employee(
        hire_date=date(2020, 1, 1), name="현황조회대상", department="개발팀", position="대리"
    )
    make_grant(
        target, grant_type="연차", grant_date=date(TODAY.year, 1, 1),
        expire_date=date(TODAY.year, 12, 31), granted_days=15, used_days=4,
    )

    login_as(viewer)
    resp = client.get("/admin/employees")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "현황조회대상" in body
    assert "11" in body  # 잔여 15-4=11


def test_employees_overview_excludes_resigned_employees(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="관리자2")
    make_employee(hire_date=date(2018, 1, 1), name="퇴사자표시안됨", status="퇴사")

    login_as(viewer)
    resp = client.get("/admin/employees")

    assert "퇴사자표시안됨".encode("utf-8") not in resp.data


def test_employees_overview_filters_by_department(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="관리자3")
    make_employee(hire_date=date(2018, 1, 1), name="개발팀직원", department="개발팀")
    make_employee(hire_date=date(2018, 1, 1), name="영업팀직원", department="영업팀")

    login_as(viewer)
    resp = client.get("/admin/employees?department=개발팀")
    body = resp.data.decode("utf-8")

    assert "개발팀직원" in body
    assert "영업팀직원" not in body


def test_employees_overview_shows_upcoming_service_leave_milestone_notice(
    make_employee, client, login_as
):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="관리자4")
    anniversary = TODAY + timedelta(days=20)  # 30일 이내 도래 예정
    hire_date = anniversary.replace(year=anniversary.year - 5)
    make_employee(hire_date=hire_date, name="곧5년차", department="지원팀")

    login_as(viewer)
    resp = client.get("/admin/employees")
    body = resp.data.decode("utf-8")

    assert "근속특별휴가 발생 예정자" in body
    assert "곧5년차" in body


def test_employees_overview_highlights_expiring_service_leave_grant(
    make_employee, make_grant, client, login_as
):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="관리자5")
    target = make_employee(hire_date=date(2015, 1, 1), name="만료임박대상")
    make_grant(
        target, grant_type="근속특별휴가",
        grant_date=date(2020, 1, 1), expire_date=TODAY + timedelta(days=20),
        granted_days=3, used_days=1,
    )

    login_as(viewer)
    resp = client.get("/admin/employees")
    body = resp.data.decode("utf-8")

    assert "만료임박대상" in body
    assert "근속휴가 만료 임박" in body


def test_rules_list_shows_seeded_rules(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="규칙조회자")
    login_as(viewer)

    resp = client.get("/admin/rules")
    body = resp.data.decode("utf-8")

    assert "연차가산" in body
    assert "근속특별휴가" in body
    assert "법정재정산" in body


def test_rules_edit_updates_condition_and_value_and_affects_calculation(
    make_employee, client, login_as, app_ctx
):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="규칙수정자")
    login_as(viewer)

    rule = get_rule("연차가산")
    assert rule is not None

    resp = client.post(
        f"/admin/rules/{rule.rule_id}/edit",
        data={
            "condition": '{"offset_years": 0, "interval_years": 2, "days_per_interval": 1}',
            "value": '{"max_days": 20}',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    updated_rule = get_rule("연차가산")
    assert calculate_annual_leave_addon_days(4, updated_rule) == 2  # (4 - offset 0) // 2


def test_rules_edit_rejects_invalid_json(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="규칙수정자2")
    login_as(viewer)

    rule = get_rule("연차가산")
    resp = client.post(
        f"/admin/rules/{rule.rule_id}/edit",
        data={"condition": "{이건 JSON이 아님", "value": '{"max_days": 25}'},
        follow_redirects=False,
    )

    assert resp.status_code == 200  # 에러와 함께 같은 폼 재표시
    assert "JSON".encode("utf-8") in resp.data or "유효한".encode("utf-8") in resp.data

    unchanged_rule = get_rule("연차가산")
    assert unchanged_rule.condition != "{이건 JSON이 아님"


# ---------------------------------------------------------------------------
# 휴가 일괄 부여 실행 버튼 (/admin/run-leave-batch)
# ---------------------------------------------------------------------------


def test_run_leave_batch_grants_annual_and_service_leave_and_flashes_summary(
    make_employee, client, login_as
):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="배치실행자")
    target = make_employee(hire_date=date(2018, 1, 1), name="배치대상")  # 근속 6년 -> 5년차 대상

    login_as(viewer)
    resp = client.post("/admin/run-leave-batch", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "신규 부여" in body

    resp = client.get("/admin/employees")
    body = resp.data.decode("utf-8")
    assert "배치대상" in body


def test_run_leave_batch_is_safe_to_click_twice(make_employee, client, login_as):
    viewer = make_employee(hire_date=date(2015, 1, 1), name="배치실행자2")
    make_employee(hire_date=date(2018, 1, 1), name="배치대상2")

    login_as(viewer)
    client.post("/admin/run-leave-batch", follow_redirects=False)
    resp = client.post("/admin/run-leave-batch", follow_redirects=True)

    body = resp.data.decode("utf-8")
    assert "0명 신규 부여" in body or "연차 0명" in body
