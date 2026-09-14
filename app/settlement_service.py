"""퇴사 정산 처리.

회사 기준 부여량(leave_grants 중 '연차' 합계)과 법정 기준 발생량
(rules_engine.calculate_legal_basis)을 대조하여 초과 사용 여부와
미사용 잔여를 자동 판정하고 resignation_settlements에 저장한다.

- 회사 기준 부여량 집계 대상은 grant_type='연차'만 포함한다. 근속특별휴가는
  법정 연차와 무관한 회사 복리후생성 휴가이므로 법정 재정산 대상에서 제외한다.
- 퇴사일 이후에 부여된 leave_grants(예: 다음 회계연도분)는 집계에서 제외한다.
- excess_used_days(초과 사용) = max(0, 실사용일수 - 법정기준발생량)
- unused_remaining_days(미사용 잔여) = max(0, 회사기준부여량 - 실사용일수)
  (법정기준발생량은 아직 TODO 더미값이므로, 확정되면 위 두 계산식도 함께 검토 필요)
- 퇴사 처리와 정산 저장은 하나의 흐름으로 묶여 있으며, employees.status를
  '퇴사'로, resign_date를 지정한 퇴사일로 갱신한다.
"""

from app.extensions import db
from app.models import LeaveGrant, ResignationSettlement
from app.rules_engine import calculate_legal_basis


def process_resignation_settlement(employee, resign_date, session=None):
    """employee를 퇴사 처리하고 퇴사 정산 결과를 계산/저장한다."""
    session = session or db.session

    if employee.status == "퇴사":
        raise ValueError("이미 퇴사 처리된 직원입니다.")

    annual_grants = (
        LeaveGrant.query.filter_by(emp_id=employee.emp_id, grant_type="연차")
        .filter(LeaveGrant.grant_date <= resign_date)
        .all()
    )
    company_basis_days = sum(g.granted_days for g in annual_grants)
    used_days_total = sum(g.used_days for g in annual_grants)
    legal_basis_days = calculate_legal_basis(employee, resign_date)

    excess_used_days = max(0, used_days_total - legal_basis_days)
    unused_remaining_days = max(0, company_basis_days - used_days_total)

    settlement = ResignationSettlement(
        emp_id=employee.emp_id,
        company_basis_days=company_basis_days,
        legal_basis_days=legal_basis_days,
        excess_used_days=excess_used_days,
        unused_remaining_days=unused_remaining_days,
        settlement_date=resign_date,
    )
    session.add(settlement)

    employee.status = "퇴사"
    employee.resign_date = resign_date

    return settlement
