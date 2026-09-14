from app.extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    emp_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(50))
    position = db.Column(db.String(50))
    hire_date = db.Column(db.Date, nullable=False)
    resign_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(10), nullable=False, default="재직")  # 재직 / 퇴사

    leave_grants = db.relationship(
        "LeaveGrant", back_populates="employee", cascade="all, delete-orphan"
    )
    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="employee",
        foreign_keys="LeaveRequest.emp_id",
        cascade="all, delete-orphan",
    )
    settlements = db.relationship(
        "ResignationSettlement", back_populates="employee", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "emp_id": self.emp_id,
            "name": self.name,
            "department": self.department,
            "position": self.position,
            "hire_date": self.hire_date.isoformat() if self.hire_date else None,
            "resign_date": self.resign_date.isoformat() if self.resign_date else None,
            "status": self.status,
        }


class LeaveGrant(db.Model):
    """휴가 부여 항목 (건별 관리, 이월 없음)"""

    __tablename__ = "leave_grants"

    grant_id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.Integer, db.ForeignKey("employees.emp_id"), nullable=False)
    grant_type = db.Column(db.String(20), nullable=False)  # 연차 / 근속특별휴가
    grant_date = db.Column(db.Date, nullable=False)
    expire_date = db.Column(db.Date, nullable=False)
    granted_days = db.Column(db.Float, nullable=False)
    used_days = db.Column(db.Float, nullable=False, default=0)
    source_rule = db.Column(db.String(100))

    employee = db.relationship("Employee", back_populates="leave_grants")


class LeaveRequest(db.Model):
    """휴가 신청"""

    __tablename__ = "leave_requests"

    request_id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.Integer, db.ForeignKey("employees.emp_id"), nullable=False)
    request_date = db.Column(db.Date, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days_used = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="신청")  # 신청/승인/반려/취소
    approver_id = db.Column(db.Integer, db.ForeignKey("employees.emp_id"), nullable=True)

    employee = db.relationship(
        "Employee", back_populates="leave_requests", foreign_keys=[emp_id]
    )
    approver = db.relationship("Employee", foreign_keys=[approver_id])


class LeaveRule(db.Model):
    """휴가 규칙 (하드코딩 금지, 설정값으로 관리)"""

    __tablename__ = "leave_rules"

    rule_id = db.Column(db.Integer, primary_key=True)
    rule_type = db.Column(db.String(20), nullable=False)  # 연차가산/근속특별휴가/법정재정산
    condition = db.Column(db.Text)
    value = db.Column(db.Text)


class ResignationSettlement(db.Model):
    """퇴사 정산"""

    __tablename__ = "resignation_settlements"

    settlement_id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.Integer, db.ForeignKey("employees.emp_id"), nullable=False)
    company_basis_days = db.Column(db.Float)
    legal_basis_days = db.Column(db.Float)
    excess_used_days = db.Column(db.Float)
    unused_remaining_days = db.Column(db.Float)
    settlement_date = db.Column(db.Date, nullable=False)

    employee = db.relationship("Employee", back_populates="settlements")
