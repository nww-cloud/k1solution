import json

from app.extensions import db
from app.models import LeaveRule


def seed_leave_rules():
    """leave_rules 초기 시드 데이터. 이미 데이터가 있으면 아무것도 하지 않는다."""
    if LeaveRule.query.count() > 0:
        return

    rules = [
        LeaveRule(
            rule_type="근속특별휴가",
            condition=json.dumps(
                {"5년차": "3일", "10년차": "5일", "15년차": "8일", "20년차": "10일"},
                ensure_ascii=False,
            ),
            value=json.dumps({"valid_years": 5}, ensure_ascii=False),
        ),
        LeaveRule(
            rule_type="연차가산",
            # 근로기준법 제60조 제4항: 최초 1년 초과 근속연수 매 2년마다 1일 가산
            condition=json.dumps(
                {"offset_years": 1, "interval_years": 2, "days_per_interval": 1},
                ensure_ascii=False,
            ),
            value=json.dumps({"max_days": 25}, ensure_ascii=False),
        ),
        LeaveRule(
            rule_type="법정재정산",
            condition="TODO",
            value="TODO",
        ),
    ]
    db.session.add_all(rules)
    db.session.commit()
