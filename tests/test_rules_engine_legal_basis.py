"""법정재정산 - calculate_legal_basis 단위 테스트.

근로기준법 조항이 아직 미정이므로, 이 단계에서는
- 1년 미만/1년 이상 근속을 올바르게 구분해서 각각의 헬퍼로 분기하는지
- 실제 계산 없이 더미값(0)을 반환하는지
만 검증한다. 조항이 확정되면 아래 테스트를 실제 기대값으로 교체한다.
"""

from datetime import date

from app.rules_engine import calculate_legal_basis


def test_calculate_legal_basis_under_1_year_returns_dummy_zero():
    hire_date = date(2024, 1, 1)
    resign_date = date(2024, 8, 1)  # 근속 7개월 -> 1년 미만 (월차 갈래)

    assert calculate_legal_basis(_make_employee(hire_date), resign_date) == 0


def test_calculate_legal_basis_1_year_or_more_returns_dummy_zero():
    hire_date = date(2020, 1, 1)
    resign_date = date(2024, 3, 1)  # 근속 4년 -> 1년 이상 (연차 갈래)

    assert calculate_legal_basis(_make_employee(hire_date), resign_date) == 0


def test_calculate_legal_basis_dispatches_to_correct_branch_by_service_years(monkeypatch):
    import app.rules_engine as rules_engine

    calls = []
    monkeypatch.setattr(
        rules_engine,
        "_calculate_legal_basis_under_1year",
        lambda employee, resign_date, rule=None: calls.append("under_1year") or 0,
    )
    monkeypatch.setattr(
        rules_engine,
        "_calculate_legal_basis_1year_or_more",
        lambda employee, resign_date, rule=None: calls.append("1year_or_more") or 0,
    )

    hire_date = date(2024, 1, 1)
    rules_engine.calculate_legal_basis(_make_employee(hire_date), date(2024, 6, 1))  # 5개월
    rules_engine.calculate_legal_basis(_make_employee(hire_date), date(2026, 6, 1))  # 2년 6개월

    assert calls == ["under_1year", "1year_or_more"]


def _make_employee(hire_date):
    """calculate_legal_basis가 필요로 하는 최소한의 속성(hire_date)만 가진 더미 직원."""

    class _Employee:
        pass

    employee = _Employee()
    employee.hire_date = hire_date
    return employee
